# Setup

How to get this repo working on your own laptop. [Repo setup](#repo-setup-everyone) is the same for everyone: install
Git, uv (which also installs Python), Node.js and VS Code, clone the repo, and check it works. Then
[each component](#components) lists what it needs on top of that, including the
[GPU machines](#gpu-machines-brev-and-the-msoe-gb10) the simulator runs on. CAD isn't covered yet.

Commands work in PowerShell, Git Bash, or a macOS/Linux terminal unless a section says otherwise. Run the repo commands
from the repo root.

## Repo setup (everyone)

### 1. Install the tools

| Tool | What it's for | Check it's installed |
| --- | --- | --- |
| Git | Version control: cloning, committing, pulling | `git --version` |
| uv | Installs Python and every dependency, and runs the app and tools | `uv --version` |
| Python 3.11+ | Installed through uv, so you don't need the python.org installer | `uv python list --only-installed` |
| Node.js 22+ (with npm) | Builds and runs the web app's frontend (`app/frontend/`); npm comes with it | `node --version`, `npm --version` |
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

#### Node.js and npm

npm is installed with Node.js. Install the current LTS release (22 or newer):

- **Windows:** `winget install -e --id OpenJS.NodeJS.LTS`, or the LTS installer from <https://nodejs.org>.
- **macOS:** `brew install node`, or the LTS installer from <https://nodejs.org>.
- **Linux (Debian/Ubuntu):** the distro's `nodejs` package is usually too old. Use [nvm](https://github.com/nvm-sh/nvm):
  `nvm install --lts`.

Close and reopen your terminal, then check with `node --version` and `npm --version`. Don't install the frontend's
packages globally (`npm install -g`): each project keeps its own in `node_modules/`.

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
npm ci --prefix app/frontend          # installs the frontend's packages into app/frontend/node_modules, exactly as locked
```

The repo is a uv workspace: each component (`app/backend`, `sim/sim_server`) has its own `pyproject.toml`, and they share
one lockfile (`uv.lock`) and one `.venv` at the root. The frontend is an npm project with its own lockfile
(`app/frontend/package-lock.json`).

### 4. Check that everything works

```bash
uv run pytest                  # tests; offline, a few seconds
uv run ruff check .            # lint
uv run ruff format --check .   # formatting
npm run build --prefix app/frontend   # type-checks and builds the frontend into app/frontend/dist/
```

All four should pass on a fresh clone. If they do, your repo setup is done.

### Day to day

- After `git pull`, run `uv sync --all-packages` and `npm ci --prefix app/frontend` to pick up dependency changes. Both are
  quick when nothing changed.
- Before committing: `uv run ruff format .`, `uv run ruff check .`, `uv run pytest`, and if you touched the frontend,
  `npm run build --prefix app/frontend`.
- To add a dependency to a component: `uv add --package backend <package>` (or `--package sim-server`). Commit the changed
  `pyproject.toml` and `uv.lock` together.
- To add a frontend dependency: `npm install --save-exact <package>` (or `--save-dev` for build tools) inside
  `app/frontend/`. Commit `package.json` and `package-lock.json` together.
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

To work on the frontend, keep the backend running and start Vite's dev server in a second terminal:

```bash
cd app/frontend
npm run dev        # serves the UI on http://localhost:5173 and reloads as you edit; API calls go to the backend on :8000
```

Open <http://localhost:5173/>. To have the backend serve the UI itself (at <http://localhost:8000/>), build it once with
`npm run build`.

After a backend change, regenerate the API types and check the frontend still matches:

```bash
npm run gen:api    # regenerates src/backend/schema.d.ts from the running backend's OpenAPI schema
npm run typecheck  # shows every frontend call that no longer matches the API
```

If the backend runs on another port, start the dev server with `API_URL` set, e.g. `API_URL=http://localhost:8001 npm run
dev` in Git Bash, or `$env:API_URL="http://localhost:8001"; npm run dev` in PowerShell.

The mock simulator's success rates are made up: never report them as results. To run jobs on the real twin instead,
connect a GPU from the app: [GPU from the web app](#gpu-from-the-web-app).

To use real backends (Claude for the LLM step, the sim server for grasps), copy the template and fill in what you need:

```bash
cp .env.example .env
```

The app reads `.env` at startup and tells you if a backend you selected is missing a setting. `.env` is gitignored, and
the pre-commit guard blocks it too: never commit keys. More on the app: [app/README.md](app/README.md).

### GPU machines (Brev and the MSOE GB10)

The digital twin (Isaac Sim) and our sim server run on a GPU machine, not on laptops. We have two: a **Brev** cloud
instance (the team's $500 of credits) and the **MSOE GB10** (free, shared with other teams, reached over the MSOE VPN).
Set up what you need for the machine you'll use:

| Tool | Needed for | Check it's set up |
| --- | --- | --- |
| Brev account in the team | Brev | You can see the team (UWM/MSOE-Team-40) at <https://brev.nvidia.com> |
| WSL with Ubuntu (Windows only) | Running the Brev CLI | `wsl -l -v` in PowerShell lists an Ubuntu with VERSION 2 |
| Brev CLI | The web app's Brev target, and `brev shell`, `brev copy`, `brev port-forward` by hand | `brev ls` in the Ubuntu terminal lists the team's instances |
| MSOE VPN (GlobalProtect) | Reaching the GB10 | `ssh hackathon11@spark1.ai.msoe.edu` connects |
| Your SSH key on the GB10 | Logging in without the shared password | `ssh -o BatchMode=yes hackathon11@spark1.ai.msoe.edu true` returns without a prompt |

What to run once you're on a machine, step by step: the [GPU test plan](docs/notes/gpu-test-plan.md). Background:
[sim/README.md](sim/README.md) and [sim/fanuc_er4ia_sim/SETUP.md](sim/fanuc_er4ia_sim/SETUP.md).

#### Brev account

Alec (the team captain) generates an invite link in Brev under **Team**. Open it, sign in or create an account, and
join the team. The credits are shared by everyone: **Billing** shows what's left, and an instance bills for every hour
it runs, so stop yours as soon as you're done.

#### WSL and Ubuntu (Windows only)

The Brev CLI doesn't run in PowerShell, only inside WSL (Windows Subsystem for Linux). If `wsl -l -v` already lists an
Ubuntu, skip this. Otherwise, in PowerShell **as administrator**:

```powershell
wsl --install -d Ubuntu-22.04
```

Reboot if asked, then open **Ubuntu** from the Start menu and create a Linux username and password (they're only for
WSL). Your Windows files are under `/mnt/c/` in Ubuntu, for example `/mnt/c/Users/you/Projects`.

#### Brev CLI

In the Ubuntu terminal (on macOS or Linux, a normal terminal):

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/brevdev/brev-cli/main/bin/install-latest.sh)"
```

No `sudo`: the installer puts `brev` in `~/.local/bin` for whoever runs it, so with `sudo` it would install for root
instead of you. Close and reopen the Ubuntu terminal so `~/.local/bin` is on your `PATH`, then:

```bash
brev --version
brev login       # opens a browser: sign in with your Brev account
brev ls          # the team's instances; empty until someone starts one
```

Run every `brev` command from that terminal, not from PowerShell. Other install options are in the
[Brev CLI docs](https://docs.nvidia.com/brev/latest/cli/getting-started).

Once the CLI is logged in, the web app can start and stop the team's GPU for you: see
[GPU from the web app](#gpu-from-the-web-app).

#### MSOE VPN

The GB10 is only reachable from MSOE's network. MSOE's VPN client is **GlobalProtect**; follow MSOE IT's
[VPN article](https://helpdesk.msoe.edu/support/solutions/articles/1000023935). In short (from a
[2021 faculty guide](https://faculty-web.msoe.edu/hasker/resources/vpn.html), so the article wins if they differ):

1. Sign in at <https://vpn.msoe.edu> and download the GlobalProtect agent (the 64-bit one on most Windows laptops). On an
   MSOE-imaged laptop it's already installed, or in Software Center.
2. Install it, open it, and set the portal to `vpn.msoe.edu`.
3. Sign in with your MSOE username **without** `@msoe.edu`, then connect from the tray icon. If it never asks for your
   credentials, restart the laptop.

#### Your SSH key on the GB10

Connect the VPN first. Windows has `ssh` built in; run these in PowerShell:

```powershell
ssh hackathon11@spark1.ai.msoe.edu    # first login: the password is in the GB10 access email (ask Alec)
```

The password is shared by the whole team: never put it in the repo, Slack, a script or `.env`. Add your own key once,
so you never need it again:

```powershell
ssh-keygen -t ed25519    # only if you don't have ~/.ssh/id_ed25519 yet; accept the defaults
type $env:USERPROFILE\.ssh\id_ed25519.pub | ssh hackathon11@spark1.ai.msoe.edu "mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"
```

On macOS or Linux, `ssh-copy-id hackathon11@spark1.ai.msoe.edu` does the same. Then check that you're in without a
prompt, since the web app can't type a password:

```powershell
ssh -o BatchMode=yes hackathon11@spark1.ai.msoe.edu true    # returns at once, with no output and no prompt
```

The GB10 is shared with other teams: check `who` and `nvidia-smi` before running anything heavy there by hand. The
team's one sim server is meant to stay running between uses (the web app connects to it); don't start a second Isaac Sim
next to it.

### GPU from the web app

The app runs jobs on the **mock** sim until you connect a real GPU target from its **GPU panel**: a **Brev** instance
(the team's credits, about $3/hr while it runs) or the **MSOE GB10** (free, always on, shared with other teams). One
target is connected at a time. The rest of the app doesn't care which: jobs always talk to `SIM_URL`, and the connected
target is forwarded there. How it works inside: [app/README.md](app/README.md#gpu-from-the-app).

**Who does what**

| When | Who | What |
| --- | --- | --- |
| Once per target | Whoever sets the target up | Put the repo and the sim server on it, following the [GPU test plan](docs/notes/gpu-test-plan.md). The team's Brev instance is set up; [CONTEXT.md](CONTEXT.md) has the GB10's status |
| Once per person | You | The accounts and tools for the targets you'll use (step 1), and your `.env` (step 2) |
| Each time | You | For the GB10, connect the VPN. Start the app, then connect a target in the GPU panel (step 4) |

#### 1. Your accounts and tools

Only for the targets you'll use. Each check is the same call the app makes, so if it passes, the app can get in too.

| Target | Set up (sections above) | Check |
| --- | --- | --- |
| Brev | [Brev account](#brev-account), [WSL and Ubuntu](#wsl-and-ubuntu-windows-only) (Windows only), [Brev CLI](#brev-cli), logged in | Windows PowerShell: `wsl -d Ubuntu -e bash -lc 'brev ls'`; macOS and Linux: `brev ls`. It lists the team's instance |
| MSOE GB10 | [MSOE VPN](#msoe-vpn), [your SSH key on the GB10](#your-ssh-key-on-the-gb10) | With the VPN connected: `ssh -o BatchMode=yes hackathon11@spark1.ai.msoe.edu true` returns with no prompt |

#### 2. Your `.env`

In the repo root (copy `.env.example` if you don't have one; it's gitignored). On Windows:

```bash
SIM_BACKEND=http
SIM_URL=http://127.0.0.1:9000
COMPUTE_BACKENDS=brev,gb10
COMPUTE_BREV_WSL=Ubuntu      # the WSL distro the Brev CLI is installed in
```

On macOS and Linux, leave out `COMPUTE_BREV_WSL`. List only the targets you've set up, e.g. `COMPUTE_BACKENDS=gb10`.
Leave the GB10 settings at their defaults: the whole team shares one sim server there, so everyone must use the same
port (`COMPUTE_GB10_SIM_PORT`, 9011). Never put the GB10 password in `.env`; the app only uses your SSH key.

#### 3. Check that the app sees your targets

Start the backend. Its startup log says `compute=brev,gb10`, and it refuses to start if a setting is missing (the log
says which). Then open <http://localhost:8000/api/compute/instances> in a browser. Its `instances` should list the Brev
instance and `spark1`. A target that can't be reached is listed under `errors`, with what to fix (see
[Troubleshooting](#troubleshooting)); the others still work.

#### 4. Use it

1. With the backend running, start the frontend's dev server (`npm run dev` in `app/frontend`) and open
   <http://localhost:5173/>. The GPU panel opens from the Compute box at the foot of the sidebar.
2. Choose a target:
   - **Brev:** choose it and press **Start the GPU**. Booting takes a few minutes, plus about a minute for Isaac Sim.
   - **GB10:** choose `spark1` and press **Connect**. It's quick if the team's sim server is running, and about a
     minute if it has to start.

   The panel shows each step.
3. When it says **Ready** (or **Connected**), run jobs. Until then, a job, a resume or a prediction is refused with the
   reason. Until the new UI has its job pages, start jobs through the API at <http://localhost:8000/docs> (see
   [backend-api.md](docs/notes/backend-api.md)).
4. When you're done:
   - **Brev:** press **Stop the GPU**. It also stops by itself after 20 minutes without a job, but don't leave it to
     that.
   - **GB10:** press **Disconnect**. This closes only your connection; the sim server stays up for your teammates.

   Closing the browser doesn't end anything: the session and every job run in background processes, even across API
   restarts, and the API still has them when you come back. They do run on this laptop, though: keep it awake, and on
   the VPN for the GB10.

**If the VPN drops** (or your connection to Brev does) during a job, nothing needs restarting. The panel says the sim
server isn't answering, and running jobs wait for it, for up to 2 hours (`SIM_RECONNECT_MINUTES`). Reconnect
GlobalProtect: within about a minute the panel reconnects by itself, and each job carries on with the round it was in,
without running it again. A job that waited longer fails; connect the GPU again and resume it, and it carries on after
its last finished round.

#### Working on the GPU code

- **No GPU needed:** with the default `COMPUTE_BACKENDS=mock`, the panel shows two made-up targets and sessions run
  against them, so the panel and the session logic work offline. `uv run pytest` covers the Brev and GB10 clients with
  fake CLI and ssh runners.
- **The sim server on a target is a copy.** After you change `sim/sim_server`, update the copy on the target and restart
  its server, as the [GPU test plan](docs/notes/gpu-test-plan.md) says. The GB10's server is shared, so tell your team
  before you restart it.
- **Logs:** `DATA_DIR/compute.log` (sessions), `DATA_DIR/compute_forward.log` (the port forward), and on the target
  `runs/sim_server.log` in the repo.

### CAD: not covered yet

Real CAD output (e.g. CadQuery → STEP/STL) isn't implemented. The app writes placeholder OpenSCAD files and needs no CAD
software.

## Troubleshooting

| Problem | Fix |
| --- | --- |
| `uv`, `git`, `node` or `npm` isn't found after installing | Close and reopen the terminal (and VS Code) so it picks up the new `PATH`. |
| PowerShell says `npm.ps1 cannot be loaded because running scripts is disabled` | Run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, or use `npm.cmd` instead of `npm`. |
| `npm ci` fails with "package.json and package-lock.json are not in sync" | Someone changed `package.json` without committing the lockfile. Run `npm install` in `app/frontend/` and commit `package-lock.json`. |
| `npm run dev` shows the page but API calls fail (`ECONNREFUSED`) | The backend isn't running, or it's on another port: start it, or set `API_URL` (see [Web app](#web-app-app)). |
| PowerShell won't run the uv installer | Use the exact command above. `-ExecutionPolicy ByPass` applies to that one command only. |
| The app stops at startup with "config problem(s)" | A backend you selected is missing a setting. The log names the variable: set it in `.env` (see `.env.example`), or unset the backend to use the mock. |
| Port 8000 is already in use | Run with `--port 8001`, or stop the other server. |
| Git asks for a password | Sign in through the Git Credential Manager browser window. GitHub doesn't accept account passwords over HTTPS. |
| A commit is blocked by the pre-commit guard | It says why: a file over 5 MB, an `.env` file, model weights, or something that looks like a key. Take that file out of the commit. |
| `brev: command not found` | It's installed inside WSL: run it in the Ubuntu terminal, not PowerShell. Just installed? Open a new Ubuntu terminal so `~/.local/bin` is on your `PATH`, or run `~/.local/bin/brev`. If you installed it with `sudo`, it went to root's home: install it again without `sudo`. |
| `wsl --install` fails, or WSL won't start | Run PowerShell as administrator. If it still fails, turn on virtualization (VT-x or AMD-V) in the laptop's BIOS/UEFI settings. |
| `ssh ... spark1.ai.msoe.edu` times out or can't resolve the host | The MSOE VPN isn't connected. Connect GlobalProtect first. |
| The GB10 still asks for the password after adding your key | Check you sent the `.pub` file, then on the GB10 run `chmod 700 ~/.ssh` and `chmod 600 ~/.ssh/authorized_keys`. |
| The app won't start: "COMPUTE_BACKENDS=... forwards the sim server to this machine, so it needs SIM_BACKEND=http and a local SIM_URL" | Set `SIM_BACKEND=http` and `SIM_URL=http://127.0.0.1:9000` in `.env` ([step 2](#2-your-env)). |
| GPU panel: "can't reach the GB10 (spark1.ai.msoe.edu): connect the MSOE VPN" | Connect GlobalProtect, then press **Refresh the list**. |
| GPU panel: "the GB10 refused the login as hackathon11: add your SSH key" | Add your key ([Your SSH key on the GB10](#your-ssh-key-on-the-gb10)) and check it with the `BatchMode=yes` command there. |
| GPU panel: "the GB10's host key changed" | Don't delete the old key from `known_hosts` to get past it: ask in `#compute-questions` first, since it can mean you're not talking to the real GB10. |
| GPU panel: "GB10 not set up" | The repo or Isaac Sim is missing on the GB10. Whoever maintains it sets it up again ([GPU test plan](docs/notes/gpu-test-plan.md)). |
| GPU panel: "Isaac Sim hung (or exited) while starting, as it sometimes does; trying again" | Normal on the GB10, about 1 start in 4: the panel retries by itself, up to 3 starts. Nothing to do. |
| GPU panel: "Isaac Sim didn't start on spark1 in 3 tries" | Rare. Read `runs/sim_server.log` (and `sim_server.prev.log`) in the repo on the GB10, then press **Connect** again. Ask in `#compute-questions` if it keeps failing. |
| GPU panel: "port 9011 on the GB10 is held by another account" | Another team took the port. Agree a new one with your team, and everyone sets `COMPUTE_GB10_SIM_PORT` to it. |
| GPU panel: "brev ls failed: ..." or "can't run the Brev CLI" | Run `brev login` in the Ubuntu terminal. If it's not installed, see [Brev CLI](#brev-cli); on Windows, set `COMPUTE_BREV_WSL=Ubuntu`. |
| GPU panel: "... is FAILURE on Brev after the start request" | Usually no GPU of that type is free in its region right now. Try again in a few minutes, and check the instance's Activity Logs in the Brev console. |
| GPU panel: "the port forward ... exited" | See `DATA_DIR/compute_forward.log`. Often something else is using local port 9000: stop it, or move `SIM_URL` to another port. For Brev, also try `brev refresh` in Ubuntu. |
| GPU panel: "The sim server isn't answering (...); retrying, and running jobs wait up to 120 min for it" | The connection dropped, usually the VPN: reconnect GlobalProtect. The panel reconnects by itself and the jobs carry on ([if the VPN drops](#4-use-it)). |
| A job failed: "... didn't answer again within 120 min: reconnect the GPU in the GPU panel, then resume the job" | The connection was down longer than `SIM_RECONNECT_MINUTES`. Connect the GPU, then resume the job (`POST /api/jobs/{id}/resume`): it carries on after its last finished round. |
| A job is refused: "The GPU isn't connected" | Connect a target in the GPU panel and wait for **Ready** or **Connected** ([step 4](#4-use-it)). |
