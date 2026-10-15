import asyncio, json, os, subprocess, sys, uuid
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from . import adapters, db

ROOT = Path(__file__).resolve().parent.parent

def pid_alive(pid):
    if not pid: return False
    try:
        if os.name == "nt":
            out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True).stdout
            return str(pid) in out
        os.kill(pid, 0); return True
    except OSError:
        return False

def spawn(job_id):
    """Start the optimisation as a detached process so it never blocks (or dies with) the web server."""
    kw = {"creationflags": 0x00000008 | 0x00000200} if os.name == "nt" else {"start_new_session": True}
    p = subprocess.Popen([sys.executable, "-m", "app.worker", job_id], cwd=ROOT,
                         stdout=open(db.DATA / "worker.log", "a"), stderr=subprocess.STDOUT, **kw)
    db.update_job(job_id, status="queued", pid=p.pid)

@asynccontextmanager
async def lifespan(app):
    db.init()
    for j in db.rows("SELECT id,pid FROM jobs WHERE status IN ('queued','running')"):
        if not pid_alive(j["pid"]):
            db.update_job(j["id"], status="interrupted")   # resumable from checkpoint
    yield

app = FastAPI(lifespan=lifespan)

def job_view(j):
    j = db.decode(j)
    j["progress"] = (j["n_done"] / j["n_total"]) if j["n_total"] else 0
    return j

@app.get("/api/meta")
def meta():
    return {"templates": adapters.SPACE,
            "llm": os.environ.get("LLM_BACKEND") or ("anthropic" if os.environ.get("ANTHROPIC_API_KEY") else "mock"),
            "sim": os.environ.get("SIM_BACKEND", "mock"), "cpus": os.cpu_count()}

@app.post("/api/jobs")
async def create_job(task: str = Form(...), shape: str = Form("sphere"), diameter_mm: float = Form(40),
                     length_mm: float = Form(40), mass_g: float = Form(50), sigma_mm: float = Form(3),
                     sigma_deg: float = Form(8), n_suggestions: int = Form(6), budget: int = Form(60),
                     n_grasps: int = Form(40), workers: int = Form(0), seed: int = Form(0),
                     part_file: UploadFile | None = File(None)):
    job_id = uuid.uuid4().hex[:10]; path = None; name = "manual"
    if part_file and part_file.filename:
        name = Path(part_file.filename).name
        path = db.DATA / "uploads" / f"{job_id}_{name}"
        path.write_bytes(await part_file.read())
    part = {"shape": shape, "diameter_mm": diameter_mm, "length_mm": length_mm, "mass_g": mass_g}
    cfg = {"sigma_mm": sigma_mm, "sigma_deg": sigma_deg, "n_suggestions": n_suggestions, "budget": budget,
           "n_grasps": n_grasps, "workers": workers, "seed": seed, "patience": 25, "prune": True}
    db.run("INSERT INTO jobs(id,created,status,part_name,part_path,part,task,config,n_total) VALUES(?,?,?,?,?,?,?,?,?)",
           (job_id, db.now(), "queued", name, str(path) if path else None, json.dumps(part), task, json.dumps(cfg), budget))
    spawn(job_id)
    return {"id": job_id}

@app.get("/api/jobs")
def list_jobs():
    return [job_view(j) for j in db.rows("SELECT * FROM jobs ORDER BY created DESC")]

@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    j = db.row("SELECT * FROM jobs WHERE id=?", (job_id,))
    if not j: raise HTTPException(404)
    out = job_view(j)
    out["suggestions"] = [db.decode(s) for s in db.rows(
        "SELECT id,idx,template,params,rationale,source,model,trial_number FROM suggestions WHERE job_id=? ORDER BY idx", (job_id,))]
    out["trials"] = [db.decode(t) for t in db.rows(
        "SELECT number,template,params,success_rate,n_grasps,pruned,suggestion_id FROM trials WHERE job_id=? ORDER BY number", (job_id,))]
    out["result"] = db.decode(db.row("SELECT * FROM results WHERE job_id=?", (job_id,)))
    m = db.decode(db.row("SELECT meta FROM run_meta WHERE job_id=?", (job_id,)))
    out["meta"] = m["meta"] if m else None
    out["review"] = db.row("SELECT status,reviewer,notes,created FROM reviews WHERE job_id=?", (job_id,))
    out["physical"] = db.rows("SELECT * FROM physical_trials WHERE job_id=? ORDER BY id", (job_id,))
    return out

@app.get("/api/jobs/{job_id}/events")
async def events(job_id: str):
    """Server-sent events: pushes job state so the UI updates live without client polling logic."""
    async def gen():
        last = None
        while True:
            j = db.row("SELECT status,stage,n_done,n_total,best_value FROM jobs WHERE id=?", (job_id,))
            if not j: return
            s = json.dumps(j)
            if s != last:
                yield f"data: {s}\n\n"; last = s
            if j["status"] in ("done", "failed", "cancelled", "interrupted"): return
            await asyncio.sleep(1)
    return StreamingResponse(gen(), media_type="text/event-stream")

@app.post("/api/jobs/{job_id}/cancel")
def cancel(job_id: str):
    db.update_job(job_id, cancel_requested=1)
    return {"ok": True}

@app.post("/api/jobs/{job_id}/resume")
def resume(job_id: str):
    j = db.row("SELECT status FROM jobs WHERE id=?", (job_id,))
    if not j or j["status"] not in ("interrupted", "cancelled", "failed"): raise HTTPException(409, "not resumable")
    spawn(job_id)
    return {"ok": True}

@app.get("/api/jobs/{job_id}/scad")
def scad(job_id: str):
    r = db.row("SELECT scad_path FROM results WHERE job_id=?", (job_id,))
    if not r: raise HTTPException(404)
    return FileResponse(r["scad_path"], filename=f"fingers_{job_id}.scad")

# ---- safety review gate + physical trial log (plant rules: no printed finger on the arm until reviewed) ----
@app.post("/api/jobs/{job_id}/review")
def review(job_id: str, status: str = Form(...), reviewer: str = Form(""), notes: str = Form("")):
    if status not in ("approved", "rejected", "pending"): raise HTTPException(422, "bad status")
    if status == "approved" and not reviewer.strip(): raise HTTPException(422, "reviewer name required")
    db.run("INSERT OR REPLACE INTO reviews VALUES(?,?,?,?,?)", (job_id, status, reviewer, notes, db.now()))
    return {"ok": True}

@app.post("/api/jobs/{job_id}/physical")
def add_physical(job_id: str, finger: str = Form("optimized"), success: int = Form(...), placement_error_mm: float | None = Form(None),
                 cycle_time_s: float | None = Form(None), recovered: int = Form(0), operator_intervention: int = Form(0), notes: str = Form("")):
    db.run("INSERT INTO physical_trials(job_id,created,finger,success,placement_error_mm,cycle_time_s,recovered,operator_intervention,notes) VALUES(?,?,?,?,?,?,?,?,?)",
           (job_id, db.now(), finger, success, placement_error_mm, cycle_time_s, recovered, operator_intervention, notes))
    return {"ok": True}

@app.get("/api/export/physical.jsonl")
def export_physical():
    return jsonl(db.rows("SELECT * FROM physical_trials"))

# ---- training-data export (stretch goal) ----
def part_key(part):
    return f"{part['shape']}-{part['diameter_mm']:g}x{part['length_mm']:g}"   # split train/test BY PART, not by row

def jsonl(items):
    return Response("\n".join(json.dumps(i) for i in items), media_type="application/x-ndjson")

@app.get("/api/export/trials.jsonl")
def export_trials():
    """One row per simulated design: features + label (success_rate), with context to train a surrogate."""
    out = []
    for t in db.rows("""SELECT t.*, j.part, j.task, j.config, r.trial_number AS chosen FROM trials t
                        JOIN jobs j ON j.id=t.job_id LEFT JOIN results r ON r.job_id=t.job_id"""):
        t = db.decode(t)
        out.append({"job_id": t["job_id"], "part_key": part_key(t["part"]), "part": t["part"], "task": t["task"],
                    "sigma_mm": t["config"]["sigma_mm"], "sigma_deg": t["config"]["sigma_deg"],
                    "template": t["template"], "params": t["params"], "success_rate": t["success_rate"],
                    "n_grasps": t["n_grasps"], "pruned": bool(t["pruned"]),
                    "from_llm": t["suggestion_id"] is not None, "chosen_best": t["chosen"] == t["number"]})
    return jsonl(out)

@app.get("/api/export/suggestions.jsonl")
def export_suggestions():
    """Every LLM proposal with its simulated outcome and the job's best: labels for a 'reject bad suggestion' classifier."""
    out = []
    for s in db.rows("""SELECT s.*, j.part, j.task, j.config, t.success_rate, t.n_grasps, r.predicted_success AS best
                        FROM suggestions s JOIN jobs j ON j.id=s.job_id
                        LEFT JOIN trials t ON t.job_id=s.job_id AND t.number=s.trial_number
                        LEFT JOIN results r ON r.job_id=s.job_id"""):
        s = db.decode(s)
        out.append({"job_id": s["job_id"], "part_key": part_key(s["part"]), "part": s["part"], "task": s["task"],
                    "sigma_mm": s["config"]["sigma_mm"], "sigma_deg": s["config"]["sigma_deg"],
                    "template": s["template"], "params": s["params"], "rationale": s["rationale"],
                    "source": s["source"], "model": s["model"], "success_rate": s["success_rate"],
                    "n_grasps": s["n_grasps"], "job_best": s["best"]})
    return jsonl(out)

app.mount("/", StaticFiles(directory=ROOT / "static", html=True), name="static")
