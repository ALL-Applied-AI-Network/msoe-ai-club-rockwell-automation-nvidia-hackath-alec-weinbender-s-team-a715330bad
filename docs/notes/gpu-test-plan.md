---
title: GPU test plan for the sim server (grasp evaluation in the FANUC ER-4iA twin)
source: our own runbook, written alongside sim/sim_server (POST /evaluate_batch)
author: Alec Weinbender's Team
received: 2026-10-19
kind: note
status: DRAFT, no step has been run yet
---

# GPU test plan: sim server

The sim server's grasp loop (`sim/sim_server`) was written on a Windows laptop **without Isaac Sim**. Only its host tests
have run (`uv run pytest sim/sim_server/tests`: models, frames, units, packing, the IK plan, the batch bookkeeping
against a fake cell, the routes, the layering). Nothing about physics,
the Isaac API calls, or GPU behaviour is validated until this runbook has been worked through. Go in order: each stage
assumes the previous one passed. Commands marked **[guess]** haven't been checked against the instance.

Background: [sim/README.md](../../sim/README.md#sim_server) (flags, contract, the gripper frame G, what a grasp is).

## 0. Before you start

- Machine: Brev **Isaac Sim launchable**, RTX PRO 6000 preferred, L40S as fallback (about $3/hr), or the MSOE GB10.
  The twin was validated upstream on Linux + Isaac Sim 6.0 + RTX A6000. The GB10 is ARM64; check that its Isaac Sim build
  runs the twin before spending time there **[guess: Isaac Sim's GB10 / DGX Spark support]**.
- Note the start time; Brev bills while the instance runs. Keep a terminal open on the instance with `tmux`, so a dropped
  SSH session doesn't kill the server.
- Get the repo onto the instance: `git clone` (needs repo access) or, from the laptop,
  `brev copy /path/to/repo.zip <instance>:/home/ubuntu` (the same syntax the organizers' tutorial uses for the twin).
- `brev shell <instance>` opens a shell in the launchable's container; add `--host` for the host machine.

## 1. Setup and environment check

```bash
cd ~/<repo>                                  # the repo root; every command below runs from here
mkdir -p runs                                # gitignored
ls -d /isaac-sim /isaacsim ~/isaacsim 2>/dev/null   # [guess] where the launchable keeps Isaac; the twin defaults to /isaacsim
export ISAAC=/isaac-sim                      # whichever directory holds python.sh
nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv | tee runs/gpu.txt
cat "$ISAAC/VERSION" 2>/dev/null | tee runs/isaac_version.txt   # [guess] file name
"$ISAAC/python.sh" -c "import numpy, torch; print(numpy.__version__, torch.__version__, torch.cuda.is_available())"
```

The vectorised path needs `torch` with CUDA in Isaac's Python (it's the tensor backend for GPU physics). If the last command
fails, the reference path still works; note it and skip stage 5.

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

Wait for `Grasp cell ready` and uvicorn's `Uvicorn running on http://127.0.0.1:9000`. Check the `Grasp cell ready` line:
the DOFs must include `J1`..`J6`, `jaw_l` and `jaw_r`, and the jaws should close along `(0.0, 1.0)` or `(0.0, -1.0)`. A
`RuntimeError` about the gripper layout or missing `.../Collision` means the twin's `cell.py` differs from what
`sim_server/clients/isaac.py` expects.

From a second shell (`tmux` split, or `brev shell` again):

```bash
curl -s http://127.0.0.1:9000/health          # {"status": "ok", "queued": 0, "envs": 1, "device": "cpu", ...}
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

Sign check for dx: restart with `--log-level DEBUG` and send `stock_cube_offsets.json` again. On the reference path every
grasp logs one `Env 0: part centre ...` line, in offset order; the sixth (dx = +3 mm) must sit 3 mm from the first along the
logged `JawL toward` direction.

## 3. S1 grid: the app's 81 offsets, stock fingers

```bash
python3 sim/sim_server/scripts/send_batch.py sim/sim_server/scripts/batches/stock_cube.json --grid --out runs/s1_stock_grid.json
```

`--grid` sends the app's default grid (centre plus rings at 1..8, 10, 12 mm, 8 directions, yaw 0) and prints a held map,
one row per ring, columns going round from +dx (toward JawL) through +dy. Copy the map into the experiment log. It should
be symmetric under dx → −dx and dy → −dy; an asymmetric map points at a frame or sign error. Note the batch time: with D
designs, a reference-path batch takes about D × 81 × (seconds per grasp), and the app's `SIM_TIMEOUT_S` must exceed it.

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

## 5. S2: vectorised path, and agreement with the reference

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

Throughput: from each run's `Batch done ... grasps/s` log line, fill in the table below for the 81-point stock grid (and a
bigger batch, e.g. 8 designs, where copies pay off). Watch `nvidia-smi` for memory. Raise `--envs` until grasps/s stops
improving or something breaks.

| Path | Flags | GPU | Grasps | Seconds | Grasps/s | Re-parse s | Agreement with S1 |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| reference | `--envs 1` | (CPU) | 81 | | | | (baseline) |
| GPU, 1 copy | `--envs 1 --device cuda:0` | | 81 | | | | |
| vectorised | `--envs 64` | | 81 | | | | |
| vectorised | `--envs 256` | | 81 | | | | |

Things that may break on the GPU path, and what to try:

- PhysX errors about GPU buffers (found/lost pairs, contact or patch counts): raise `GPU_CAPACITIES` in `sim_server/clients/isaac.py`.
- `AssertionError` on `is_homogeneous` when designs are mixed in a chunk: the articulation view won't mix copies with
  different collider counts. Then chunks need one finger design each (a change to `chunk_grasps` in `services/batches.py`); report it.
- `slots_to_envs` errors at startup: the views didn't report body positions after reset; report the message.
- Different results only on the GPU: CCD isn't enabled on the GPU path (the twin enables it on CPU), and the GPU limits
  convex hulls to 64 vertices.

## 6. End to end with the app

Server on the GPU machine (whichever path passed), app on a laptop. The server listens on 127.0.0.1 only; reach it
through an SSH tunnel, **never by exposing the port publicly**:

```bash
brev port-forward <instance> --port 9000:9000      # local:remote; keep it running
curl -s http://127.0.0.1:9000/health
export SIM_BACKEND=http SIM_URL=http://127.0.0.1:9000 SIM_TIMEOUT_S=1800   # base URL; the app appends /evaluate_batch
uv run --package backend uvicorn api.main:app --port 8000
```

Run a small optimizer job and watch the server log for `Batch done` lines. Set `SIM_TIMEOUT_S` from the batch times
measured above. Results from the app are real twin results only if the server log shows the batches; label everything
else as mock.

## 7. What to record per run

One experiment file per session in [../experiments/](../experiments/README.md) (the `log-experiment` format), failures
included, plus a row in its index:

- date, people, `git rev-parse --short HEAD`, server flags, part and designs (the batch file), offsets (file or `--grid`);
- GPU (`runs/gpu.txt`), Isaac Sim version, instance type, wall time, credits (Brev console: run time × rate);
- held counts per design with Wilson 95% intervals, the held maps, `--compare` agreement, grasps/s, re-parse times;
- where the raw files are (`runs/*.json`, `runs/*.log` on the instance, or copied back). Don't commit `runs/`.

Copy results back before stopping: `brev copy <instance>:/home/ubuntu/<repo>/runs/s1_stock_grid.json .` **[guess: brev
copy also works in this direction, as the organizers' tutorial shows for videos]**.

## 8. Stop the instance

Stop it from the Brev console (Compute → the instance → **Stop**), or `brev stop <instance>` **[guess]**. Stopping keeps
the disk (small storage cost); delete only when nothing on it is needed. Run `brev refresh` after a restart so SSH finds
its new address.
