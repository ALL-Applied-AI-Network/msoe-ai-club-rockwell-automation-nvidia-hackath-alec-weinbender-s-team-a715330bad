# Auto-Grasp (web app)

Web front end + job runner: takes a part, searches finger designs in the simulator, and reports the best one next to the
stock and imprint baselines.

```text
app/
├── backend/              uv workspace member "backend"; layout rules in ../.claude/rules/coding-style.md
│   ├── pyproject.toml    dependencies
│   ├── alembic.ini       database migrations CLI
│   ├── src/api/          main.py (API + lifespan), worker.py (detached job process), config.py (settings + secrets),
│   │                     routers/ -> services/ -> clients/ (sim, cad, llm, database), models/ (domain objects),
│   │                     db/ (SQLAlchemy tables + Alembic migrations)
│   └── tests/            pytest: routers/, services/, clients/, models/, db/
├── frontend/             npm project: Vite + React + TypeScript (see "Frontend" below)
│   ├── index.html        the old single-file UI: the page at /, from the backend and from the dev server
│   ├── app.html, src/    the new React UI, at /app.html on the dev server; src/backend/ is the typed API client
│   ├── public/           static files: task-examples/, the Isaac Sim video of each task for the wizard's task step
│   └── dist/             npm run build output (the new UI only), gitignored
└── data/                 runtime only, gitignored: app.db, uploads/, outputs/, worker.log
```

Run from the repo root:

```bash
uv sync --all-packages
uv run --package backend uvicorn api.main:app --port 8000      # open http://localhost:8000
uv run pytest                                                   # backend tests, offline
```

Add a dependency with `uv add --package backend <dep>`. BoTorch's PyTorch comes from the CPU-only index (root
`pyproject.toml`): the optimizer's GP is small, and the GPU belongs to Isaac.

Runs end-to-end out of the box with the **mock** simulator. Configure the real one in the repo-root `.env` (loaded
automatically; real environment variables win). Every variable is in [`../.env.example`](../.env.example):

| Variable | Effect |
|---|---|
| `SIM_BACKEND=http`, `SIM_URL` | The sim server's base URL; each round is one `POST {SIM_URL}/evaluate_batch` (contract below) |
| `SIM_TIMEOUT_S` | Per-request timeout; a request is a whole round (default 3600 s) |
| `SIM_RECONNECT_MINUTES` | How long a round whose connection drops waits for the sim to answer again (default 120; 0 fails at once) |
| `DATA_DIR` | Where the SQLite DB, uploads and outputs go (default `app/data/`) |
| `DB_URL` | Another database instead of the SQLite file, e.g. Postgres |
| `ANTHROPIC_API_KEY`, `LLM_*` | The LLM client. The optimizer doesn't call it at the moment |
| `COMPUTE_BACKENDS=brev,gb10`, `COMPUTE_*` | The GPU targets the app connects the sim to: Brev and the MSOE GB10 (see "GPU from the app") |

If a selected backend is missing its key or URL, the API logs which variable and refuses to start.

## GPU from the app

**The rest of the app doesn't know where the sim runs.** Jobs, workers and the optimizer only ever send batches to
`SIM_URL` (`SIM_BACKEND=http`). The GPU panel decides which machine answers there: it connects one target at a time and
forwards its sim server to `SIM_URL`'s port on this machine. Only `clients/compute.py`, `services/compute.py`,
`compute_worker.py`, `routers/compute.py` and the panel know about Brev or the GB10. Results are badged by the sim
(`isaac` or `mock`), not by the machine.

`COMPUTE_BACKENDS` lists the targets (`brev,gb10`; `mock` shows made-up ones for working offline):

| | Brev | MSOE GB10 |
| --- | --- | --- |
| Targets | the team's instances (new ones are created in the Brev console) | `spark1`, always on, shared with other teams |
| The panel's action | **Start** the instance, **Stop** it | **Connect**, **Disconnect** |
| Ends by itself | after `COMPUTE_AUTO_STOP_MINUTES` (default 20) without a job or prediction | never: one person's idle timer mustn't end a teammate's job on the shared server |
| On stop / disconnect | the instance stops | only the forward closes; the sim server keeps running for teammates |
| On failure | the instance is stopped too, so it can't use credits | nothing is stopped |
| Reached with | the Brev CLI (`brev start`, `brev exec`, `brev port-forward`) | `ssh` with your key, on the MSOE VPN |
| Sim port there | 9000 (`COMPUTE_SIM_PORT`) | 9011 (`COMPUTE_GB10_SIM_PORT`): other accounts can reach its localhost ports |

Choosing a target runs a **session**:

1. The API records it (with the target's backend) and starts a detached session process
   (`python -m api.compute_worker <id>`), which builds its client from that backend.
2. The process starts the instance if it's Brev, starts the sim server if it isn't running (on the GB10 a lock and a
   pid file stop two teammates starting two), and opens the port forward. The panel shows each step. Isaac Sim fails
   about 1 start in 4 on the GB10 (it hangs, or crashes in the graphics driver), so a start that exits, or hasn't logged
   Kit's "Simulation App Startup Complete" within 90 s, is killed and tried again, up to 3 starts.
3. Once the sim answers through the forward, the session is **ready**, and jobs, resumes and test-plan predictions can
   start. Until then they're refused with the reason (409), so nothing runs against a sim that isn't there.
4. It ends as the table says. If the sim server dies while connected, the session starts it again. A Brev instance
   stopped in the console ends the session. A dropped connection (the VPN, a port forward that dies) doesn't: the
   session keeps trying and reopens the forward once the target answers, and running jobs wait for it (see "Simulator
   service").

The session process outlives API restarts like the job workers, and the API restarts it at startup if it's gone. Sessions
are kept as a log of GPU time (`GET /api/compute/sessions`).

**Setup:** each target is prepared once by hand (the runbook, `docs/notes/gpu-test-plan.md`: the repo and `sim_server`
installed into Isaac's Python). Then in the repo-root `.env`:

```bash
SIM_BACKEND=http
SIM_URL=http://127.0.0.1:9000
COMPUTE_BACKENDS=brev,gb10
COMPUTE_BREV_WSL=Ubuntu   # Windows only: the WSL distro the Brev CLI is installed in
```

Brev needs the CLI logged in (`brev login`, SETUP.md) or `COMPUTE_BREV_TOKEN`. The GB10 needs the MSOE VPN and your SSH
key on the team account (SETUP.md); there's no password setting, by team rule. A target that can't be reached (no VPN,
CLI not logged in) shows its error in the panel; the others are still listed. Logs: `DATA_DIR/compute.log`
(sessions), `DATA_DIR/compute_forward.log` (the port forward).

## Frontend

The new UI is a Vite + React + TypeScript app in `frontend/` (setup in [../SETUP.md](../SETUP.md#web-app-app)). It has every
screen in the plan: the experiments list, the new-experiment wizard, the experiment page (progress, then results), the
GPU page, validation, the quick logger, parts and settings ([status](../docs/notes/frontend-plan.md#1-where-the-frontend-stands)). The screens and what each one shows are in
[the frontend plan](../docs/notes/frontend-plan.md); the calls each screen makes are in
[backend-api.md](../docs/notes/backend-api.md).

- `npm run dev` serves both UIs on <http://localhost:5173>, with `/api` forwarded to the backend on :8000 (`API_URL`
  overrides): the old one at `/`, the new one at `/app.html`. Only the new one is built (`npm run build`); the backend
  serves the old `index.html` straight from the folder.
- API calls go through `src/backend/client.ts` ([openapi-fetch](https://openapi-ts.dev/openapi-fetch/)), typed by
  `src/backend/schema.d.ts`. That file is generated and committed: after a backend change, `npm run gen:api` with the
  backend running, then `npm run typecheck` lists every call that no longer matches.
- Routes are hash routes (`#/jobs/...`), so deep links work while the backend serves the build as static files.
- Other packages: TanStack Query (fetching, caching, polling), React Router, three.js (3D previews).
- To switch to the new UI: delete the old `index.html`, rename `app.html` to `index.html` (and its entry in
  `vite.config.ts`), `npm run build`, and point the static mount in `backend/src/api/main.py` at `frontend/dist`.

## How a job runs

The optimizer is `backend/src/api/services/optimizer.py`.

- **Part** (`models/part.py`): a cylinder (standing, or lying across the jaws) or a box, as it rests on the table.
- **Design space** (`models/search_space.py`): six numbers defined relative to the part (pad width, groove angle, groove depth,
  slack, fingertip height, lead-in), mapped from a unit cube so every point is a finger that fits and the jaws can grip with.
- **Geometry** (`models/finger.py`): a design becomes convex pieces in the gripper frame. The sim server, the CAD file and
  the 3D preview all get those same pieces, and quick checks reject anything that can't work before it's simulated.
- **Score** (`models/offset_grid.py`): every design is tried at every point of a fixed grid of camera errors (81 points, more
  for parts whose yaw matters), and scored by its expected success under the job's error model, plus its capture radius.
- **Rounds**: round 0 is the stock and imprint baselines plus a Sobol sample; each later round fits a GP to all scores and
  picks the next batch with BoTorch's qLogNoisyExpectedImprovement. A round is one sim request, checkpointed whole, so a job
  stops after its budget or `patience` rounds without gain, and an interrupted or cancelled job resumes at the next round.
- **Result**: the top 3 and both baselines are re-tested together on a denser grid. The winner's validated score is the
  predicted success; the result page shows the comparison and success at several error levels.
- Each job is a **detached process** (`python -m api.worker <id>`), so closing the browser or restarting the API doesn't kill
  it. Live progress via Server-Sent Events.

## Simulator service

`SIM_URL` points at the sim server in [`../sim/sim_server/`](../sim/README.md), which runs next to Isaac Sim and the
[FANUC ER-4iA twin](../sim/fanuc_er4ia_sim/). The batch contract (`clients/sim.py`):

```text
POST /evaluate_batch
{part: {shape, diameter_mm, length_mm, upright, box_mm: [along, across, height], mass_g},
 designs: [{id: "stock"} | {id, pieces: [{points, triangles}], friction: [static, dynamic], tip_height_mm, jaw_close_mm}],
 offsets: [{dx, dy, yaw_deg}]}                       -> {held: [[bool per offset] per design]}
```

Pieces are in the gripper frame with the jaws closed (mm; see the docstring of `models/finger.py`); the sim mirrors them for
the second finger. The mock (`MockSim`) checks capture geometry only, so **its success rates are not results**.

**Long runs outlive a dropped connection.** Each batch goes with its own `Idempotency-Key` header. If the request or its
answer is lost (the VPN drops, the port forward dies), the client waits for `/health` to answer again, for up to
`SIM_RECONNECT_MINUTES`, and sends the batch again under the same key; the server answers it from the run it already
made, or is still making, instead of running it twice. A round that waits longer fails the job, which resumes after its
last finished round. A server that has never answered (a wrong `SIM_URL`) fails the job at once.

**Clips:** `POST /record_grasp` films one grasp of a final design in Isaac Sim, for the results page
(`services/clips.py` runs a worker per clip and stores the mp4s under the job's outputs). The calls are in
[backend-api.md, "Isaac Sim clips"](../docs/notes/backend-api.md#isaac-sim-clips).

## Database

SQLite at `data/app.db` (relative to `app/`) by default. Tables are in `backend/src/api/db/tables.py`; changes need a
migration (`uv run --package backend alembic -c app/backend/alembic.ini revision --autogenerate -m "..."` from the repo root),
which the API applies at startup. Migration 0002 cleared every job made before it (demo data from the old design space).

## Training data for the stretch goal

`GET /api/export/trials.jsonl`: every simulated design with its parameters, score, capture radius, the raw held/missed result
at every grid point and the grid itself, so a surrogate can be trained for any error level. `GET /api/export/physical.jsonl`:
logged physical trials.

## Not done yet

CAD/image parsing (part size is entered manually; the file is stored), CadQuery export with the mount holes, auth.
