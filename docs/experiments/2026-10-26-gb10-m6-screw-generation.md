---
date: 2026-10-26
kind: sim
owner: Oliver Grudzinski (run by Claude Code from his laptop)
git_commit: 4c9269f (laptop backend and the GB10's ~/repo; the laptop had only uncommitted docs)
---

# M6 screw, generation job EXP-0001 in Isaac on the GB10

## Question

Does a generated V-pad finger beat the stock fingers and the imprint on the M6 × 30 countersunk screw (drop into the
bin) in the real twin, at the cell's placeholder grasp accuracy of 3 mm and 8°? This is the first Isaac run on the
screw, the first on the unbiased CPU-copies path (`--envs 64 --device cpu`, risk 7), and the first since the shank
section grasp was added.

## Setup

- **Part:** `cad/ISO10642-M6x30-countersunk-screw.step`, uploaded as part `462813aae16e`, steel, 7.47 g (computed),
  friction 0.4 / 0.3 against the pad. One pose: lying on its side (trimesh likelihood 0.951; standing on an end, 0.049,
  not covered). Simulated as 16 convex pieces.
- **Grasp:** the top proposal, across the shank: 90°, centre (−1.458, 0) mm, span (−16.561, 9.939) mm, section
  6.0 mm wide.
- **Task:** drop, no transport. **Cell:** UWM CSI cell v1 (SMC MHZL2-16D2 mount from the STEP).
- **Search:** one V-pad BO search, budget 128, 12 Sobol starts, batch 4, patience 12. Free: pad width, slack, tip
  height, lead-in (no groove for this part).
- **Baselines:** STOCK (the twin's blades) and IMP (the imprint), in round 0 and in the final test.
- **Error model:** the cell's grasp accuracy, the "typical" preset: σ 3 mm per axis and 8° in yaw, no bias. It's a
  placeholder (risk 3).
- **Grids:**
  - Search: rings 1–8, 10 and 12 mm × 8 directions × yaw −12 / 0 / +12°, 243 offsets.
  - Final: 20 rings 0.5–12 mm × 16 directions × the same 3 yaws, 963 offsets.
  - Seed 0.
- **Sim:**
  - Isaac Sim 6.0.1 (aarch64 pip wheels) on the MSOE GB10, driver 580.178.04.
  - `-m sim_server --port 9011 --envs 64 --device cpu`, started by hand after updating `~/repo` to `4c9269f`.
  - `/health`: TGS, 16 / 2 solver iterations, dt 1/60 s, contact offset 0.2 mm, `jaw_max_force_n` 180.
  - No other GPU processes and no other logins at the start. The hosted app's GPU session was connected but idle.
- **Backend:** the laptop (Windows), BoTorch 0.18.1, torch 2.14.1+cpu, CadQuery 2.8.0. It reaches the sim through the
  app's GB10 session (ssh forward to 127.0.0.1:9000).

## Results

Final dense grid, 963 offsets each. "Predicted" is the expected success under the 3 mm / 8° model: the grid points'
probabilities summed over the held ones. The point counts and their Wilson intervals are only for reference. The grid
points aren't random draws, so the Wilson interval is not a confidence interval on the prediction.

| Design | Grid points | Held | Held share (95% Wilson) | Predicted at 3 mm / 8° | Capture radius | Notes |
| --- | ---: | ---: | --- | ---: | ---: | --- |
| STOCK | 963 | 735 | 76.3% (73.5–78.9) | **87.2%** | 0 mm | The twin's blades |
| D1 | 963 | 753 | 78.2% (75.5–80.7) | 85.9% | 0 mm | Sobol start #4: pad 15.9, slack 5.38, tip 2.38, lead-in 0.23 mm |
| D2 | 963 | 750 | 77.9% (75.2–80.4) | 82.5% | none (misses the centre at some yaw) | BO: pad 19.9, slack 5.5, tip 1.76, lead-in 0 |
| D3 | 963 | 741 | 76.9% (74.2–79.5) | 82.4% | 0 mm | BO: pad 19.9, slack 5.5, tip 1.0, lead-in 0 |
| IMP | 963 | 678 | 70.4% (67.4–73.2) | 78.1% | 0 mm | The imprint |

**Success vs σ** (the results view's curves; same stored outcomes, yaw σ 8° throughout):

| σ (mm) | 0.5 | 1 | 2 | 3 | 4 | 5 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| STOCK | 95.2 | 95.1 | 92.2 | 87.2 | 79.8 | 70.9 |
| D1 | 94.8 | 92.3 | 90.1 | 85.9 | 79.7 | 72.3 |
| IMP | 89.7 | 86.5 | 83.7 | 78.1 | 71.9 | 64.8 |

**Headline:**

- In the twin at 3 mm / 8°, the generated finger does **not** beat the stock fingers: 85.9% against 87.2%.
- D1 only draws level at about 4 mm and is ahead by 1.4 points at 5 mm. That's inside the run-to-run noise (below).
- Both beat the imprint by about 8 points.

**Time:**

- 1436 s (24 min) from start to finish, against the plan's estimate of 7281 s.
- The estimate assumed the full 128-design budget at the configured 5 grasps/s. The run actually measured:
  - round 0: 14 designs, 3,402 grasps in 531.5 s (6.4 grasps/s);
  - round 1: 4 designs in 153.2 s (6.3 grasps/s);
  - the final test: 4,815 grasps in about 733 s (6.6 grasps/s).

## Failures observed

- **The search stopped after 16 of its 128 designs**, by patience:
  - The best design came early in the Sobol starts (the 3rd of 12, 0.851 on the search grid).
  - `SearchPlan.stop_reason` (`app/backend/src/api/models/search_plan.py`) counts every design after the best as
    stale, including the Sobol starts. So 9 Sobol + 4 BO designs reached patience 12 after the first BO batch.
  - BO proposed only 4 designs, so **this is not a converged optimisation**, and "D1 loses to stock" is not yet a
    conclusion about the V-pad family.
- **Every design's capture radius is 0 mm, or none:** each misses some point on the 0.5 mm ring at one of the ±12° yaw
  layers. The first miss for D1 is at 0.5 mm.
- **D1 and STOCK hold different points, interleaved:**
  - Of the 963 offsets, D1 holds 137 that STOCK misses, and STOCK holds 119 that D1 misses.
  - These are often adjacent: D1 holds (−1.77, −1.77) mm and STOCK misses it, while STOCK holds (−2.47, −2.47) and D1
    misses it.
  - That looks like the edge-flip noise in risk 5 (about 9% of points flip between runs on the cube). The gap between
    D1 and STOCK is smaller than that.
  - Measured afterwards in [EXP-0002](2026-10-26-gb10-m6-screw-evaluation.md): stock re-simulated on the same grid
    agrees with this run on only 77.5% of points, so the D1–STOCK difference is noise.
- **D1 misses most toward −x**: 64 of 132 points in that direction, from 2.5 mm out. Its failure breakdown is in the
  results view's `failures`.
- **Not checked:** whether a finger landing on the screw counts as a hold (risk 5), and height error, which the grid
  doesn't test.

## Artifacts

- **App database:** `app/data/app.db` on Oliver's laptop. Job `372a39276d` (EXP-0001) and part `462813aae16e`.
  - Results: `GET /api/jobs/372a39276d/results`.
  - Trials: `GET /api/export/trials.jsonl?job_id=372a39276d`.
- **D1's CAD:** STEP, STLs and the print sheet in `app/data/outputs/372a39276d/` (gitignored). The export checks
  passed with no blocking failures.
- **Clips:** clips 1–5, D1 / STOCK / IMP at the centre and D1 / STOCK at (0, −5) mm, under
  `GET /api/jobs/372a39276d/clips`.
- **GB10:** `~/repo/runs/sim_server.log` (this start). The previous code is kept in `~/repo-fd6fbdd-20261026`.
  - Its `clients/isaac.py` differed from `main` only in CRLF line endings: `runs/isaac_py_replaced_20261026.diff` is
    1,238 lines, and `diff --strip-trailing-cr` is empty.

## Next

- **Fix the patience count** so it starts after the Sobol phase, then rerun EXP-0001. That's about 2 h at about
  6.4 grasps/s if the full budget runs. Only then compare the families.
- **Repeat the final test of D1 and STOCK** (or the whole job) to measure the screw's repeatability on this path,
  before claiming any gap of a few points.
- Height error and landing capture: see the step 5 proposal (CONTEXT.md open questions).
