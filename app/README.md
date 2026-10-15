# Finger Designer (web app)

Web front end + job runner bridging the user to the LLM and the simulation/optimization back end.

```
app/
├── backend/          FastAPI API (main.py), detached optimizer worker (worker.py),
│                     LLM/sim adapters + design space (adapters.py), SQLite layer (db.py)
├── frontend/         single-file UI (index.html), served by the backend at /
├── data/             runtime only, gitignored: app.db, uploads/, outputs/, worker.log
└── requirements.txt
```

Run from this `app/` directory:

    pip install -r requirements.txt
    python -m uvicorn backend.main:app --port 8000      # open http://localhost:8000

Runs end-to-end out of the box with a **mock** LLM and **mock** simulator. Wire in the real models via env vars (see [`../.env.example`](../.env.example)):

| Variable | Effect |
|---|---|
| `ANTHROPIC_API_KEY` (+ optional `LLM_MODEL`) | LLM step uses Claude |
| `LLM_BACKEND=http`, `LLM_URL` | POST `{part,task,k}` -> `{suggestions:[{template,params,rationale}]}` |
| `SIM_BACKEND=http`, `SIM_URL` | POST `{part,design,offsets:[...]}` -> `{successes:[bool,...]}` (a batch of grasps in the ER-4iA twin) |
| `DATA_DIR` | Where the SQLite DB, uploads and outputs go (default `app/data/`) |

Template/parameter ranges: `backend/adapters.py` (`SPACE`). Replace `make_scad` with a real CAD export (e.g. CadQuery -> STEP/STL).

## Long-running optimization
- Each job is a **detached process** (`python -m backend.worker <id>`), not a request thread: closing the browser or restarting the API doesn't kill it.
- Candidates evaluate **in parallel** across CPU cores (ask/tell Bayesian optimization, TPE).
- **Early pruning**: grasps run in chunks of 10; a candidate stops once its Wilson upper bound can't beat the current best.
- **Common random numbers**: grasp *i* uses the same camera-error offset for every design => fairer, lower-variance comparison.
- LLM suggestions are **warm-start trials**; early stopping after 25 candidates with no improvement.
- **Checkpointed** to SQLite after every trial; interrupted/cancelled jobs can be resumed from the UI.
- The reported success rate comes from **re-validating the top 3 on fresh perturbations (3x grasps)**, so it isn't inflated by picking the max of many noisy trials.
- Live progress via Server-Sent Events.

Further speed-ups when the real sim is plugged in: headless/no-render mode, N simulator instances per worker, GPU-batched
physics (many grasps per call), lower grasp count in early rounds, and later the stretch-goal surrogate to skip bad candidates.
For running remotely, point `SIM_URL` at a GPU box, or move `backend/worker.py` behind a queue (Celery/RQ) - the DB layer is the only shared state.

## Simulator service
`SIM_URL` should point at [`../sim/sim_server/server.py`](../sim/sim_server/server.py), which runs next to Isaac Sim and the
[FANUC ER-4iA twin](../sim/fanuc_er4ia_sim/). It is still a stub (`run_grasps` raises `NotImplementedError`).

> **Gripper-fit warning:** the twin's actuator is an SMC MHZL2-16D2 (6 mm travel per jaw, 12 mm max straight-face gap,
> ~16 mm at the hooked tips). The default "tennis balls" example and the `SPACE` ranges here assume much larger parts.
> Read [../CONTEXT.md](../CONTEXT.md) before choosing the demo part.

## Training data for the stretch goal
Everything is in `data/app.db` (relative to `app/`) and exportable:
- `GET /api/export/suggestions.jsonl` - each LLM proposal (template, params, rationale, model, raw output) + its simulated success rate + the job's best. Label good/bad (e.g. within X of best) to train the "reject bad LLM suggestions" filter.
- `GET /api/export/trials.jsonl` - every simulated design (features, success rate, n_grasps, `from_llm`, `chosen_best`) for the instant success-rate predictor.
Raw LLM responses and uploaded CAD files are kept, so you can re-featurize later (e.g. part geometry embeddings).

## Not done yet
CAD/image parsing (part size is entered manually; the file is stored), real CAD output, auth, and a hardware-validation (stage 5) tracking page.
