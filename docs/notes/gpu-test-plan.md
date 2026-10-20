---
title: GPU test plan for the sim server (grasp evaluation in the FANUC ER-4iA twin)
source: our own runbook, written alongside sim/sim_server (POST /evaluate_batch)
author: Alec Weinbender's Team
received: 2026-10-19
kind: note
status: DRAFT; stages 0–3 run on Brev 2026-10-20 (docs/experiments/2026-10-20-brev-sim-server-bringup.md); 0.2 and stages 1–6 run on the GB10 2026-10-20 (docs/experiments/2026-10-20-gb10-sim-server-bringup.md, docs/experiments/2026-10-20-gb10-stages-4-6.md)
---

# GPU test plan: sim server

The sim server's grasp loop (`sim/sim_server`) was written on a Windows laptop **without Isaac Sim**. Only its host tests
have run (`uv run pytest sim/sim_server/tests`: models, frames, units, packing, the IK plan including the transport move,
the in-hand pose math, the batch bookkeeping against a fake cell, the routes, the layering). Nothing about physics,
the Isaac API calls, or GPU behaviour is validated until this runbook has been worked through. That includes all of
contract v2 (mesh parts, cylinders along x, part friction, the grip-force limit, transport, the in-hand readout), which
stage 5 checks. Go in order: each stage assumes the previous one passed. Commands marked **[guess]** haven't been checked
against the instance.

Background: [sim/README.md](../../sim/README.md#sim_server) (flags, contract, the gripper frame G, what a grasp is).

## 0. Machines and access

We have two machines ([GB10 access](../04-gb10-access.md), [Brev credits](../05-brev-credits.md)):

| | Brev, Isaac Sim launchable | MSOE GB10 (`spark1.ai.msoe.edu`) |
| --- | --- | --- |
| Cost | the team's $500 of credits, billed while the instance runs | free |
| Platform | x86_64 Linux, RTX PRO 6000 or 4500: close to the twin's validated setup (Linux, Isaac Sim 6.0, RTX A6000) | ARM64 (DGX Spark platform), shared with other teams; Isaac Sim 6.0.1 from NVIDIA's aarch64 pip wheels, already installed (0.2) |
| Main risk | spending credits | other teams on the GPU (check `nvidia-smi`); the driver must stay on R580, since NVIDIA reports R590+ crashes Isaac Sim 6.0 at RTX startup on DGX Spark |
| Use it for | a second machine, and x86 checks | the default: stages 1–3 pass there and agree with Brev's (2026-10-20) |

**Order (done 2026-10-20):** the GB10 check passed, and stages 1–3 pass on both machines. The GB10's stage 3 grids agree
with Brev's as well as each machine agrees with itself: 92.6–96.3% across machines, against 95.1% (GB10) and 91.4% (Brev)
within one ([log](../experiments/2026-10-20-gb10-sim-server-bringup.md)). Stages 4–6 ran on the GB10
([log](../experiments/2026-10-20-gb10-stages-4-6.md)). So use the GB10 (free) by default, and Brev when the GB10 is busy.
Before relying on a new kind of result from one machine, rerun a grid on the other and `send_batch.py --compare`.

**The machine needs the current code.** Both machines run a copy of a pushed commit (Brev: 0.1 step 5; the GB10: 0.2).
Push before a session, and note the commit the machine runs in the experiment log.

### 0.1 Brev: the known-good path

1. **Account (Alec, once):** open the invite link in Dan Schneider's email and create the Brev account. Then Team →
   generate a link for teammates (role "member"). Billing shows the credits left.
2. **CLI on your laptop**, for `brev shell`, `brev copy` and `brev port-forward`: WSL with Ubuntu (on Windows) and the
   Brev CLI, set up once per [SETUP.md](../../SETUP.md#gpu-machines-brev-and-the-msoe-gb10). Run `brev` commands from
   the Ubuntu terminal.
3. **Start the instance:** open the
   [Isaac Sim launchable](https://brev.nvidia.com/launchable/deploy?launchableID=env-35JP2ywERLgqtD0b0MIeK1HnF46), check
   its description names Isaac Sim 6.0, then **Change → Change compute** → RTX PRO 6000 (or RTX PRO 4500 if it's cheaper
   per hour) → **Save compute** → deploy. Pick only instance types that can be stopped and started; both of those can.
   Note the start time and the $/hr.
4. **Connect:** run `brev refresh` once (it writes the SSH alias), then `brev shell <instance>` or `ssh <instance>` opens
   a shell on the VM as `ubuntu`. Isaac Sim is inside the `vscode` container: `docker exec -it vscode bash`. Start
   `tmux` on the VM (the container has none) and run long commands from it with `docker exec -it vscode ...`, so a dropped
   connection doesn't kill the server.
5. **Get the repo onto it.** The repo is private: either clone with a read-only credential (a fine-grained GitHub token
   limited to this repo, or a deploy key), or pack the pushed commit on the laptop and copy it. Unpack it on the VM, then
   copy it into the container:

   ```bash
   git archive --format=tar.gz --prefix=repo/ -o repo.tgz <commit>   # on the laptop; committed files only
   brev copy repo.tgz <instance>:/home/ubuntu                        # then on the VM: tar xzf repo.tgz (makes ~/repo)
   tar -C ~ --exclude='repo/sim/fanuc_er4ia_sim/.venv' -cf - repo | docker exec -i vscode tar -C /root -xf -
   ```

   Run that last line after the twin's `bootstrap.sh` (stage 1), so the container's copy gets the generated textures.

**What's on the Isaac launchable** (NVIDIA's [isaac-launchable](https://github.com/isaac-sim/isaac-launchable) v1.7,
checked 2026-10-20 on an RTX PRO 4500 at $3.07/hr):

- **First deploy takes about 13 minutes:** the VM is up in about 3, then a create-only setup script pulls and builds about
  52 GB of container images. Wait until `docker ps` shows `vscode` as Up; `brev ls` says RUNNING well before that.
- **The `vscode` container** has Isaac Sim 6.0.1 at `/isaac-sim` (so `ISAAC=/isaac-sim`; `VERSION` reads
  `6.0.1-rc.7+release.42383...`), and Isaac's Python 3.12 has torch 2.10 with CUDA. It uses the host's network, so a
  server on port 9000 inside it is on the VM's `127.0.0.1:9000` (what `brev port-forward` reaches). It runs as root, has
  no `python3` or `tmux`, and shares no folder with `/home/ubuntu`.
- **The VM** has Python 3.12, `tmux` and `git`: run the twin's `bootstrap.sh` and `send_batch.py` there.
- **The driver is 595.71.05**, and Isaac Sim 6.0.1 runs headless on it here: the scene builds and the sim server
  answers. The R590+ crash in 0.2 hasn't shown up on this machine.
- **Stop and Start keep everything:** one persistent 247 GB disk holds the Docker images, the `vscode` container (with
  the repo and the pip install inside), `~/repo` and the caches; the setup script doesn't run again. Programs don't
  survive a stop, so start the sim server again, and run `brev refresh` for the new address. **Delete** wipes it all.
  **[to confirm on the first restart]**
- **The twin's `.sh` files aren't executable in git** (committed from Windows): run `bash bootstrap.sh`, or fix them with
  `git update-index --chmod=+x sim/fanuc_er4ia_sim/*.sh`.

### 0.2 MSOE GB10: free, shared, set up

Set up and checked 2026-10-20 ([log](../experiments/2026-10-20-gb10-sim-server-bringup.md)). Isaac Sim, the sim server
and the repo are already on the team account, so a session is steps 1, 2 and 5.

1. **Connect:** with the MSOE VPN (GlobalProtect) and your SSH key set up once per
   [SETUP.md](../../SETUP.md#gpu-machines-brev-and-the-msoe-gb10), `ssh hackathon11@spark1.ai.msoe.edu`. The shared
   password is in Riley's email: never put it in the repo, Slack or a script.

2. **Check the machine before a session** (nothing here changes it):

   ```bash
   nvidia-smi        # the driver (580.178.04 on 2026-10-20), and which processes (other teams) use the GPU
   who               # who else is logged in
   ss -ltn           # ports in use; ours is 9011
   df -h ~           # free disk (1.6 TB on 2026-10-20)
   ```

   **The driver must stay on R580.** Isaac Sim 6.0 was tested on DGX Spark with 580.142
   ([requirements](https://docs.isaacsim.omniverse.nvidia.com/6.0.0/installation/requirements.html)), and NVIDIA's fix for
   6.0.x crashing at RTX startup on a Spark with a 595 driver is 580.159.03
   ([forum](https://forums.developer.nvidia.com/t/isaac-sim-6-0-1-gpu-crash-on-dgx-spark-gb10-arm64-driver-595-71-05/376418)).
   If it ever shows 590 or newer, don't run Isaac: ask Riley (driley@nvidia.com). It's shared, so it's their call. Stay
   on Brev meanwhile. If another team is using the GPU, timings aren't comparable; note it.

3. **What's on the GB10** (account `hackathon11`, set up 2026-10-20):

   - **The machine:** NVIDIA DGX Spark, GB10 (sm_121; 128 GB of memory shared by the CPU and GPU, so `nvidia-smi` shows
     memory as N/A), 20 Arm cores, DGX OS 7.5 (Ubuntu 24.04, `/etc/dgx-release`), driver 580.178.04, CUDA 13.0. The team
     account has no sudo and no Docker access. It has Python 3.12, git, tmux and curl, but no gcc-11 or git-lfs, so
     NVIDIA's source build ([Spark playbook](https://build.nvidia.com/spark/isaac/isaac-sim)) isn't an option from it.
   - **Isaac Sim 6.0.1 in `~/isaac-sim-6.0.1`**, from NVIDIA's aarch64 pip wheels, in a venv: `ISAAC=~/isaac-sim-6.0.1`.
     Its `python.sh` is our stand-in for Isaac's: it runs the venv's Python with `OMNI_KIT_ACCEPT_EULA=YES` (accepting
     NVIDIA's EULA) and `LD_PRELOAD=/lib/aarch64-linux-gnu/libgomp.so.1` (needed on DGX Spark). There's no `VERSION`
     file; `"$ISAAC/venv/bin/python" -m pip show isaacsim` gives the version. torch 2.11.0+cu130 sees the GPU.
   - **`~/isaac-sim-6.0.1/install.sh`** reinstalls it (about 5 minutes, 19 GB). It uses uv's standalone CPython 3.12,
     because the system Python has no headers (`python3.12-dev` isn't installed, and there's no sudo), while `psutil`
     5.9.8 and `PyOpenGL-accelerate` 3.1.10 have no aarch64 wheels and build from source. Then it installs
     torch 2.11.0 (`cu130`) first, and `isaacsim[all,extscache]==6.0.1.0` from pypi.nvidia.com, as NVIDIA's
     [pip instructions](https://docs.isaacsim.omniverse.nvidia.com/6.0.0/installation/install_python.html) say.
   - **The sim server is installed in that venv** (`pip install -e`, from `~/repo`) **with Isaac's pins put back**.
     `isaacsim-kernel` pins `uvicorn==0.29.0`, `websockets==12.0` and `httptools==0.6.1`, and installing the sim server
     upgrades all three. After any `pip install -e sim/sim_server`, run
     `"$ISAAC/python.sh" -m pip install uvicorn==0.29.0 websockets==12.0 httptools==0.6.1`. `pip check` then reports only
     the sim server's own `uvicorn>=0.30` floor, which doesn't matter: it uses nothing newer.
   - **The repo in `~/repo`** is a `git archive` of a pushed commit, not a clone: there's no `.git`, and no GitHub
     credentials on the shared account. `~/repo/COMMIT` says which commit. `~/repo/runs/` holds every result so far
     (Brev's under `runs/brev/`, for `--compare`).

4. **Update the repo on the GB10** to a newer pushed commit:

   ```bash
   git archive --format=tar.gz --prefix=repo/ -o repo.tgz <commit>   # on the laptop: committed files only
   scp repo.tgz hackathon11@spark1.ai.msoe.edu:
   # on the GB10: replace the code, keep runs/
   mv ~/repo ~/repo-old && tar xzf ~/repo.tgz -C ~ && echo <commit> > ~/repo/COMMIT && mv ~/repo-old/runs ~/repo/
   (cd ~/repo/sim/fanuc_er4ia_sim && bash bootstrap.sh)              # the twin's host venv and textures
   rm -rf ~/repo-old ~/repo.tgz
   ```

   The sim server's editable install points at `~/repo/sim/sim_server/src`, so it picks up the new code. Reinstall it
   only if its `pyproject.toml` changed, then put Isaac's pins back (step 3).

5. **Start the sim server detached, and watch that it starts:**

   ```bash
   cd ~/repo && export ISAAC=~/isaac-sim-6.0.1
   setsid nohup stdbuf -oL -eL "$ISAAC/python.sh" -m sim_server --port 9011 < /dev/null >> runs/sim_server.log 2>&1 &
   echo $! > runs/sim_server.pid                      # "Uvicorn running" in the log after 10–25 s (more copies: longer)
   kill -INT "$(cat runs/sim_server.pid)"             # stop it: a clean shutdown in about 2 s
   ```

   **Isaac's start-up fails intermittently on the GB10:** 3 of 12 starts on 2026-10-20.

   - Two hung before Kit logged anything, asleep on a lock at 0% CPU. One was in tmux, one detached.
   - One segfaulted 1.2 s in, inside NVIDIA's EGL/Vulkan start-up.
   - Every retry worked. So if the log has no `Simulation App Startup Complete` within about 90 s, kill the process
     (`kill -KILL`) and start again.

   `setsid nohup` keeps a server, or a script of batches, alive through a dropped SSH connection. `runs/simctl.sh` wraps
   the start: source it from `~/repo`, then `sim_start <log name> [sim_server flags]` and `sim_stop`. The watchdog loop is
   in `runs/stage6_256.sh`. The first start after an install also builds caches: the twin's scene build took 159 s the
   first time (59 s on Brev).

6. **Sharing the machine:** other users on the GB10 can reach its `127.0.0.1` ports, and two servers can't share a port.
   Run the sim server there with `--port 9011` (stage 7 tunnels to it). Teammates share the account, so check
   `ss -ltn` or `runs/sim_server.pid` before starting a second server. **Stop it when you're done**, so it doesn't hold
   GPU memory other teams need.

## 1. Setup and environment check

On the Brev launchable, run the Isaac commands below inside the `vscode` container and `bootstrap.sh` on the VM (see
0.1). The `ls` and `VERSION` guesses are settled there: `ISAAC=/isaac-sim`. On the GB10 (0.2), everything runs on the
machine itself with `ISAAC=~/isaac-sim-6.0.1`. There's no `VERSION` file there (use `pip show isaacsim`), and after the
sim server's `pip install` you put Isaac's pins back (0.2, step 3). All of stage 1 is already done there.

```bash
cd ~/<repo>                                  # the repo root; every command below runs from here
mkdir -p runs                                # gitignored
ls -d /isaac-sim /isaacsim ~/isaacsim 2>/dev/null   # [guess] where the launchable keeps Isaac; the twin defaults to /isaacsim
export ISAAC=/isaac-sim                      # whichever directory holds python.sh; on the GB10, the build from 0.2
nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv | tee runs/gpu.txt
cat "$ISAAC/VERSION" 2>/dev/null | tee runs/isaac_version.txt   # [guess] file name
"$ISAAC/python.sh" -c "import numpy, torch; print(numpy.__version__, torch.__version__, torch.cuda.is_available())"
```

The vectorised path needs `torch` with CUDA in Isaac's Python (it's the tensor backend for GPU physics). If the last command
fails, the reference path still works; note it and skip stage 6.

Check the driver in `runs/gpu.txt` too: Isaac Sim 6.0 was tested on 580.95.05 on x86_64 Linux, and NVIDIA's forum reply
(linked in 0.2) says R590 drivers also break its RTX renderer on RTX PRO 6000 Blackwell. A crash at startup with a 590+
driver is that, not our code.

Install the sim server into Isaac's Python and check that pip didn't replace anything Isaac bundles:

```bash
"$ISAAC/python.sh" -m pip install -e sim/sim_server 2>&1 | tee runs/pip_install.log
grep -iE "uninstalling|successfully installed" runs/pip_install.log   # expect only fastapi, uvicorn and their deps
```

Twin environment check (the organizers' own pipeline; see `sim/fanuc_er4ia_sim/SETUP.md`):

```bash
cd sim/fanuc_er4ia_sim
mkdir -p runs                                                     # the twin's own (gitignored) run directory
./bootstrap.sh                                                    # host venv, textures, 33 host tests: all must pass
"$ISAAC/python.sh" build_scene.py --headless --save runs/scene.usd   # needs the robot USD from Isaac's asset root
export COSMOS=/path/to/cosmos-env/bin/python COSMOS3_NANO_PATH=/path/to/Cosmos3-Nano/snapshot
./run_sort_pipeline.sh runs/stack_01
python3 -c "import json; r = json.load(open('runs/stack_01/execution_report.json')); print(r['task_complete'], r['verified_pickups'], r['verified_placements'])"
cd ../..
```

Pass: `True 6 6`. Isaac can exit 0 after an exception, so read the report, not the exit code. Without a Cosmos
environment the stacking run can't happen (it needs perception); then `build_scene.py` succeeding is the minimum, and
the log should say the stacking check was skipped. If the twin itself fails here, stop: the sim server builds on it.

## 2. S1: one grasp, reference path

Start the server (reference path: the twin's own robot, CPU physics, one grasp at a time):

```bash
tmux new -s sim
"$ISAAC/python.sh" -m sim_server --port 9000 2>&1 | tee runs/sim_server_s1.log
```

On the GB10, start it detached on port 9011 instead (0.2, step 5), and add `--url http://127.0.0.1:9011` to every
`send_batch.py` command below.

Wait for `Grasp cell ready` and uvicorn's `Uvicorn running on http://127.0.0.1:9000`. Check the `Grasp cell ready` line:
the DOFs must include `J1`..`J6`, `jaw_l` and `jaw_r`, and the jaws should close along `(0.0, 1.0)` or `(0.0, -1.0)`. A
`RuntimeError` about the gripper layout or missing `.../Collision` means the twin's `cell.py` differs from what
`sim_server/clients/isaac.py` expects. The same line ends with the scene description (`describe()`, also in `/health`
and every batch's `sim` block): `physics_dt` 0.0167, `solver_position_iterations` 16 and `solver_velocity_iterations` 2
(the part body, from the twin's `make_dynamic`), `contact_offset_mm` 0.2, `rest_offset_mm` 0.0, `solver_type`, and
`robot_solver_iterations` as the robot USD authors them (`None` means PhysX's default). The backend compares the first
group with the job's cell profile. An exception while building it (`Usd.PrimRange`, `get_solver_type`) stops startup:
report it.

From a second shell (`tmux` split, or `brev shell` again):

```bash
curl -s http://127.0.0.1:9000/health          # {"status": "ok", "queued": 0, "envs": 1, "device": "cpu", "physics_dt": ..., ...}
python3 sim/sim_server/scripts/send_batch.py sim/sim_server/scripts/batches/stock_cube.json --out runs/s1_stock_cube.json
```

Pass: `stock held 1/1` (the twin's 10 mm, 4 g cube, stock fingers, zero offset; the twin itself picks these). The server
log's `Batch done` line gives the time per grasp; note it.

Then a handful of offsets, the same batch twice (CPU physics should repeat exactly), and a lying cylinder:

```bash
python3 sim/sim_server/scripts/send_batch.py sim/sim_server/scripts/batches/stock_cube_offsets.json --out runs/s1_offsets_a.json
python3 sim/sim_server/scripts/send_batch.py sim/sim_server/scripts/batches/stock_cube_offsets.json --out runs/s1_offsets_b.json
python3 sim/sim_server/scripts/send_batch.py --compare runs/s1_offsets_a.json runs/s1_offsets_b.json   # expect 100% agreement
python3 sim/sim_server/scripts/send_batch.py sim/sim_server/scripts/batches/stock_cylinder_lying.json --out runs/s1_cylinder.json
```

What to expect (from geometry, not yet observed): the open stock hook tips are 16 mm apart, so a 10 mm cube has about 3 mm
of slack per side along dx; ±1 and ±2 mm should hold, 3 mm is borderline. ±2 mm dy and ±15° yaw should hold. Results
should be mirror-symmetric in dx (the fingers are). If even the zero offset drops:

- restart with `--log-level DEBUG` and read the `Env 0: part centre ...` line: the part should sit at (0.30, 0.0) in the
  base frame, 5.1 mm below the base plane plus half its height;
- a `422` with `IK failed` means the planner can't reach the site: report the message;
- `non-finite positions` in the log means physics blew up (check contact offsets and the part's spawn height).

If the twin's cube works but the first batch with another part (the cylinder) answers `HTTP 500`, and the server log shows
`RuntimeError: There is no current event loop in thread 'MainThread'` from `uvloop`, the server is running uvicorn on
uvloop: Kit's extensions use asyncio on the main thread whenever the stage is edited. `__main__.py` passes
`loop="asyncio"` to uvicorn for this (found on Brev 2026-10-20); restart the server after updating, since the failed edit
leaves the stage half changed.

Sign check for dx: restart with `--log-level DEBUG` and send `stock_cube_offsets.json` again. On the reference path every
grasp logs one `Env 0: part centre ...` line, in offset order; the sixth (dx = +3 mm) must sit 3 mm from the first along the
logged `JawL toward` direction.

## 3. S1 grid: the app's 81 offsets, stock fingers

```bash
python3 sim/sim_server/scripts/send_batch.py sim/sim_server/scripts/batches/stock_cube.json --grid --out runs/s1_stock_grid.json
```

`--grid` sends the app's default grid (centre plus rings at 1..8, 10, 12 mm, 8 directions, yaw 0) and prints a held map,
one row per ring, columns going round from +dx (toward JawL) through +dy. Copy the map into the experiment log. It should
be symmetric under dx → −dx and dy → −dy; an asymmetric map points at a frame or sign error.

Observed on Brev (2026-10-20, [log](../experiments/2026-10-20-brev-sim-server-bringup.md)): every ring out to 5 mm held,
and grasps there repeat exactly, but beyond about 6 mm two runs of the same grid disagreed at 7 of 81 points, so one map
can look asymmetric by chance. Run the grid twice and `--compare` before calling an asymmetry a frame error; the stage 2
sign check settles it. Note the batch time: with D
designs, a reference-path batch takes about D × 81 × (seconds per grasp), and the app's `SIM_TIMEOUT_S` must exceed it.

Observed on the GB10 (2026-10-20, [log](../experiments/2026-10-20-gb10-sim-server-bringup.md)): 58 and 60 of 81 held
(Brev: 56 and 61), every ring out to 6 mm, except one drop at dx +5 mm. The two GB10 grids agree 77/81, and they agree
with Brev's 75–78/81. Every disagreement on either machine is along the jaw axis or on a 7 mm diagonal. Reference-path
speed: 2.75 grasps/s (81 grasps in 29.5 s), against 2.1 on Brev.

## 4. S3: custom fingers, reference path

`flat_pads.json` has the stock fingers and two flat-pad designs on the cube, swept along dx:

- `pad_x0`: one box, x 0..12, the stock blade's bounding box. Open gap 12 mm, so about 1 mm slack per side.
- `pad_x2`: the lower 46 mm recessed to x 2..12, the upper (mount) 30 mm unchanged. Open gap 16 mm, about 3 mm slack.

```bash
python3 sim/sim_server/scripts/send_batch.py sim/sim_server/scripts/batches/flat_pads.json --out runs/s3_flat_pads.json
python3 sim/sim_server/scripts/send_batch.py sim/sim_server/scripts/batches/flat_pads.json --grid --out runs/s3_flat_pads_grid.json
```

Pass (sanity, not a result): `pad_x2` tolerates larger |dx| than `pad_x0` (expect `pad_x0` to drop from |dx| ≈ 1.5 mm and
`pad_x2` from ≈ 3.5 mm). The log shows one `Stage edit (... finger swap(s)) and physics re-parse` line per design change;
note its time. If both pads behave like the stock fingers, the swap didn't take (stock colliders still active).

Observed on the GB10 (2026-10-20, [log](../experiments/2026-10-20-gb10-stages-4-6.md)): **the pass condition isn't met,
but the swap works.**

- Swaps take 0.3 s (0.8 s the first time), and the three designs give different maps and in-hand readings.
- `pad_x0` held 9/9 out to ±3.5 mm, the same as `pad_x2`. On the grid it even held dx ±8 mm, where the cube spans
  3–13 mm and one pad face (at 6 mm) must land on top of it. The cube still ended centred in the hand.
- So a finger that comes down on the part pushes it into the gap: the landing capture from the Brev log, Failure 4.
- The result: tight and loose pads score almost the same (55 and 56 of 81). This sanity check can't pass until a part
  disturbed during the descent is detected (read its pose at the end of the descent).

## 5. S4: contract v2, reference path

Same server as stages 2–4 (`--envs 1`, CPU). Every expectation below is arithmetic or geometry, **not an observation**;
the point is to see whether the physics agrees. Save every run with `--out`; stage 6 compares them with the GPU path.

**Observed on the GB10 (2026-10-20, [log](../experiments/2026-10-20-gb10-stages-4-6.md)):** light parts behave as
expected, and the 300 g block doesn't. **The twin grips with only about 2.5–3 N per jaw, not the ~40 N that 5.3–5.5
assume.**

| Check | Expected | Observed |
| --- | --- | --- |
| 5.1 in hand | centred about 0; dy ±2 reads ±2; flat pads square yaw ±10 | all as expected, except dz −1.27 mm on every grasp (as on Brev) |
| 5.2 L-bracket | rests on the mat; no hull errors; maps like the cube's | rests at z 7.0 mm; no errors; maps differ: stock 42/81 and can tumble it (tilt up to 110°), `pad_x2` 44/81 |
| 5.3 friction 0.08 / 0.3 / 0.9 at 15 N | dropped / held / held | 0/3, **0/3**, 3/3 |
| 5.3 part 0.08, pads 0.9 | `average` (0.49): held | 0/3; under `max` (0.9): 3/3, so the part's material and the combine mode are bound |
| 5.4 grip-force sweep (μ 0.08) | `none` held; held from about 18 N | **0/3 at every force, including `none`** |
| 5.5 cube with transport | kept | 9/9 for both designs |
| 5.5 block at 21 N | held at the lift; kept slow and normal, lost fast | **dropped at the lift every time** |

Measured with no force limit (the twin's drive): the 300 g block holds only from μ ≈ 0.6–0.7. At μ 0.3, blocks up to
100 g hold and 200 g drops. Even "held" blocks at μ 0.9 and 15 N slid 25–27 mm down the jaws and tilted 6–11°. So the
expected numbers in 5.3–5.5 don't apply until the twin's grip force is understood: the jaw drive's squeeze, or how the
close target is set for custom fingers. In 5.3, test the combine mode with `max`, not `min`: under `average`, 0.08 with
0.9 already drops.

### 5.1 In-hand readout sanity

`stock_cube_transport.json` has the stock fingers and the flat pad `pad_x2` on the 10 mm cube, at dx ±1, ±2, dy ±2 and
yaw ±10. Run it without its transport first:

```bash
python3 sim/sim_server/scripts/send_batch.py sim/sim_server/scripts/batches/stock_cube_transport.json --transport none --out runs/s4_in_hand.json
```

Each held grasp prints `in hand dx .. dy .. dz .. mm, tilt .., yaw .. deg`. Pass:

- **Centred part reads about 0** for both designs: |dx|, |dy| under 0.3 mm, |dz| under 0.5 mm, tilt and yaw under 1°.
  dz also picks up the arm lagging its commanded lift (G is the *commanded* frame) and the 0.1 mm spawn gap; a steady
  offset of a few tenths of a millimetre is expected, several millimetres is not.
- **dx offsets read about 0**: the closing jaws push the part to the middle. A dx that survives the close means the
  jaws stop asymmetrically; report it.
- **A dy offset with flat pads reads about dy**: nothing centres the cube across the jaws, so dy = +2 reads +2 (± 0.3).
  The sign matters: −2 here means G's y axis is flipped somewhere between `robot/poses.py` and Isaac's quaternions.
- **Yaw ±10 with flat pads reads about 0** (the pads square a box), with stock fingers anything from 0 to ±10.
- tilt stays under a degree or two for every held cube.

Record the per-offset readings in the experiment log; they're the baseline for the in-hand histograms.

### 5.2 Mesh-part contact

```bash
python3 sim/sim_server/scripts/send_batch.py sim/sim_server/scripts/batches/mesh_l_bracket.json --out runs/s4_mesh.json
python3 sim/sim_server/scripts/send_batch.py sim/sim_server/scripts/batches/mesh_l_bracket.json --grid --out runs/s4_mesh_grid.json
```

The L-bracket is two convex boxes: a 10 × 4 × 24 mm leg over the grasp centre and a 10 × 16 × 4 mm foot off to −y, 4.3 g,
aluminium-on-PLA friction (0.45 / 0.35). It is 10 mm wide along the jaws, like the cube, so the stock fingers fit. Pass:

- the log shows `Stage edit (new part, ...)` and no PhysX cooking or convex-hull errors;
- with `--log-level DEBUG`, the `Env 0: part centre` line sits 12 mm (half the height) above the surface: the pieces were
  recentred and the bracket rests on the mat rather than dropping onto it or starting inside it;
- both designs hold at the centre, and the held maps look like the cube's (the leg is what's gripped);
- in hand: the foot pulls the centre of mass toward −y, so a small tilt (a few degrees, about G's x) is plausible; a
  large tilt or yaw at the centre is not.

If the bracket falls through the mat or jitters at rest, check its contact offsets and that each piece got
`convexHull` (the stage can be saved from the Kit console, or temporarily from `_author_parts`, and inspected).

### 5.3 Part friction

The part's material should change what holds. `heavy_block_grip_force.json` is a 300 g block (10 × 40 × 40 mm) with a
15 N per-jaw force limit, flat pads, and the same friction on part and pads. Make friction variants:

```bash
python3 - <<'PY'
import json
b = json.load(open("sim/sim_server/scripts/batches/heavy_block_grip_force.json"))
for mu in (0.08, 0.3, 0.9):
    b["part"]["friction"] = b["designs"][0]["friction"] = [mu, round(0.75 * mu, 3)]
    json.dump(b, open(f"runs/heavy_mu_{mu}.json", "w"))
PY
for mu in 0.08 0.3 0.9; do
  python3 sim/sim_server/scripts/send_batch.py runs/heavy_mu_$mu.json --out runs/s4_friction_$mu.json
done
```

Expected from the friction limit, 2 μ F against the weight (0.3 kg × 9.81 = 2.94 N) at F = 15 N: μ 0.08 → 2.4 N, dropped;
0.3 → 9 N and 0.9 → 27 N, held. To check that the part's own material is bound (not only the fingers'), restart with
`--friction-combine min`, keep the pads at 0.9 and set only the part to 0.08: `min` gives 0.08 and the block should drop;
under `average` (0.49) it should hold. If nothing changes with the part's friction, the part colliders aren't using
`/World/Physics/PartMaterial`.

### 5.4 Grip-force limit

```bash
python3 sim/sim_server/scripts/send_batch.py sim/sim_server/scripts/batches/heavy_block_grip_force.json --out runs/s4_force_15.json
python3 sim/sim_server/scripts/send_batch.py sim/sim_server/scripts/batches/heavy_block_grip_force.json --grip-force none --out runs/s4_force_none.json
for f in 10 20 25 30; do
  python3 sim/sim_server/scripts/send_batch.py sim/sim_server/scripts/batches/heavy_block_grip_force.json --grip-force $f --out runs/s4_force_$f.json
done
```

Expected: at 15 N the block slips out (2.4 N of friction for 2.94 N of weight). With `none` the twin's 180 N limit
doesn't bite: the jaw drive is a stiff position servo (4e4 N/m), and `jaw_close_mm` 2.0 commands the pads 1 mm past the
block's faces, so it squeezes about 40 N per jaw: 6.4 N of friction, held. The sweep should switch from dropped to held
near 2.94 / (2 × 0.08) ≈ 18 N. A failed `set_max_efforts` call (wrong argument types on this Isaac version) raises on the
first batch; report the traceback.

Caveat to check here: the twin's jaw drive also has damping (3e3 N·s/m), and the force limit caps the whole drive force,
so it caps the closing speed too, at F / 3000 m/s (5 mm/s at 15 N). The pads travel 3 mm to this block, which fits in the
1.1 s of close and dwell only for F above about 8 N. If drops continue well above 18 N, or a light cube drops at a low
limit, the jaws probably hadn't reached the part when the lift began: then the limit should switch on at the end of the
close segment instead of before the chunk (a small change in `GraspCell.run_chunk`); report it.

### 5.5 Transport slip

```bash
python3 sim/sim_server/scripts/send_batch.py sim/sim_server/scripts/batches/stock_cube_transport.json --out runs/s4_cube_transport.json
for t in slow normal fast; do
  python3 sim/sim_server/scripts/send_batch.py sim/sim_server/scripts/batches/heavy_block_grip_force.json --grip-force 21 --transport $t --out runs/s4_transport_$t.json
done
```

The move is 0.12 m along base +X (across the jaws) with smoothstep easing, so its peak acceleration is 6 × 0.12 / T²:
0.5, 2 and 8 m/s² for slow, normal and fast. Expected:

- the 4 g cube: held after transport wherever it was held (its inertia is tiny next to the grip);
- the 300 g block at 21 N (3.36 N of friction): held at the lift everywhere; after transport it needs about
  m √(g² + a²) = 2.95, 3.0 and 3.8 N, so kept for slow and normal, lost for fast. The margins are thin, so the shape
  (monotonic in speed) matters more than the exact switch point.
- no `422 ... IK failed during transport`: the planner checks the move on the host, but report it if Isaac's arm can't
  follow (the part would be left behind with the gripper stopping short of x = 0.42 m).

The `Batch done` line shows the extra time per grasp (the plan grows from 117 frames to 141, 150 or 168).

## 6. S2: vectorised path, and agreement with the reference

Stop the server (Ctrl-C in its tmux pane) and restart it with copies on the GPU:

```bash
"$ISAAC/python.sh" -m sim_server --port 9000 --envs 64 2>&1 | tee runs/sim_server_s2_64.log
```

Check the startup log: `Copied the robot and mat into 64 environments`, `GPU physics on cuda:0: gpu dynamics True,
broadphase GPU`. Then rerun stages 3 and 4 and compare with the reference:

```bash
python3 sim/sim_server/scripts/send_batch.py sim/sim_server/scripts/batches/stock_cube.json --grid --out runs/s2_stock_grid_64.json
python3 sim/sim_server/scripts/send_batch.py --compare runs/s1_stock_grid.json runs/s2_stock_grid_64.json
python3 sim/sim_server/scripts/send_batch.py sim/sim_server/scripts/batches/flat_pads.json --grid --out runs/s2_flat_pads_grid_64.json
python3 sim/sim_server/scripts/send_batch.py --compare runs/s3_flat_pads_grid.json runs/s2_flat_pads_grid_64.json
```

The flat-pad batch is 243 grasps, so with 64 copies it runs in 4 chunks, and chunks mix designs (copies with different
fingers side by side). Agreement target: 100%; tolerable only at offsets next to the held/dropped boundary. GPU PhysX with
0.2 mm contact offsets on 10 mm parts may differ from CPU. If they disagree, isolate the cause by restarting with:

- `--envs 1 --device cuda:0`: GPU physics, no copies. Differs from S1? Then it's GPU vs CPU physics.
- `--envs 64 --device cpu`: copies on CPU physics (slow). Differs from S1? Then it's the copying.

Then the contract v2 fields, against the stage 5 runs:

```bash
B=sim/sim_server/scripts/batches
python3 sim/sim_server/scripts/send_batch.py $B/stock_cube_transport.json --transport none --out runs/s2_in_hand_64.json
python3 sim/sim_server/scripts/send_batch.py --compare runs/s4_in_hand.json runs/s2_in_hand_64.json
python3 sim/sim_server/scripts/send_batch.py $B/mesh_l_bracket.json --grid --out runs/s2_mesh_grid_64.json
python3 sim/sim_server/scripts/send_batch.py --compare runs/s4_mesh_grid.json runs/s2_mesh_grid_64.json
python3 sim/sim_server/scripts/send_batch.py $B/stock_cube_transport.json --out runs/s2_cube_transport_64.json
python3 sim/sim_server/scripts/send_batch.py --compare runs/s4_cube_transport.json runs/s2_cube_transport_64.json
for f in 15 none; do
  python3 sim/sim_server/scripts/send_batch.py $B/heavy_block_grip_force.json --grip-force $f --out runs/s2_force_${f}_64.json
  python3 sim/sim_server/scripts/send_batch.py --compare runs/s4_force_$f.json runs/s2_force_${f}_64.json
done
for t in slow normal fast; do
  python3 sim/sim_server/scripts/send_batch.py $B/heavy_block_grip_force.json --grip-force 21 --transport $t --out runs/s2_transport_${t}_64.json
  python3 sim/sim_server/scripts/send_batch.py --compare runs/s4_transport_$t.json runs/s2_transport_${t}_64.json
done
```

`--compare` judges held and held after transport exactly (same target as above), and reports the in-hand differences
over the grasps both runs held as median / max per field. Target **[guess]**: median under 0.1 mm and 0.5°, max under
0.5 mm and 2°; record what you get. Each response's `sim` block should differ only in `envs` and `device`. Things that
only the GPU path exercises: `set_max_efforts` with torch tensors (the jaw limits live on the CPU in PhysX's tensor API;
Isaac copies them), mesh-part hulls under the GPU's 64-vertex limit, and the part orientations coming back as torch
tensors (converted by `_numpy`).

Throughput: from each run's `Batch done ... grasps/s` log line, fill in the table below for the 81-point stock grid (and a
bigger batch, e.g. 8 designs, where copies pay off). Watch `nvidia-smi` for memory. Raise `--envs` until grasps/s stops
improving or something breaks.

Filled in on the GB10 (2026-10-20, [log](../experiments/2026-10-20-gb10-stages-4-6.md)): stock cube grid, then the
243-grasp flat-pad grid where it ran.

| Path | Flags | GPU | Grasps | Seconds | Grasps/s | Re-parse s | Agreement with S1 |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| reference | `--envs 1` | (CPU) | 81 | 29.5 | 2.75 | 0.3 | (baseline; two runs agree 77/81) |
| GPU, 1 copy | `--envs 1 --device cuda:0` | GB10 | 81 | 120 | 0.68 | – | 76/81 (93.8%) |
| copies on CPU | `--envs 64 --device cpu` | (CPU) | 81 | 16.7 | 4.9 | – | 77/81 (95.1%) |
| vectorised | `--envs 64` | GB10, 4.9 GB | 81 / 243 | 5.0 / 13.0 | 16.1 / 18.7 | 1.2–1.9 | **72–74/81 (88.9–91.4%)**, biased: holds 67 vs 58–60 |
| vectorised | `--envs 256` | GB10, 4.8 GB | 81 / 243 | 5.3 / 8.8 | 15.2 / 27.6 | 3.7 | 69/81 (85.2%) |

Observed on the GB10: **the GPU path runs without any of the errors below, but it doesn't match the reference.**

- With 64 or 256 copies it holds about 9 more of 81 cube grasps than the reference, and repeats exactly (81/81,
  162/162). GPU physics alone and copies on CPU each match the reference within its own noise. So the bias comes from
  the two together; CCD (next list) is the first suspect.
- The L-bracket grid disagrees with the reference on every path (70–84%). Its reference grid was run only once.
- In-hand readings, transport and the heavy-block outcomes agree (all 3/3 or 18/18), except the μ 0.9 block (1/3 vs 3/3).

Until the bias is found, use `--envs 64 --device cpu` (about 5 grasps/s) for results that matter, and the GPU path for
exploring.

Things that may break on the GPU path, and what to try:

- PhysX errors about GPU buffers (found/lost pairs, contact or patch counts): raise `GPU_CAPACITIES` in `sim_server/clients/isaac.py`.
- `AssertionError` on `is_homogeneous` when designs are mixed in a chunk: the articulation view won't mix copies with
  different collider counts. Then chunks need one finger design each (a change to `chunk_grasps` in `services/batches.py`); report it.
- `slots_to_envs` errors at startup: the views didn't report body positions after reset; report the message.
- Different results only on the GPU: CCD isn't enabled on the GPU path (the twin enables it on CPU), and the GPU limits
  convex hulls to 64 vertices.

## 7. End to end with the app

On Brev the app can do this whole stage itself: with `COMPUTE_BACKEND=brev`, its GPU panel starts the instance, the sim
server and the forward, and stops the instance when idle ([app/README.md](../../app/README.md#gpu-from-the-app)). By
hand, it goes like this.

Server on the GPU machine (whichever path passed), app on a laptop. The server listens on 127.0.0.1 only; reach it
through an SSH tunnel, **never by exposing the port publicly**:

```bash
brev port-forward <instance> --port 9000:9000      # local:remote; keep it running
curl -s http://127.0.0.1:9000/health
export SIM_BACKEND=http SIM_URL=http://127.0.0.1:9000 SIM_TIMEOUT_S=1800   # base URL; the app appends /evaluate_batch
uv run --package backend uvicorn api.main:app --port 8000
```

On the GB10, start the server detached with `--port 9011` (0.2, step 5) and tunnel to it from the laptop, on the MSOE VPN:

```bash
ssh -N -L 9000:127.0.0.1:9011 hackathon11@spark1.ai.msoe.edu   # keep it running; the app still uses 127.0.0.1:9000
```

On Windows, put `SIM_BACKEND`, `SIM_URL` and `SIM_TIMEOUT_S` in the repo-root `.env` instead of exporting them.

Start with a small job (a budget of about 16 designs) and watch the server log for `Batch done` lines; run a full
128-design job only after that one finishes. Set `SIM_TIMEOUT_S` from the batch times measured above. Results from the
app are real twin results only if the server log shows the batches; label everything else as mock.

## 8. What to record per run

One experiment file per session in [../experiments/](../experiments/README.md) (the `log-experiment` format), failures
included, plus a row in its index:

- date, people, `git rev-parse --short HEAD`, server flags, part and designs (the batch file), offsets (file or `--grid`);
- GPU (`runs/gpu.txt`), Isaac Sim version, instance type, wall time, credits (Brev console: run time × rate);
- held counts per design with Wilson 95% intervals, the held maps, `--compare` agreement, grasps/s, re-parse times;
- for contract v2 runs: the grip force and transport sent, held-after-transport counts, the in-hand readings (stage 5.1's
  table, and the median / max differences from `--compare`), and the friction and force sweeps as tables;
- where the raw files are (`runs/*.json`, `runs/*.log` on the instance, or copied back). Don't commit `runs/`.

Copy results back before stopping: `brev copy <instance>:/home/ubuntu/<repo>/runs/s1_stock_grid.json .` **[guess: brev
copy also works in this direction, as the organizers' tutorial shows for videos]**.

## 9. Stop the instance

Stop it from the Brev console (Compute → the instance → **Stop**), or `brev stop <instance>` **[guess]**. Stopping keeps
the disk (small storage cost); delete only when nothing on it is needed. Run `brev refresh` after a restart so SSH finds
its new address.

On the GB10, stop the sim server when you're done (`kill -INT "$(cat ~/repo/runs/sim_server.pid)"`, or `sim_stop`), so
it doesn't hold GPU memory other teams need. Copy results back with
`scp hackathon11@spark1.ai.msoe.edu:repo/runs/<file> .`.
