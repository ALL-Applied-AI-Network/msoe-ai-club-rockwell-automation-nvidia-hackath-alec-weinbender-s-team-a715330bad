"""Long-running job process:  python -m app.worker <job_id>

Runs detached from the API server (survives API reloads), parallelises candidate
evaluation across CPU cores, prunes hopeless candidates early, checkpoints every
trial to SQLite so a crashed/cancelled job can be resumed without losing work.
"""
import json, math, os, sys, traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
import optuna
from . import adapters as A, db

optuna.logging.set_verbosity(optuna.logging.WARNING)

def wilson(s, n, z=1.96):
    if n == 0: return 0.0, 1.0
    p = s / n; den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0, c - h), min(1, c + h)

def evaluate_design(part, design, cfg, best_rate):
    """Runs in a pool process. Repeated grasps with camera-error offsets, in chunks,
    stopping early when the Wilson upper bound can't beat the current best (multi-fidelity pruning)."""
    import time; t0 = time.time()
    n, chunk, s, done, pruned = cfg["n_grasps"], 10, 0, 0, False
    while done < n:
        hi = min(n, done + chunk)
        offs = [A.offset_for(i, cfg["sigma_mm"], cfg["sigma_deg"], cfg["seed"]) for i in range(done, hi)]
        s += sum(A.sim_batch(part, design, offs))
        done = hi
        if cfg.get("prune", True) and best_rate is not None and done >= 20 and done < n and wilson(s, done)[1] < best_rate - 0.02:
            pruned = True; break
    return {"n_grasps": done, "n_success": s, "rate": s / done, "pruned": pruned, "duration": time.time() - t0}

def dists(template):
    return {"template": optuna.distributions.CategoricalDistribution(A.TEMPLATES),
            **{f"{template}.{k}": optuna.distributions.FloatDistribution(lo, hi) for k, (lo, hi) in A.SPACE[template].items()}}

def flat(template, params):
    return {"template": template, **{f"{template}.{k}": v for k, v in A.clamp_design(template, params).items()}}

def gpu_info():
    import subprocess
    try:
        return subprocess.run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"], capture_output=True, text=True, timeout=5).stdout.strip() or None
    except Exception:
        return None

def run_job(job_id):
    import platform, time
    t_start = time.time()
    job = db.decode(db.row("SELECT * FROM jobs WHERE id=?", (job_id,)))
    cfg, part = json.loads(json.dumps(job["config"])), job["part"]
    db.update_job(job_id, status="running", pid=os.getpid(), error=None, cancel_requested=0)
    try:
        # ---- stage 1: LLM proposals (stored verbatim for later training) ----
        if not db.rows("SELECT id FROM suggestions WHERE job_id=?", (job_id,)):
            db.update_job(job_id, stage="llm")
            sugg, source, model, raw = A.llm_suggest(part, job["task"], cfg["n_suggestions"])
            for i, s in enumerate(sugg):
                t = s["template"] if s["template"] in A.SPACE else "flat_pad"
                db.run("INSERT INTO suggestions(job_id,idx,template,params,rationale,source,model,raw_response,created) VALUES(?,?,?,?,?,?,?,?,?)",
                       (job_id, i, t, json.dumps(A.clamp_design(t, s.get("params", {}))), s.get("rationale", ""), source, model, raw, db.now()))

        # ---- stage 2: Bayesian optimisation (ask/tell, parallel, resumable) ----
        db.update_job(job_id, stage="optimize", n_total=cfg["budget"])
        study = optuna.create_study(direction="maximize", sampler=optuna.samplers.TPESampler(
            multivariate=True, group=True, seed=cfg["seed"], n_startup_trials=max(cfg["n_suggestions"], 8)))
        done = db.rows("SELECT * FROM trials WHERE job_id=? ORDER BY number", (job_id,))
        for r in done:  # replay checkpoint
            p = json.loads(r["params"])
            study.add_trial(optuna.trial.create_trial(params=flat(r["template"], p), distributions=dists(r["template"]), value=r["success_rate"]))
        number = len(done)
        for s in db.rows("SELECT * FROM suggestions WHERE job_id=? AND trial_number IS NULL ORDER BY idx", (job_id,)):
            study.enqueue_trial(flat(s["template"], json.loads(s["params"])))
        best_rate = max([r["success_rate"] for r in done if not r["pruned"]], default=None)
        stale, patience = 0, cfg.get("patience", 25)
        workers = cfg.get("workers") or max(1, (os.cpu_count() or 2) - 1)

        with ProcessPoolExecutor(workers) as pool:
            while number < cfg["budget"] and stale < patience:
                if db.row("SELECT cancel_requested c FROM jobs WHERE id=?", (job_id,))["c"]:
                    db.update_job(job_id, status="cancelled", stage=None); return
                batch = []
                for _ in range(min(workers, cfg["budget"] - number)):
                    tr = study.ask()
                    tpl = tr.suggest_categorical("template", A.TEMPLATES)
                    params = {k: tr.suggest_float(f"{tpl}.{k}", lo, hi) for k, (lo, hi) in A.SPACE[tpl].items()}
                    batch.append((tr, tpl, params))
                futs = {pool.submit(evaluate_design, part, {"template": t, "params": p}, cfg, best_rate): (tr, t, p) for tr, t, p in batch}
                for f in as_completed(futs):
                    tr, tpl, params = futs[f]; r = f.result()
                    study.tell(tr, r["rate"])
                    sid = None
                    for s in db.rows("SELECT id,template,params FROM suggestions WHERE job_id=? AND trial_number IS NULL", (job_id,)):
                        if s["template"] == tpl and all(abs(json.loads(s["params"])[k] - v) < 1e-9 for k, v in params.items()):
                            sid = s["id"]; db.run("UPDATE suggestions SET trial_number=? WHERE id=?", (number, sid)); break
                    db.run("INSERT INTO trials(job_id,number,template,params,success_rate,n_grasps,n_success,pruned,suggestion_id,duration,created) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                           (job_id, number, tpl, json.dumps(params), r["rate"], r["n_grasps"], r["n_success"], int(r["pruned"]), sid, r["duration"], db.now()))
                    number += 1
                    if not r["pruned"] and (best_rate is None or r["rate"] > best_rate + 0.005): best_rate, stale = r["rate"], 0
                    else: stale += 1
                    db.update_job(job_id, n_done=number, best_value=best_rate)

        # ---- stage 3: pick winner among fully-evaluated trials, emit outputs ----
        db.update_job(job_id, stage="finalize")
        sugg_src = (db.row("SELECT source,model FROM suggestions WHERE job_id=? LIMIT 1", (job_id,)) or {})
        # re-validate the top 3 on fresh perturbations (new seed, 3x grasps) to avoid winner's-curse bias;
        # the validated rate is what we report as the predicted success rate.
        top = db.rows("SELECT * FROM trials WHERE job_id=? AND pruned=0 ORDER BY success_rate DESC, number LIMIT 3", (job_id,))
        vcfg = {**cfg, "seed": cfg["seed"] + 1, "n_grasps": cfg["n_grasps"] * 3, "prune": False}
        with ProcessPoolExecutor(min(3, workers)) as pool:
            vals = list(pool.map(evaluate_design, [part] * len(top),
                                 [{"template": t["template"], "params": json.loads(t["params"])} for t in top],
                                 [vcfg] * len(top), [None] * len(top)))
        k = max(range(len(top)), key=lambda i: vals[i]["rate"])
        w, v = top[k], vals[k]; design = {"template": w["template"], "params": json.loads(w["params"])}
        lo, hi = wilson(v["n_success"], v["n_grasps"])
        scad = db.DATA / "outputs" / f"{job_id}.scad"; scad.write_text(A.make_scad(part, design))
        db.run("INSERT OR REPLACE INTO results VALUES(?,?,?,?,?,?,?,?,?,?)",
               (job_id, w["number"], w["template"], w["params"], json.dumps(A.grasp_pose(part, design)), v["rate"], lo, hi, str(scad), db.now()))
        db.run("INSERT OR REPLACE INTO run_meta VALUES(?,?)", (job_id, json.dumps({
            "started": t_start, "runtime_s": time.time() - t_start, "config": cfg, "part": part,
            "llm": {"backend": sugg_src, "prompt_version": A.PROMPT_VERSION},
            "sim_backend": os.environ.get("SIM_BACKEND", "mock"), "sim_url": os.environ.get("SIM_URL"),
            "optuna": optuna.__version__, "python": platform.python_version(), "cpus": os.cpu_count(), "gpu": gpu_info(),
            "n_trials": number, "n_pruned": db.row("SELECT COUNT(*) c FROM trials WHERE job_id=? AND pruned=1", (job_id,))["c"]})))
        db.update_job(job_id, status="done", stage=None, best_value=v["rate"], best_trial=w["number"], finished=db.now())
    except Exception:
        db.update_job(job_id, status="failed", error=traceback.format_exc()[-2000:])

if __name__ == "__main__":
    db.init(); run_job(sys.argv[1])
