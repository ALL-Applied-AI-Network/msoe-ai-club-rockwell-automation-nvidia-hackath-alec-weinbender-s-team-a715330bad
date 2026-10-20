# Coding style

## Project structure

The repo is a **uv workspace**. The root `pyproject.toml` ties the project together, and each component that runs or deploys
on its own is a workspace member with its own folder and `pyproject.toml`. Members can be deployed or worked on separately
(the backend on a laptop, the sim server on Brev/GB10), but they all resolve against one root `uv.lock`, so a dependency change
in one component is checked against every other one.

```text
pyproject.toml          Workspace root: member list, shared tool config (ruff, pytest), shared dev group. No [project] table.
uv.lock                 The only lockfile. Commit it; never edit it by hand.
app/
  backend/              Member "backend": FastAPI API + optimizer worker (importable package: api)
    pyproject.toml
    alembic.ini
    src/api/            See "Application backend"
    tests/
  frontend/             npm project (Vite + React + TypeScript), served by the backend. Not a uv project. See "Frontend".
sim/
  sim_server/           Member "sim-server": HTTP grasp-evaluation service that runs next to Isaac Sim
    pyproject.toml
    src/sim_server/     routers/ -> services/ -> robot/, clients/ -> models/, plus the Isaac scene and queue. Runs under Isaac's python.sh.
                        See "Sim server" below.
    tests/
  fanuc_er4ia_sim/      Vendored twin. Not a member; keeps its own requirements.txt and interpreters.
```

### Rules

- **One component, one member.** Anything new that runs or deploys on its own (a service, a worker, a CLI) gets its own
  folder with its own `pyproject.toml` and `src/<package>/` layout. Don't grow an existing member to host an unrelated
  service. Create it from the repo root with `uv init --package <path>`, which also adds it to `[tool.uv.workspace] members`.
- **Python 3.11+ everywhere.** Set `requires-python = ">=3.11"` in every member to match ruff's `target-version`.
  `uv init` fills in your local interpreter's version instead, so fix it after generating.
- **Dependencies belong to the member that uses them.** Add them with `uv add --package <member> <dep>`, never to the root.
  The root only holds the shared `dev` group (ruff, pytest, httpx), added with `uv add --dev <tool>` from the root.
- **Declare cross-member imports.** If one member imports another, add it as a dependency (`uv add --package sim-server
  backend` writes the `[tool.uv.sources]` workspace entry for you). All members share the root `.venv`, so an undeclared
  import works locally after `uv sync --all-packages` and then breaks in a deploy that syncs only one package. Never reach
  into another member by relative path or `sys.path` edits.
- **Tool config lives at the root.** `[tool.ruff]`, `[tool.pytest.ini_options]` and similar sections go only in the root
  `pyproject.toml`, so every member is linted and tested the same way.
- **Vendored code stays out.** Don't add a `pyproject.toml` to `sim/fanuc_er4ia_sim/` or make it a member. The same goes for
  anything that has to run under Isaac's `python.sh` or the Cosmos env.

### Commands (from the repo root)

```bash
uv sync --all-packages                           # local dev: every member + dev tools in one root .venv
uv sync --package backend                        # just one member (+ dev tools)
uv run --package backend uvicorn api.main:app --port 8000
uv add --package backend "fastapi>=0.115"        # add a dependency to one member
uv add --dev pytest                              # add a shared dev tool to the root
uv lock                                          # after hand-editing any pyproject.toml; commit uv.lock

# Deploying one member somewhere else
uv sync --frozen --no-dev --package sim-server
uv export --frozen --no-dev --package sim-server > requirements.txt   # pinned list for a Docker image
```

Code that needs files outside its package (the backend serves `app/frontend/` and writes `app/data/`) finds them relative
to `__file__`, so it relies on the default editable install from `uv sync`. A non-editable install (`--no-editable`) needs
those paths passed in by env var, as `DATA_DIR` already is.

## Application backend

The backend is split into layers so the real work can be tested without going through HTTP.

```text
app/backend/
  pyproject.toml
  alembic.ini            Alembic CLI config; points at api/db/migrations
  src/api/
    main.py              Builds the FastAPI app: lifespan (logging, config check, database), routers, static UI
    worker.py            Entrypoint for the detached job process: builds the clients, runs the optimizer
    config.py            Settings, secrets and setup_logging(). The only module that reads environment variables.
    dependencies.py      FastAPI dependencies that hand routers what the lifespan created (config, database)
    routers/             HTTP layer, one file per object, each with its own request/response schemas
      health.py  meta.py  jobs.py  export.py
    services/            Business logic. Never imports FastAPI.
      jobs.py  reviews.py  physical_trials.py  export.py  optimizer.py
    clients/             External systems. Each builds itself from its own config section.
      llm.py  sim.py  cad.py  database.py
    db/                  What's stored: the SQLAlchemy tables and their Alembic migrations
      tables.py  migrations/
    models/              Domain objects (pydantic) shared by services, clients, tables and router schemas
      job.py  part.py  design.py  review.py  physical_trial.py
  tests/                 Next to src/, not inside it (see Testing); mirrors src/api
    conftest.py  test_config.py  routers/  services/  clients/  db/
```

### Naming

- **Name routers and services after the main object or service they work with.** `routers/jobs.py` serves `/api/jobs`,
  and `services/jobs.py` holds the job logic behind it. Clients are named after the system they talk to (`llm.py`,
  `sim.py`, `database.py`). Model files are singular and named after the object they define (`models/job.py` defines
  `Job`). Table classes are the object plus `Row` (`JobRow`).
- Don't name files after a layer or a verb (`utils.py`, `helpers.py`, `handlers.py`, `manager.py`, `do_optimize.py`). If
  a function doesn't fit an existing object, that object probably needs its own file. `dependencies.py` is the one
  exception: it's FastAPI's convention.
- `health.py` (always present: `GET /health`) and `meta.py` are operational routers with no matching service.

### Layers

Dependencies point one way: **routers → services → clients**, and services use `db/tables.py` for their queries. Models can
be used by every layer and import none of them.

- **Routers** are thin. A route validates the request, calls one service function, and turns the result into its response
  schema. Routers contain no queries, no client calls and no business rules. They translate service exceptions into
  `HTTPException`.
- **Services** are plain Python that never imports `fastapi`. They take their clients (including the database client) as
  arguments rather than building them, and raise domain exceptions defined next to the service
  (`class JobNotFoundError(LookupError)` in `services/jobs.py`) instead of HTTP errors.
- **Clients** wrap one external system each. Every external system gets a module in `clients/`: LLMs, the sim server, CAD
  export, the database, any future API. This holds even when only a mock exists so far. Services never call an outside
  system directly. Each client module has a `create_<name>_client(config.<section>)` factory. Clients with mock and real
  backends expose a single interface (a `Protocol`), and the config decides which one is built; the mock is the default,
  so the app and the tests run offline. The database client has one implementation; tests use a temporary SQLite file.
- **Models** are pydantic `BaseModel` domain objects (`Job`, `Part`, `Design`, the design space). They carry no HTTP or
  storage concerns: no request-only fields, no status codes, no storage-only columns.

### Request and response schemas

- Each route's request and response schemas are pydantic models defined **in the router file that uses them**, named after
  the action and object: `CreateJobRequest`, `JobResponse`, `JobDetailResponse`.
- Schemas may embed or extend models (`class JobResponse(Job)`) but are never imported by services or by other routers.
- If two routers need the same shape, it's a domain object: move it to `models/`.
- Form posts use one form model per route (`Annotated[ReviewRequest, Form()]`). A file upload goes inside that model as an
  `UploadFile` field, since FastAPI can't combine a form model with a separate `File()` parameter.

### Database

- **The client connects; the `db` package describes what's stored.** `clients/database.py` builds the engine and sessions
  from `DbConfig`, handles SQLite specifics (WAL, the file's folder) or Postgres pooling, and runs migrations. Moving to
  Postgres means changing `DB_URL`, not code. `db/tables.py` holds the SQLAlchemy table classes; `db/migrations/` holds
  the Alembic migrations.
- **Services query the ORM, never SQL strings.** Each unit of work is its own short block, `with db.session() as s:`,
  which commits at the end. Keep sessions short and don't hold one across a slow call (an LLM request, a process pool):
  the detached workers and the UI's live progress depend on seeing each other's commits.
- **Tables mirror models; don't merge them.** Rows also hold storage-only columns (`pid`, `raw_response`), and one model
  can span several tables, so they stay separate classes. What can drift is shared instead: `tables.py` imports value
  types from `models/` (`Part` and `JobConfig` are stored as typed JSON through `PydanticJSON`, and the status `Literal`s
  are column types), and services convert rows with `Job.model_validate(row)` (models set `from_attributes=True`).
  `tests/db/test_tables.py` checks every model field against its table, including nullability.
- **Every table change ships with a migration.** Edit `tables.py`, then generate and review the migration:
  `uv run --package backend alembic -c app/backend/alembic.ini revision --autogenerate -m "what changed"`. A test fails if
  `tables.py` and the migrations disagree. The API runs `alembic upgrade head` at startup unless `DB_AUTO_MIGRATE=false`,
  which is meant for deploys that run migrations as their own step. Migrations use batch mode, because SQLite can't
  `ALTER` most columns.
- Databases created before Alembic are stamped as revision `0001` on first startup instead of being recreated, so their
  data is kept.

### Lifespans: where long-lived resources go

Anything with a startup and shutdown (a database engine, an SDK client with a connection pool, a loaded model) is created
by the **entrypoint that uses it**, which also closes it:

- **The API** creates its resources in `main.py`'s `lifespan`, stores them on `app.state`, and closes them after the
  `yield`. Routers reach them only through `dependencies.py` (`DbDep`, `ConfigDep`), so tests can swap them.
- **A job** runs in its own detached process. `worker.py` builds the LLM, sim, CAD and database clients in a
  `with closing(...)` block around the optimizer, so they live exactly as long as the job. That's where the sim client
  lives: the API never calls the sim.
- **The heavy Isaac Sim scene** belongs to the sim server, a separate member. It loads in that server's entrypoint
  (`__main__.py`), on the main thread, before serving and never at import. Isaac must only be called from that thread:
  route handlers submit work to `SimQueue` and await it, and never touch the scene directly.
- Clients sent to the optimizer's process pool are pickled, so they hold plain attributes only (a URL, a timeout), never an
  open connection.

### Config and secrets

- `config.py` has **one pydantic model per client** (`LlmConfig`, `SimConfig`, `DbConfig`) and one pydantic-settings
  `AppConfig` that combines them with the app-wide settings (`DATA_DIR`, `LOG_LEVEL`). Each section reads its own prefix:
  `LLM_BACKEND` sets `llm.backend` and `DB_URL` sets `db.url`. `ANTHROPIC_API_KEY` keeps its standard name and is copied
  into the LLM section.
- Values come from real environment variables first, then the repo-root `.env`. No other module reads `os.environ`.
- Secrets (API keys, database URLs with passwords) are `SecretStr`, so they never show up in logs, reprs or tracebacks.
  Log whether a secret is set, never its value.
- `load_config()` loads and checks the config once per process. Both entrypoints call it before doing any work:
  - If a real backend is selected but its key or URL is missing (`LLM_BACKEND=anthropic` without `ANTHROPIC_API_KEY`), log
    an error that names the variable, says what it's for and points to `.env.example`, then refuse to start.
  - If no backend is selected, use the mock and log a warning that says how to switch to the real one.
  - Collect every problem and report them together, so you don't have to fix and restart one variable at a time.
- Routers get the config through `ConfigDep`; tests build `AppConfig(...)` directly.
- Every new variable goes in its section of `config.py` and in `.env.example` with a one-line comment.

### Logging

- Use the standard `logging` module. Each module declares `logger = logging.getLogger(__name__)`. No `print()`.
- `config.setup_logging()` sets the format and level (`LOG_LEVEL`, default `INFO`). Each entrypoint calls it first, before
  loading the config, so config errors are logged too, and again with the configured level. Modules never configure
  handlers themselves.
- Levels: `DEBUG` for detail, `INFO` for lifecycle events (backend selected, job started or finished), `WARNING` when
  falling back or degraded (mock in use, retrying), `ERROR` when someone has to act.
- Pass values as arguments (`logger.info("job %s done", job_id)`), not f-strings; ruff's `G` rules enforce it. In `except`
  blocks use `logger.exception` to keep the traceback.

### Ruff

- `uv run ruff format .` is the only formatter, and its output is final; don't hand-format around it. `uv run ruff check .`
  must pass too. Run both before committing.
- Config lives only in the root `pyproject.toml`. A `# noqa` needs a short comment explaining why.

### Testing

- Backend tests use pytest and live in `app/backend/tests/`, **next to `src/`, not inside it.** `src/` holds what gets
  installed and deployed, so tests stay out of the package and import `api` the same way the running app does.
- Test files mirror the package: `tests/services/test_jobs.py` tests `services/jobs.py`, and `tests/routers/test_jobs.py`
  tests `routers/jobs.py`. Shared fixtures go in `tests/conftest.py`. Tests never read the developer's `.env` or exported
  app variables; `conftest.py` blocks both.
- **Service tests** call service functions directly, with mock clients and a temporary SQLite database built by the real
  migrations. No HTTP is involved.
- **Router tests** use FastAPI's `TestClient` with `get_config` and `get_db` overridden (`app.dependency_overrides`) to
  that temporary config and database. Anything that would start a process or call out is monkeypatched (`spawn_worker`).
  They check status codes, validation and response shape, not business logic.
- Tests run offline. Anything that needs a real LLM or the sim is marked `@pytest.mark.integration` and skipped by default.
- Run them with `uv run pytest` from the repo root. The vendored twin keeps its own `unittest` suite.

## Frontend

`app/frontend/` is an npm project (Vite, React, TypeScript), not a uv member. Setup and commands are in
[SETUP.md](../../SETUP.md#web-app-app); how it fits the app is in [app/README.md](../../app/README.md#frontend).

```text
app/frontend/
  package.json           Dependencies, pinned to exact versions. Commit it together with package-lock.json.
  vite.config.ts         Dev server (:5173, forwards /api to the backend) and the build
  index.html             The old single-file UI, served until the new one replaces it. New pages go in src/, not here.
  app.html               Entry page of the new UI
  src/
    main.tsx             Providers and routes
    backend/             client.ts (the typed API client) and schema.d.ts (generated by `npm run gen:api`; never edited)
    styles/              tokens.css (colors, fonts, radii, spacing, shadows, light and dark) and base.css (element defaults)
    components/          Shared building blocks: page shell, buttons, cards, form fields, tables, badges, icons, 3D viewer
    pages/               One folder per page or wizard step, put together from components/
    format.ts            The one place numbers become text: percentages, mm, degrees, grams
```

`components/`, `pages/` and `format.ts` don't exist yet; whoever needs one first creates it there.

### Design

- **Reuse components before writing new ones.** Look in `src/components/` first. If something there is close, give it a
  prop instead of copying it. If a page needs a pattern another page already has, move it into `components/` and use it
  from both. Pages put components together and hold page state; they never style their own buttons, inputs, cards,
  tables or badges.
- **One look across every page.** Colors, fonts, radii, spacing and shadows come only from the variables in
  `styles/tokens.css`: no hex values, font names or one-off sizes inside components. Every page sits in the same page
  shell (header, sim badge, content width), every wizard step uses the same step layout, and the same thing always looks
  the same: a job status is always the same badge, a success rate always goes through `format.ts`.
- **The palette is the old UI's:** NVIDIA green (`--acc`) for actions and progress, Rockwell red (`--brand`) for the
  header line, with light and dark themes. Check a change in both themes before calling it done.
- **Component styles live next to the component** as a CSS module (`Button.tsx` with `Button.module.css`) and use only
  the tokens. Inline `style={...}` is only for values computed at runtime, like a progress bar's width.
- **No emojis** anywhere in the UI or the frontend code: labels, buttons, messages, placeholders, alt text, comments.
- **No arrows or other symbols in place of words or icons** (→, ←, ↓, ✓, ✕, •). Write the words: "Download trials",
  "Close", "Next step". When a control really needs an icon, it comes from the shared `Icon` component (inline SVG), so
  every icon is drawn the same way.
- **Plain, sentence-case text** that says what happens: "Start optimization", not "Let's go!". Every number shows its
  unit. Results from the mock sim always carry the sim badge: they are never predictions.

### Code

- API types come from `src/backend/schema.d.ts` (`Schemas["PartResponse"]`). Never hand-write a type the backend already
  defines. After a backend change: `npm run gen:api` with the backend running, then `npm run typecheck`.
- Server data goes through TanStack Query (`useQuery`, `useMutation`) and the `api` client, not `useEffect` with `fetch`.
- Routes are hash routes (`#/jobs/...`), so deep links work while the backend serves the build as static files.
- `npm run build` (type check, then build) must pass before committing frontend changes.

## Sim server

`sim/sim_server/` has the backend's layering, scaled to one service with one external system (Isaac Sim). The import
package stays `sim_server`, not `api`: every workspace member installs into the same root `.venv`, so two top-level `api`
packages would shadow each other.

```text
sim/sim_server/
  pyproject.toml
  scripts/               send_batch.py and example batches: test a running server without the app
  src/sim_server/
    __main__.py          Entrypoint: starts Isaac on the main thread, uvicorn in a thread, then serves the queue
    app.py               Builds the FastAPI app: routers, with the scene and queue stored on app.state
    dependencies.py      FastAPI dependencies that hand routers the scene and queue (so tests can swap them)
    routers/             Thin HTTP layer; request/response schemas (mm, g, deg) live in the router file that uses them
      health.py  evaluations.py
    services/            The work the routers queue. Isaac-free, never imports FastAPI.
      evaluations.py     A batch -> held rows, against a small Protocol for the Isaac client (handed in, never imported)
      batches.py         Request units -> models, the grasp each design commands, packing grasps into environments
    robot/               The arm and gripper, Isaac-free: motion.py (the top-down grasp, planned with the twin's IK;
                         another grasp type would be a sibling module), gripper_frame.py, poses.py
    clients/             The external system: isaac.py (the stage, the environment copies, running a chunk of grasps)
                         and env_grid.py (their Isaac-free layout)
    models/              Pydantic domain objects in the twin's units (m, kg, deg), frozen, one file per object
      part.py  finger.py  offset.py  batch.py  grasp.py  pose.py  gripper.py
    scene.py             Isaac's lifecycle: SimulationApp + the grasp cell, loaded once, kept between requests
    sim_queue.py         Runs every Isaac call on the main thread, one at a time
    twin.py              Makes the vendored twin's modules importable without editing it
  tests/                 Mirrors the package: routers/, services/, robot/, clients/, models/, scripts/. Runs without
                         Isaac. test_layers.py enforces the rules below from each module's imports.
```

- **Dependencies point one way:** routers -> services -> robot / clients -> models, as in the backend. Services get the
  Isaac client handed in through a Protocol and never import it; clients never import services; models import no other
  layer.
- **Only `clients/isaac.py` and `scene.py` touch Isaac** (`isaacsim`, `omni`, `pxr`), and only after `SimulationApp` has started.
  Everything else imports, and is tested, on a laptop without Isaac; the twin's pure-Python modules (`scene_config`, `ik`,
  `fk`) are fine through `twin.use_twin()`.
- **Isaac runs on the main thread only.** Route handlers convert the request, submit the work to `SimQueue` and await it;
  they never call the scene or the cell directly.
- **Units convert once, at the boundary.** Requests are in mm, g and degrees; `services/batches.py` converts them to metres and
  kilograms, and nothing past it sees millimetres.
- Code that can't be checked without a GPU says so in its docstring, and [docs/notes/gpu-test-plan.md](../../docs/notes/gpu-test-plan.md)
  is how it gets validated. Don't claim Isaac behaviour from host tests.
