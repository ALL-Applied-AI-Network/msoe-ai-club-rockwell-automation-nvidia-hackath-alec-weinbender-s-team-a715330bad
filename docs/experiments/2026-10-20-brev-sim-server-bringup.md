---
date: 2026-10-20
kind: sim
owner: Matt
git_commit: 7a34916 plus uncommitted fixes (see Setup: which code each run used)
---

# Sim server bring-up on Brev: GPU test plan stages 0–3

Real twin (Isaac Sim), **not** the mock. Reference path only: one environment, CPU physics, stock fingers.

## Question

Does `sim/sim_server` run in Isaac Sim at all, does the stock cube grasp hold, are the offsets applied with the right
signs, are results repeatable, and how fast is the reference path? (Stages 0–3 of
[the GPU test plan](../notes/gpu-test-plan.md).) A failure here blocks every real-twin result.

## Setup

- **Compute:** Brev, NVIDIA's Isaac launchable ([isaac-launchable](https://github.com/isaac-sim/isaac-launchable) v1.7),
  AWS g7.2xlarge: RTX PRO 4500 Blackwell Server Edition (32 GB), 8 vCPUs, 32 GiB RAM, driver 595.71.05, $3.07/hr.
  Instance created 00:54 CDT; stopped about 01:40 CDT, so about 45 minutes billed, roughly $2.30 (exact figure: Brev
  Billing tab).
- **Isaac Sim:** 6.0.1 (`VERSION`: `6.0.1-rc.7+release.42383.32955d8d.gl`) in the launchable's `vscode` container at
  `/isaac-sim`; Isaac's Python 3.12.13, numpy 2.5.1, torch 2.10.0+cu128 with CUDA available. Robot USD from the Isaac 6.0
  asset root (`.../Isaac/6.0/Isaac/Robots/Fanuc/er4ia/er4ia.usd`).
- **Sim server:** `--envs 1`, device cpu, `friction_combine` average, physics_dt 1/60 (2 steps per control frame, 30
  frames/s), solver TGS, part solver iterations 16/2, robot 32/1, contact offset 0.2 mm, rest offset 0, jaw limit 180 N,
  nominal site (0.30, 0.0), jaws closing along base +Y. `pip install -e sim/sim_server` into Isaac's Python added only
  uvicorn and its extras; nothing Isaac bundles was replaced.
- **Code each run used:** commit `7a34916` for the first server (runs `s1_stock_cube`, `s1_offsets_a/b`, the failed
  cylinder and grid). Then `7a34916` + the `loop="asyncio"` fix in `sim_server/__main__.py` (`s1_cylinder`,
  `s1_stock_grid`, `s1_offsets_c_fixed`, the sign check and dx sweeps, `s1_stock_grid_b`). Then + the cylinder in-hand fix
  in `robot/poses.py` (`s1_cylinder_fixed`, `s1_offsets_d`). Both fixes are uncommitted as of this log.
- **Parts:** the twin's cube, 10 × 10 × 10 mm, 4 g (`stock_cube*.json`); a lying cylinder, 10 mm diameter × 20 mm long,
  3 g, axis across the jaws (`stock_cylinder_lying.json`). Twin's part friction (0.9 / 0.8). No grip-force limit, no
  transport.
- **Fingers:** stock only (the twin's hooked SMC fingers; the stock grasp rule: tips 2.5 mm up, each jaw 0.3 mm past
  where its hook meets the part). No custom fingers yet (stage 4).
- **Offsets:** `stock_cube_offsets.json` (centre, dx ±1/±2/+3, dy ±2, yaw ±15°), `--grid` (the app's 81 points: centre
  plus rings at 1–8, 10, 12 mm, 8 directions, yaw 0), and a dx sweep −12..+12 mm in 1 mm steps (dy 0, yaw 0).
- **Twin checks:** `bash bootstrap.sh` on the VM: 33 host tests OK, textures made. `build_scene.py --headless` in the
  container: exit 0 in 59 s, DOFs J1–J6, jaw_l, jaw_r, scene saved. Cosmos stacking run skipped (no Cosmos env; not needed
  by the sim server).

## Results

Stock fingers, real twin, reference path. 95% Wilson intervals.

| Run | Part | Attempts | Held | Rate (95% CI) | Notes |
| --- | --- | ---: | ---: | --- | --- |
| `s1_stock_cube` | cube, centre | 1 | 1 | 100% (20.7–100%) | Stage 2 pass condition (`stock held 1/1`) |
| `s1_offsets_a` | cube, 10 offsets | 10 | 10 | 100% (72.2–100%) | Before the uvloop fix |
| `s1_offsets_b` | cube, 10 offsets | 10 | 10 | 100% (72.2–100%) | Agrees 10/10 with a; in-hand max diff 0.18 mm, 0.65° |
| `s1_offsets_c_fixed` | cube, 10 offsets | 10 | 10 | 100% (72.2–100%) | After the fix: agrees 10/10 with a, 13.6× faster |
| `s1_cylinder` | lying cylinder, 10 offsets | 10 | 9 | 90% (59.6–98.2%) | dy −2 mm dropped; tilt read 9–92° (roll, see Failures) |
| `s1_cylinder_fixed` | lying cylinder, 10 offsets | 10 | 9 | 90% (59.6–98.2%) | Same outcomes; tilt now 1.7–3.9°, one real tumble (85°) |
| `s1_stock_grid` | cube, 81-point grid | 81 | 56 | 69.1% (58.4–78.1%) | Every direction held out to 5 mm |
| `s1_stock_grid_b` | cube, 81-point grid | 81 | 61 | 75.3% (64.9–83.4%) | Agrees 74/81 (91.4%) with the first grid |
| `s1_dx_sweep` | cube, dx −12..+12 | 25 | 24 | 96.0% (80.5–99.3%) | Only dx −7 dropped |
| `s1_dx_sweep_b` | cube, dx −12..+12 | 25 | 24 | 96.0% (80.5–99.3%) | Agrees 23/25; −7 and −8 swapped |

Held maps (columns: 8 directions from +dx, toward JawL, through +dy; `#` held, `.` dropped):

```text
             grid a      grid b
centre       #           #
r = 1..5 mm  ########    ########
r = 6 mm     ####.###    ########
r = 7 mm     #.#...##    ..######
r = 8 mm     #.......    #...#...
r = 10 mm    #.......    #...#...
r = 12 mm    #...#...    #...#...
```

**Sign check (stage 2): pass.** With DEBUG logging, dx +1, +2, +3 mm put the cube at base y +1, +2, +3 mm and JawL
closes toward base +Y; dy +2 mm put it at base x 0.298 (G's y is base −X with this spread); yaw ±15° gave part yaw 105°
and 75° against a nominal 90°. Offsets are applied as the contract defines them.

**In hand (cube):** dx ≈ +0.3 mm, dz ≈ −1.27 mm on every held grasp; dy offsets read back with their sign (+2 → +1.97,
−2 → −2.06); dx offsets are centred by the jaws (≤ 0.4 mm); yaw ±15° reads ±4–5° with stock fingers. The dz offset is
above the runbook's 0.5 mm guide for stage 5.1.

**Throughput (reference path, cube):** 2.1 grasps/s after the uvloop fix (81-point grid in 38 s, 10 grasps in 4.7 s);
0.12–0.24 grasps/s before it. A part change (the stage edit for the cylinder) added about 3 s.

## Failures observed

1. **Every stage edit failed with HTTP 500** (the cylinder, then the grid): `RuntimeError: There is no current event loop
   in thread 'MainThread'` from `uvloop`, raised in Kit's `omni.behavior.scripting` handler on USD changes
   (`RemovePrim`, `XFormPrim.set_local_poses`). Cause: `uvicorn[standard]` installs uvloop, and uvicorn's default
   `loop="auto"` then sets uvloop's event-loop policy for the whole process, so Kit's asyncio calls on the main thread find
   no loop. **Fixed** by `loop="asyncio"` in `sim_server/__main__.py`; the server must be restarted afterwards (the failed
   edit leaves the stage half changed). The same fix made the reference path 13.6× faster on identical results.
2. **A lying cylinder's roll read as tilt** (9–92°), because tilt was measured from the part's z axis, which a cylinder
   rolling about its own axis turns. `Task.success` checks tilt for insert tasks, so round parts would have failed
   inserts they pass. **Fixed** in `robot/poses.py`: a cylinder's tilt and yaw follow its own axis (25 new host tests).
   After the fix one grasp (dx +1 mm) still reads tilt 85°, yaw −34°, dz −4.7 mm in both runs: the cylinder stood up in
   the jaws, a real tumble.
3. **Outcomes beyond about 5 mm are not repeatable.** Inside 5 mm every repeat agreed 100%; the two grids disagreed at 7
   of 81 points and the two dx sweeps at 2 of 25. The first grid looked asymmetric in dx; the sign check and the second
   grid (symmetric) show that was this noise, not a frame error. Scores near a design's capture edge carry noise.
4. **Captures from 8–12 mm along the jaw axis.** The stock fingers "held" the cube placed 8–12 mm off along dx, outside
   the 16 mm open tip gap, and the cube ended centred in the hand. Most likely a finger came down on the cube and the
   position-controlled descent squeezed it into the gap. A real arm may knock it away instead, so this probably flatters
   the stock baseline. Not yet decided how to treat it (see Next).
5. Setup snags (fixed or worked around): the twin's `.sh` files are not executable in git (now staged `100755`);
   `brev refresh` is needed before `ssh <instance>`; `assets/mat_print.png` is missing (render only).

## Artifacts

- Laptop: `runs/brev-2026-10-20/` (gitignored): `vm/` (every `send_batch.py --out` JSON, `gpu.txt`), `container/`
  (sim server logs `sim_server_s1*.log`, `pip_install.log`), `twin/` (`bootstrap.log`, `build_scene.log`).
- Brev instance `isaac-launchable-1e8a9b` (stopped): `~/repo` on the VM and `/root/repo` in the `vscode` container,
  including `runs/scene.usd`.

## Next

- Commit the two fixes and the script modes, then start the next session from that commit.
- Decide how to treat a part disturbed before the jaws close (finger landed on it): count it as a miss, or flag it. Then
  read the part's pose at the end of the descent and implement it.
- Stage 4 (custom flat pads, finger-swap time), stage 5 (contract v2, including the 1.27 mm dz), stage 6 (`--envs 64`,
  agreement with these runs, throughput).
- Confirm that a stop/start keeps the container, the repo and the install (expected from the disk layout).
