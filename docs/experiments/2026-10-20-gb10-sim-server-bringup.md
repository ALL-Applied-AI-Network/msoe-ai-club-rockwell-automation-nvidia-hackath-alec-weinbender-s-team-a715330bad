---
date: 2026-10-20
kind: sim
owner: Matt
git_commit: fd6fbdd (a git archive of origin/main on the GB10, not a clone)
---

# Sim server bring-up on the MSOE GB10: GPU test plan 0.2 and stages 1–3

Real twin (Isaac Sim), **not** the mock. Reference path only: one environment, CPU physics, stock fingers. The same
batches as the [Brev bring-up](2026-10-20-brev-sim-server-bringup.md), compared against its saved results.

## Question

Can the free, shared GB10 run the twin and the sim server, and does it give the same answers as Brev? If it does, it
can take the long optimizer runs and save Brev credits. ([GPU test plan](../notes/gpu-test-plan.md): 0.2, then stages
1–3 on the GB10, interchangeable only if the stage 3 grids agree.)

## Setup

- **Compute:** MSOE GB10 `spark1.ai.msoe.edu`, team account `hackathon11`, over the MSOE VPN. NVIDIA DGX Spark: GB10
  (sm_121, 122 GiB visible to CUDA, memory shared with the CPU), 20 Arm cores, DGX OS 7.5 (Ubuntu 24.04), driver
  580.178.04, CUDA 13.0. Free. No other team's processes on the GPU during the runs. Session about 10:30–11:35 CDT.
- **0.2 check:** driver 580.x, so it passes (Isaac Sim 6.0 on DGX Spark needs R580). No sudo, no Docker access, no
  gcc-11, no git-lfs, so the source build in the runbook isn't possible from the team account.
- **Isaac Sim:** **6.0.1 from NVIDIA's aarch64 pip wheels** (`isaacsim[all,extscache]==6.0.1.0` from pypi.nvidia.com),
  not a source build. Installed in `~/isaac-sim-6.0.1/venv` on uv's standalone CPython 3.12.15. torch 2.11.0+cu130 was
  installed first, per NVIDIA's pip instructions. numpy 2.3.1. Install time about 5 minutes; 19 GB.
  `~/isaac-sim-6.0.1/python.sh` is our stand-in for Isaac's `python.sh`: it runs the venv's Python with
  `OMNI_KIT_ACCEPT_EULA=YES` and `LD_PRELOAD=/lib/aarch64-linux-gnu/libgomp.so.1`, so `ISAAC=~/isaac-sim-6.0.1` works
  with the repo's commands.
- **Sim server:** `pip install -e sim/sim_server` into that venv, then Isaac's pins restored (see Failures 2), so it runs
  on uvicorn 0.29.0. Flags `--port 9011` (the GB10's port), otherwise the defaults; the scene description matches Brev's
  exactly: `--envs 1`, cpu, friction average, physics_dt 1/60, TGS, part 16/2, robot 32/1, contact offset 0.2 mm, rest 0,
  jaw limit 180 N, site (0.30, 0.0), jaws close along base +Y. Started detached (`setsid nohup`, stdin `/dev/null`).
- **Code:** `fd6fbdd`, which includes both of Brev's fixes (`loop="asyncio"`, the cylinder in-hand angles). So the
  comparisons are against Brev's runs made after the fixes, where Brev has them.
- **Parts, fingers, offsets:** the same batch files as Brev. The twin's 10 mm cube and the lying 10 × 20 mm cylinder,
  stock fingers, `stock_cube_offsets.json` and the 81-point `--grid`.
- **Twin checks:** `bash bootstrap.sh`: 33 host tests OK on aarch64, textures made. `build_scene.py --headless`: exit 0,
  DOFs J1–J6, jaw_l, jaw_r, `runs/scene.usd` saved (7.6 MB). It took 159 s with cold caches, against 59 s on Brev; about
  137 s of that was the first `world.reset()`, most likely the RTX shader cache being built. Afterwards Isaac starts in
  about 8 s. Isaac's own log shows `NVIDIA GB10` on Vulkan with driver 580.178.04. The same 168 `SetEditTarget` USD
  warnings as on Brev.

## Results

Stock fingers, real twin, reference path. 95% Wilson intervals.

| Run | Part | Attempts | Held | Rate (95% CI) | Notes |
| --- | --- | ---: | ---: | --- | --- |
| `s1_stock_cube` | cube, centre | 1 | 1 | 100% (20.7–100%) | Stage 2 pass condition; in hand dx 0.29, dz −1.27 mm (Brev: the same) |
| `s1_offsets_a` | cube, 10 offsets | 10 | 10 | 100% (72.2–100%) | Agrees 10/10 with Brev's `s1_offsets_d` (in hand max diff 0.25 mm, 1.5°) |
| `s1_offsets_b` | cube, 10 offsets | 10 | 10 | 100% (72.2–100%) | Agrees 10/10 with a; in hand max diff 0.24 mm, 2.0° |
| `s1_cylinder` | lying cylinder, 10 offsets | 10 | 9 | 90% (59.6–98.2%) | dy −2 mm dropped, as on Brev; agrees 10/10 with Brev's `s1_cylinder_fixed` |
| `s1_stock_grid` | cube, 81-point grid | 81 | 58 | 71.6% (61.0–80.3%) | Every direction held out to 6 mm |
| `s1_stock_grid_b` | cube, 81-point grid | 81 | 60 | 74.1% (63.6–82.4%) | Agrees 77/81 (95.1%) with grid a; dropped dx +5 mm |
| `s1_signcheck` | cube, 10 offsets (DEBUG) | 10 | 10 | 100% (72.2–100%) | Sign check: pass (below) |

Held maps (columns: 8 directions from +dx, toward JawL, through +dy; `#` held, `.` dropped):

```text
             GB10 a      GB10 b      Brev a      Brev b
centre       #           #           #           #
r = 1..4 mm  ########    ########    ########    ########
r = 5 mm     ########    .#######    ########    ########
r = 6 mm     ########    ########    ####.###    ########
r = 7 mm     #.###.##    #.###.##    #.#...##    ..######
r = 8 mm     #.......    #...#...    #.......    #...#...
r = 10 mm    #.......    #...#...    #.......    #...#...
r = 12 mm    #.......    #...#...    #...#...    #...#...
```

**GB10 against Brev (stage 3's interchangeability check):**

| Compared | Agreement |
| --- | --- |
| GB10 a vs GB10 b | 77/81 (95.1%) |
| Brev a vs Brev b (from its log) | 74/81 (91.4%) |
| GB10 a vs Brev a / Brev b | 77/81 (95.1%) / 76/81 (93.8%) |
| GB10 b vs Brev a / Brev b | 75/81 (92.6%) / 78/81 (96.3%) |
| 10 offsets, GB10 a vs Brev d | 10/10 |
| Lying cylinder, GB10 vs Brev fixed | 10/10 |

The machines disagree with each other no more than each disagrees with itself. Every disagreement on either machine is
along the jaw axis (dx = −12 … +7 mm) or on a 7 mm diagonal. In-hand readings agree to a median of 0.00–0.09 mm and
0–0.2° over the grasps both held. **For the reference path, the GB10 and Brev are interchangeable.**

**Sign check (stage 2): pass, identical to Brev.** dx +1, +2, +3 mm put the cube at base y +1, +2, +3 mm with JawL
toward (0, 1); dy +2 mm put it at x 0.298 and dy −2 at 0.302; yaw ±15° gave part yaw 105° and 75°.

**Throughput (reference path, cube):** **2.75–2.8 grasps/s** (the 81-point grid in 29.2–29.5 s, 10 grasps in 3.6 s),
against 2.1 on Brev's RTX PRO 4500 instance. A part change (the cylinder's stage edit) took 0.3 s, against about 3 s on
Brev. Server start with warm caches: 8 s. A clean SIGINT shutdown took about 2 s.

## Failures observed

1. **The first Isaac install failed: the system Python has no headers.** `isaacsim-kernel` pins `psutil==5.9.8`, and
   `isaacsim-core` pins `PyOpenGL-accelerate==3.1.10`. Neither has an aarch64 wheel, so both build from source, which
   needs `Python.h`, and `python3.12-dev` isn't installed (no sudo to add it). **Fixed** by building the venv on uv's
   standalone CPython 3.12.15, which ships headers; both then built with the system gcc 13.
2. **Installing the sim server replaced Isaac's pinned packages.** `isaacsim-kernel` pins `uvicorn==0.29.0`,
   `websockets==12.0` and `httptools==0.6.1`; the sim server's `uvicorn[standard]>=0.30` upgraded all three. That didn't
   happen on Brev, because Isaac's bundled Python there doesn't carry them. **Fixed** by reinstalling the three pinned
   versions. The sim server only uses `uvicorn.Config(loop="asyncio")`, `Server`, `run()` and `should_exit`, which 0.29
   has. `pip check` now reports only the sim server's own `>=0.30` floor, plus a spurious "nvidia-cusparselt-cu13 not
   supported on this platform" (torch runs on CUDA regardless). Not changed in the repo.
3. **The first `build_scene.py` hung for 20 minutes.** It was started in tmux, so it had a terminal. The process sat in
   `futex_do_wait` at 0% CPU and 52 MB resident, and Kit never wrote its log; I killed it. A bare `SimulationApp`
   then started in 8.6 s, and the next build (foreground, stdin `/dev/null`, `stdbuf -oL`) succeeded in 159 s.
   **Not the terminal**, as found later the same day ([stages 4–6](2026-10-20-gb10-stages-4-6.md), Failures 4): a
   detached start hung the same way, and another segfaulted in NVIDIA's EGL/Vulkan start-up. Isaac's start-up on the
   GB10 fails intermittently, 3 of 12 starts that day; a retry has always worked.
4. **A dropped grasp at dx +5 mm** (grid b). Brev's log called outcomes inside 5 mm repeatable; on the GB10 the
   capture edge reaches dx = 5 mm along the jaw axis. In every other direction both machines agree through 6 mm.
5. Not reproduced: Brev's one cylinder tumble (dx +1 mm, tilt 85°); on the GB10 that grasp read tilt 1.2°. Seen again:
   `assets/mat_print.png` missing (render only).

## Artifacts

- Laptop: `runs/gb10-2026-10-20/` (gitignored). Every `send_batch.py --out` JSON, the sim server logs
  (`sim_server_s1.log`, `sim_server_s1_debug.log`), `build_scene.log`, `app_probe.log`, `bootstrap.log`, the Isaac
  install logs (both attempts), the pip logs, `gpu.txt`, `isaac_version.txt`.
- GB10: `~/repo/runs/` (the same files, plus Brev's results under `runs/brev/` for `--compare`),
  `~/repo/sim/fanuc_er4ia_sim/runs/scene.usd`, Isaac Sim in `~/isaac-sim-6.0.1/` (`install.sh`, `python.sh`, logs).
  The sim server is stopped; nothing of ours is left running on the GPU.

## Next

- Update the runbook's 0.2 for the pip-wheel install. It still says the wheels are x86-only and describes the source
  build, which needs sudo.
- Done the same day: stages 4–6 ([log](2026-10-20-gb10-stages-4-6.md)). The start-up hang turned out to be intermittent
  GPU start-up failures, not tmux. Whatever starts the server should retry after about 90 s without Kit's
  `Startup Complete`.
