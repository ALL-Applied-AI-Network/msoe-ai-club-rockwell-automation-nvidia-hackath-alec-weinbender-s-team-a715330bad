---
date: 2026-10-20
kind: sim
owner: Matt
git_commit: 945d3a6 (the app on the laptop; the GB10's sim/ a git archive of it, plus the close-up framing committed after)
---

# The app end to end on the MSOE GB10 (stage 7), and the first Isaac Sim clips

Real twin (Isaac Sim), **not** the mock. Reference path only: one environment, CPU physics.

## Question

Does the whole app work against a real GPU? That covers four steps (GPU test plan stage 7):

1. Connect the GB10 from the app.
2. Run an experiment on the Isaac sim.
3. Get the results back.
4. Film grasps of the result in Isaac Sim (the new clips).

## Setup

- **Compute:** MSOE GB10 (`spark1`), over the MSOE VPN. Isaac Sim 6.0.1 (aarch64 pip install), sim server on uvicorn
  0.29.0. `imageio-ffmpeg` 0.6.0 installed into Isaac's Python with `--no-deps` (its own aarch64 ffmpeg 7.0.2; Isaac's
  pins unchanged). No other team's processes on the GPU. About 14:38 to 17:30 CDT.
- **App:** the API on the laptop with `SIM_BACKEND=http`, `SIM_URL=http://127.0.0.1:19000`, `COMPUTE_BACKENDS=gb10`,
  `SIM_GRASPS_PER_S=2.75`, and its own data directory. The GPU session forwarded the GB10's port 9011 to 19000.
- **Experiment EXP-0001:**

  | Setting | Value |
  | --- | --- |
  | Part | `cad/manipbench-cube-10mm.step` (10 × 10 × 10 mm), PLA, resting pose 0 |
  | Grasp | The first auto proposal |
  | Fingers | V-pad with every parameter locked (a single design): pad width 9 mm, flat (groove 180°, depth 0), slack 3 mm, tip height 3.5 mm, lead-in 2 mm |
  | Baselines | Stock and imprint |
  | Camera error | The "calibrated" preset with σ 1 mm and yaw σ 0, so no yaw layers |
  | Grids | Search: 81 points. Final: 321 |
  | Size | 1,206 grasps planned: 3 designs × 81, then 3 × 321 |

- **Clips:** 1280 × 720, both views (`closeup`, `side`), 30 fps.

## Results

**Connecting from the app:** 33 s from Connect to Connected. The app's start script launched Isaac, opened the forward,
and the session was ready.

**The experiment** (resumed run, below): round 0 in about 82 s, the final test in about 5 min 25 s, done at 17:25:48.
That's 2.95 grasps/s on the search grid and 3.0 on the final grid. 95% Wilson intervals on the held fraction of each
grid:

| Design | Grid | Held | Rate (95% CI) | Success at σ 1 mm | Capture radius |
| --- | --- | ---: | --- | --- | --- |
| Locked V-pad | search | 61/81 | 75.3% (64.9–83.4%) | 1.000 | 6.0 mm |
| Stock | search | 58/81 | 71.6% (61.0–80.3%) | 1.000 | 5.0 mm |
| Imprint | search | 52/81 | 64.2% (53.3–73.8%) | 0.890 | 0.0 mm |
| **D1** (the locked V-pad) | final | 243/321 | 75.7% (70.7–80.1%) | 0.99999994 | 5.0 mm |
| **STOCK** | final | 224/321 | 69.8% (64.5–74.5%) | 0.9999991 | 4.5 mm |
| IMP | final | 215/321 | 67.0% (61.7–71.9%) | 0.907 | 1.0 mm |

- **Stock on the search grid** held 58/81, as in the GB10 bring-up's first grid.
- **At σ 1 mm** D1 and stock both score about 100%: the error is small next to a 10 mm cube. The 0.5 mm of extra capture
  radius is inside the noise at the capture edge (CONTEXT.md, risk 5).
- **This was a pipeline check,** not a finger comparison.

**Recording, directly against the sim server** (stock, cube, centre):

- The server started in 9 s.
- Two recordings took 6.8 s and 6.5 s, held both, with 147 frames (4.9 s) each.
- H.264 High at 1280 × 720, about 2.1–2.9 MB per view.
- The first close-up framing put the cube on the bottom edge and cut off the lift. It was raised (the eye 15 cm up,
  looking down at 7 cm, framing 32 cm), and the second try kept the grasp and the lift in frame.

**Clips through the app** (4 asked for, all ready in 50 s, about 12 s each including each worker's start):

| Clip | Design | Offset (mm) | This recording | Stored result | Agree |
| --- | --- | --- | --- | --- | --- |
| 1 | D1 | (0, 0) | held | held | yes |
| 2 | STOCK | (0, 0) | held | held | yes |
| 3 | D1 | (−9.24, −3.83), 10 mm out | missed | held | **no** |
| 4 | D1 | (2.10, 5.08), 5.5 mm out | held | missed | **no** |

- **The centre clips agree.** The two edge points flipped, one each way. Clip 3 sits in the landing-capture zone (8–12 mm
  along the jaw axis, risk 5), where the stored "held" was probably a finger pushing the cube into the gap. The frames
  show clip 3's fingers coming down beside the cube and lifting away empty.
- **Clips can't settle edge outcomes.** A single recording can't say which outcome near the edge is right, and
  `matches_result` flags exactly this case.

## Failures observed

1. **The first attempt's job worker died silently,** between 14:45:12 and 14:46:33.
   - The GB10 finished round 0 meanwhile (243 grasps, 81.8 s, 2.97 grasps/s), but its reply was never sent: the worker's
     connection was already gone.
   - There's no traceback in the worker log and no Windows crash record, and the laptop was awake.
   - The job sat at "running" until the API was restarted, which marked it interrupted. Resume then ran it to the end,
     with the worker alive throughout.
   - **Suspected cause:** the Claude Code sandbox the test API ran in. Stopping that API killed every process under it,
     detached children included, which a normal terminal doesn't do. Not confirmed. A person running the API in their
     own terminal hasn't seen this.
2. **The laptop slept for 1 h 40 min** (lid closed, Modern Standby from 15:19 to 17:00). The GPU session's forward
   dropped. On wake, the session reconnected by itself within a minute, as designed.
3. **Launching the API outside the sandbox** with WMI (`Win32_Process.Create`) started a process that exited at once,
   without logging. Not pursued.
4. **The mat's printed texture is missing on the GB10** (`assets/mat_print.png`; render only, `make_mat_texture.py`
   makes it). The clips show a plain white table.

## Artifacts

- **Laptop:** `runs/gb10-app-e2e-2026-10-20/` (gitignored).
  - the app database (`app.db`), the API, worker, session and forward logs;
  - the job's outputs;
  - `clips/` (the 4 clips' mp4s and frame grabs);
  - `clip_spike/` (the direct recordings and server log).
- **GB10:** `~/repo/runs/clip_spike/` and `clip_spike_v1/` (the first framing); `~/repo/runs/sim_server.log`, the app
  session's server. `~/repo/sim.bak-20261020` is the sim copy from before this session. The sim server was stopped
  afterwards, and nothing of ours is left running.

## Next

- **Watch for the silent worker death** in a normal terminal. If it ever happens there, the worker needs a heartbeat,
  so the API can mark a vanished worker without a restart.
- **Make the mat texture on the GB10,** so clips show the real mat.
- **Pick clip offsets for the demo** away from the landing-capture zone, and away from the capture edge, unless the
  point is to show the edge.
- **Rerun stage 7 at a larger σ and with free parameters,** once landing capture is handled (risk 5), so D1 and stock
  differ by more than noise.
