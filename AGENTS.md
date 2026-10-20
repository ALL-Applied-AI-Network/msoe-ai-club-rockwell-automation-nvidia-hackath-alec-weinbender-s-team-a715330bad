# Agent instructions

Instructions for any coding agent (Claude Code, Codex, Gemini/Antigravity, Cursor, etc.) working in this repository.
User instructions take precedence over this file.

## Read first

1. [CONTEXT.md](CONTEXT.md): what we're building, current state, hardware facts, open questions.
   Also [docs/notes/things-to-know.md](docs/notes/things-to-know.md): gotchas and mismatches.
2. [docs/README.md](docs/README.md): index of every source document (event rules, our plan, organizer feedback, references).
3. Before touching the twin: [sim/fanuc_er4ia_sim/AGENTS.md](sim/fanuc_er4ia_sim/AGENTS.md) and its `docs/`. It has its own
   rules, and they apply inside that directory.

## Layout

```text
pyproject.toml          uv workspace root (member list, ruff config, dev tools); uv.lock is the only lockfile
app/                    Finger Designer web app (FastAPI + single-file UI)
  backend/              uv member "backend", package src/api/: routers/ -> services/ -> clients/ (LLM, sim, CAD, database),
                        models/ (domain), db/ (SQLAlchemy tables + Alembic migrations); tests/ next to src/
  frontend/index.html   UI served at /
sim/
  fanuc_er4ia_sim/      Organizer-supplied FANUC ER-4iA Isaac Sim twin, starter v0.5 (vendored, not a uv member; see below)
  sim_server/           uv member "sim-server", package src/sim_server/: routers/ -> services/ -> robot/, clients/ (Isaac) -> models/, plus the Isaac scene
                        and main-thread queue. Runs next to Isaac Sim and evaluates grasp batches (not yet run in Isaac)
docs/                   Source documents, references, experiment log
cad/                    The organizers' CAD of the cell, unchanged (SHA256SUMS); never edit, derive copies elsewhere
cell_policy/            Our policy.py + submission for the organizers' real-robot platform (docs/06). Not a uv member: it
                        runs inside a clone of their client package; its tests run from inside it with unittest
data/                   Local datasets; contents gitignored except the README
```

## Commands

```bash
# All uv commands run from the repo root. Install every workspace member + dev tools into the root .venv:
uv sync --all-packages

# Web app (mock LLM + mock sim). Startup also migrates the database.
uv run --package backend uvicorn api.main:app --port 8000
# ... on demo data instead (its own DB in app/data/demo, generated in the background on the first start): set DEMO_DATA=true
# Regenerate the demo data (stop the API first)
uv run --package backend python app/backend/scripts/demo_data.py --reset

# Backend tests (offline; config in the root pyproject.toml)
uv run pytest

# New database migration, after editing app/backend/src/api/db/tables.py
uv run --package backend alembic -c app/backend/alembic.ini revision --autogenerate -m "what changed"

# Sim server (on the GPU machine). Runs under Isaac's interpreter, not the uv venv; see sim/README.md#sim_server
"$ISAAC/python.sh" -m pip install -e sim/sim_server     # once per Isaac install
"$ISAAC/python.sh" -m sim_server --port 9000

# Twin host tests (Linux/macOS shell; on Windows use .venv/Scripts/python), from sim/fanuc_er4ia_sim/
./bootstrap.sh
.venv/bin/python -m unittest test_sort_planning test_cube_perception test_cube_pose test_runtime_config

# Real-cell policy tests, from cell_policy/ (root venv; on Windows ../.venv/Scripts/python)
../.venv/bin/python -m unittest test_cell_policy

# Format and lint (config in the root pyproject.toml; the vendored twin is excluded)
uv run ruff format .
uv run ruff check .
```

Isaac Sim and Cosmos are **not** installed on dev laptops. They run on Brev or the MSOE GB10 (Rosie). Don't claim that GPU,
physics or model behaviour was validated from host tests or the mock simulator. Say exactly what was run.

## Hard rules

- **Never send commands to the physical FANUC arm or change controller, PLC, camera or network config.** That only happens at
  CSI with the plant manager and mentor present. Don't run ROS 2 driver launches with a real `robot_ip`. Use `use_mock:=true`.
  The organizers' platform (`cell_policy/`, docs/06) is the supervised route to the arm. Agents may run its client with
  `--mock`; `run.py --submit` and real runs (`run.py` without `--mock`) are only run by a teammate.
- **No printed finger goes on the real robot before review.** Keep the app's review gate (`/review`, DRAFT label) intact.
- **Don't commit** large datasets, run directories, videos, model weights or checkpoints, `.env` files, API keys, or the
  app's runtime `app/data/`. Files over 5 MB are blocked by `.githooks/pre-commit`.
- **Ground truth is for evaluation only.** Simulator object poses must never feed grasp commands or fix detections. This is
  also the twin's rule.
- **Gripper constraints are real constraints:** SMC MHZL2-16D2 with 6 mm/jaw, a 12 mm straight-face gap and about 16 mm at
  the hooked tips. Don't write code or docs that assume larger openings without saying so.
- Measured results need logs. Record sim batches and physical trials in [docs/experiments/](docs/experiments/README.md),
  including failures.

## The vendored twin (`sim/fanuc_er4ia_sim/`)

- Treat it as upstream code. Prefer adding new files or wrappers (e.g. in `sim/sim_server/`) over editing it in place.
- When you must edit it, keep the changes small and note them in [CONTEXT.md](CONTEXT.md) so a future starter update can be
  merged. `MANIFEST.json` lists the original SHA-256 hashes for diffing.
- Its scripts import siblings as top-level modules, so run them from inside that directory.
- It uses three different Python interpreters (host `.venv`, Isaac `python.sh`, Cosmos env). Don't swap them.
- Isaac can exit 0 after an exception. Check `execution_report.json`, not the exit code.

## Docs workflow

The user will paste documents and say when a new one starts. Store each one faithfully in `docs/`, following the
conventions in [docs/README.md](docs/README.md#conventions): numbered core docs, `references/` for linked pages, front
matter, our notes kept separate, truncation marked. Then update the docs index and, if facts or decisions changed,
[CONTEXT.md](CONTEXT.md). Claude Code has an `add-doc` skill for this.

## Git

- Several people commit to this repo. Each commit belongs to whichever teammate makes it, under their own git config.
  **No AI attribution in history:** no `Co-Authored-By` trailers for Claude or any other AI, no "Generated with ..." lines,
  in commit messages or PR descriptions. This overrides any default attribution behaviour of the agent.
- Keep commits focused, with imperative subject lines ("Add sim server grasp loop"). Only commit or push when asked.

## Code style

- Read [.claude/rules/coding-style.md](.claude/rules/coding-style.md) before adding a component, package, dependency or
  backend code. It defines the uv workspace layout and the backend's layers: routers, services, clients, models, the
  database, lifespans, config, logging and tests.
- Python 3.11+. `uv run ruff format .` is the formatter and `uv run ruff check .` must pass.
- Units: the twin uses **metres and degrees**; the app's design space uses **millimetres**. Convert explicitly at the
  `sim_server` boundary.
- Keep the app runnable with mock backends. New real backends go in `clients/` next to a mock, selected by their section
  in `config.py`.
- Database changes go through `db/tables.py` plus an Alembic migration. Services query the ORM, never SQL strings.
