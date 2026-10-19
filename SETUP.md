# Setup

How to get this repo working on your own laptop. [Repo setup](#repo-setup-everyone) is the same for everyone: install
Git, uv (which also installs Python) and VS Code, clone the repo, and check it works. Then [each component](#components)
lists what it needs on top of that. The web app needs nothing more; the simulator and CAD aren't covered yet.

Commands work in PowerShell, Git Bash, or a macOS/Linux terminal unless a section says otherwise. Run the repo commands
from the repo root.

## Repo setup (everyone)

### 1. Install the tools

| Tool | What it's for | Check it's installed |
| --- | --- | --- |
| Git | Version control: cloning, committing, pulling | `git --version` |
| uv | Installs Python and every dependency, and runs the app and tools | `uv --version` |
| Python 3.11+ | Installed through uv, so you don't need the python.org installer | `uv python list --only-installed` |
| VS Code | Recommended editor; the repo suggests its extensions | — |

#### Git

- **Windows:** `winget install --id Git.Git -e --source winget`, or the installer from <https://git-scm.com/download/win>.
  This also installs Git Bash and Git Credential Manager, which signs you in to GitHub the first time you clone or push.
- **macOS:** `xcode-select --install`, or `brew install git`.
- **Linux (Debian/Ubuntu):** `sudo apt install git`.

Then tell Git who you are, once per machine. Use the email on your GitHub account:

```bash
git config --global user.name "Your Name"
git config --global user.email "you@msoe.edu"
```

#### uv

Windows (PowerShell):

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

macOS and Linux:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

`winget install --id=astral-sh.uv -e` and `brew install uv` work too. Close and reopen your terminal afterwards, then check
with `uv --version`.

#### Python

```bash
uv python install 3.12
```

The project needs Python 3.11 or newer, and the team uses 3.12. uv keeps its own Python, separate from any system install
(and downloads it automatically on your first sync if you skip this step). Don't `pip install` anything into a global
Python: uv manages every dependency.

#### VS Code (recommended)

- **Windows:** `winget install -e --id Microsoft.VisualStudioCode`
- **macOS:** `brew install --cask visual-studio-code`
- Or download it from <https://code.visualstudio.com>.

When you open the repo folder, VS Code offers the recommended extensions (Python, Ruff, EditorConfig, markdownlint);
install them. After step 3, point VS Code at the project's Python: `Ctrl+Shift+P` → **Python: Select Interpreter** → the
`.venv` at the repo root.

### 2. Get the repo

You need access to the team's GitHub repo; accept the invite from the
[team workspace](https://dashboard.all-ai-network.org/j/L36HEH). Then:

```bash
git clone https://github.com/ALL-Applied-AI-Network/msoe-ai-club-rockwell-automation-nvidia-hackath-alec-weinbender-s-team-a715330bad.git
cd msoe-ai-club-rockwell-automation-nvidia-hackath-alec-weinbender-s-team-a715330bad
```

On Windows, clone into a short path outside OneDrive (for example `C:\Users\you\Projects`). OneDrive syncing can lock
files inside `.venv`.

### 3. One-time setup

```bash
git config core.hooksPath .githooks   # turns on the pre-commit guard: blocks files over 5 MB, .env files, keys, model weights
uv sync --all-packages                # creates .venv at the repo root with every component's dependencies and the dev tools
```

The repo is a uv workspace: each component (`app/backend`, `sim/sim_server`) has its own `pyproject.toml`, and they share
one lockfile (`uv.lock`) and one `.venv` at the root.

### 4. Check that everything works

```bash
uv run pytest                  # tests; offline, a few seconds
uv run ruff check .            # lint
uv run ruff format --check .   # formatting
```

All three should pass on a fresh clone. If they do, your repo setup is done.

### Day to day

- After `git pull`, run `uv sync --all-packages` to pick up dependency changes. It's quick when nothing changed.
- Before committing: `uv run ruff format .`, `uv run ruff check .`, `uv run pytest`.
- To add a dependency to a component: `uv add --package backend <package>` (or `--package sim-server`). Commit the changed
  `pyproject.toml` and `uv.lock` together.
- Coding conventions (project layout, backend layers, database, tests) are in
  [.claude/rules/coding-style.md](.claude/rules/coding-style.md). Project context: [CONTEXT.md](CONTEXT.md). Instructions
  for coding agents: [AGENTS.md](AGENTS.md).

## Components

### Web app (`app/`)

Nothing beyond the repo setup. The app runs on a mock LLM and a mock simulator, so it doesn't need the digital twin, a
GPU or real CAD output.

```bash
uv run --package backend uvicorn api.main:app --port 8000
```

Open <http://localhost:8000>. The log shows which backends are active; warnings about the mock LLM and mock simulator are
expected. The first start creates the database at `app/data/app.db`. Stop the server with `Ctrl+C`.

The mock simulator's success rates are made up: never report them as results.

To use real backends (Claude for the LLM step, the sim server for grasps), copy the template and fill in what you need:

```bash
cp .env.example .env
```

The app reads `.env` at startup and tells you if a backend you selected is missing a setting. `.env` is gitignored, and
the pre-commit guard blocks it too: never commit keys. More on the app: [app/README.md](app/README.md).

### Simulator (`sim/`): not covered yet

The digital twin (Isaac Sim + Cosmos) runs on Brev or the MSOE GB10, not on laptops. Until this guide covers it, see
[sim/README.md](sim/README.md) and [sim/fanuc_er4ia_sim/SETUP.md](sim/fanuc_er4ia_sim/SETUP.md).

### CAD: not covered yet

Real CAD output (e.g. CadQuery → STEP/STL) isn't implemented. The app writes placeholder OpenSCAD files and needs no CAD
software.

## Troubleshooting

| Problem | Fix |
| --- | --- |
| `uv` or `git` isn't found after installing | Close and reopen the terminal (and VS Code) so it picks up the new `PATH`. |
| PowerShell won't run the uv installer | Use the exact command above. `-ExecutionPolicy ByPass` applies to that one command only. |
| The app stops at startup with "config problem(s)" | A backend you selected is missing a setting. The log names the variable: set it in `.env` (see `.env.example`), or unset the backend to use the mock. |
| Port 8000 is already in use | Run with `--port 8001`, or stop the other server. |
| Git asks for a password | Sign in through the Git Credential Manager browser window. GitHub doesn't accept account passwords over HTTPS. |
| A commit is blocked by the pre-commit guard | It says why: a file over 5 MB, an `.env` file, model weights, or something that looks like a key. Take that file out of the commit. |
