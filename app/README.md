# Finger Designer (web app)

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
| `DATA_DIR` | Where the SQLite DB, uploads and outputs go (default `app/data/`) |
| `DB_URL` | Another database instead of the SQLite file, e.g. Postgres |
| `ANTHROPIC_API_KEY`, `LLM_*` | The LLM client. The optimizer doesn't call it at the moment |

If a selected backend is missing its key or URL, the API logs which variable and refuses to start.

## Frontend

The new UI is a Vite + React + TypeScript app in `frontend/` (setup in [../SETUP.md](../SETUP.md#web-app-app)). It's only
an entry point so far; the wizard and results pages are built against the API contract in section 7 of
[the input-flow plan](../docs/notes/input-flow-backend-plan.md).

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
