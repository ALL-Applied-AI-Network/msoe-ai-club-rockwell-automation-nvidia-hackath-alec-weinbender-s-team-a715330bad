---
date: 2026-10-27
kind: sim
owner: Oliver Grudzinski (run by Claude Code from his laptop)
git_commit: 121b55d (the GB10's ~/repo and the laptop backend)
---

# 16 mm cube: the library can't grip it, a generated finger can

## Question

On the M6 screw, the stock fingers were already close to the best this gripper can do, so a generated finger had little
to win ([log](2026-10-26-gb10-landing-check-and-screw-reruns.md)). Does the library-first flow show its value on a part
the stock fingers can't take? The 16 mm cube is on the real cell, and it's as wide as the stock tips open.

## Setup

- **Part:** `cad/manipbench-cube-16mm.step` (16 mm, 1 mm edge radius), part `e3513b0ab7c4`.
  - **Material set to PLA** (5.03 g), an assumption: the cell docs don't say what the cubes are made of. Friction
    against the printed pad is 0.5 / 0.4.
  - One resting pose, standing (likelihood 1.0).
- **Grasps** (the app's proposals):
  - g0: across the faces, 90°;
  - g1: across the faces, 0°;
  - g2: across the diagonal, 136°, 21.8 mm wide.
  - Every proposal warns that "the stock fingers open at most 16 mm, so the stock baseline will score 0".
- **Task:** drop. **Cell:** UWM CSI cell v1. **Error model:** 3 mm / 8°, a placeholder. **Landing rule on** (1 mm / 3°).
- **EXP-0005, the library evaluation:** the stock fingers (FNG-0001), and FNG-0002, which is EXP-0001's imprint of the
  **screw**. It was the only other finger in the library. It can't reach the g2 position.
- **EXP-0006, generation:** V-pad at g0. Budget 128, 12 Sobol starts, batch 4, patience 12. Search grid 243 offsets,
  final grid 963.
- **Sim:** the GB10, `-m sim_server --port 9011 --envs 64 --device cpu`, the same server as the screw's reruns.
  - The two jobs started together at 10:06 and shared the sim until EXP-0005 finished at 10:22.
  - No other users or GPU processes.

## Results

### EXP-0005: the library can't grip the cube

| Rank | Finger | Predicted at 3 mm / 8° | Per grasp (search grid) |
| --- | --- | ---: | --- |
| 1 | FNG-0002, the screw's imprint | 17.6% | g0 18.5%, g1 18.5%, g2 can't reach |
| 2 | FNG-0001, stock | **0%** | 0 at every grasp |

- **Stock isn't simulated at all.** The sim server's fit check skips a part as wide as the open stock tips (16 mm), so
  every grasp counts as dropped. That's a geometric 0, not a physics result. The real tips measured 15 ± 2 mm open
  (risk 8), so on the arm they'd land on the cube or crush it, not grip it.
- **1,231 of 1,384 grasps the sim held count as misses**, because a finger landed on the cube first. The screw imprint
  mostly lands on the cube.
- **Time:** 15 min, against an 8 min estimate. It shared the sim with EXP-0006.

### EXP-0006: generation finds a finger that grips it reliably

Final dense grid, 963 points, landing rule on:

| Design | Predicted at 3 mm / 8° | Held | Capture radius | Params |
| --- | ---: | ---: | ---: | --- |
| **D1** | **92.3%** | 749 | **4.5 mm** | pad 19.2, slack 5.5, tip 1.0, lead-in 0 mm |
| D2 | 92.3% | 748 | 4.5 mm | the same |
| D3 | 92.2% | 750 | 4.5 mm | pad 16.0, slack 5.5, tip 1.0, lead-in 0 mm |
| Imprint (the cube's own) | 27.2% | 167 | none | |
| Stock | 0% | 0 | none | not simulated (too wide) |

Success vs σ (yaw σ 8°): [chart](2026-10-27-cube16-success-vs-sigma.png), [CSV](2026-10-27-cube16-success-vs-sigma.csv).

| σ (mm) | 0.5 | 1 | 2 | 3 | 4 | 5 | 6 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| D1 | 97.6 | 97.6 | 97.0 | 92.3 | 83.6 | 73.4 | 63.3 |
| Library best (FNG-0002) | 39.7 | 36.5 | 24.7 | 17.6 | 13.9 | 11.7 | 10.2 |
| Stock | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

- **D1 holds every grasp out to 4.5 mm of error, at every yaw.** At 0.5–1 mm it scores 97.6%, which is the grid's
  coverage limit (2.4% of the yaw mass lies past its ±12° layers), so effectively all of it.
- **D1–D3 score within 0.03 points of each other.** They're three slightly different designs on one grid, so the
  cube's results are far less noisy than the screw's.
- **The imprint scores only 27.2%.** It's moulded tight around the cube, so its fingers land on it. A part's exact
  shape isn't a good finger.
- **The search ran 28 designs and stopped on patience.** Its best came in round 3 (92.3% on the search grid), and 12 BO
  designs after it didn't beat it.
- **Time:** 1,955 s (33 min) in all, against a 5,780 s estimate made for the full budget. Rounds took about 157 s alone
  and 307 s while sharing the sim.
- **2,767 of 10,208 held grasps across the job's final test count as misses** (landings), most of them the imprint's.
- **D1's CAD:** exported with the SMC mount (STEP plus an STL per side). The export checks pass, and the download isn't
  blocked.

## Failures observed

- None in the runs.
- **Assumption:** PLA, because the cube's material is unknown. A heavier cube would be gripped at the twin's weak
  2.5 N (risk 6). At 5 g that's no concern.
- **The stock 0% comes from the fit check, not physics.** Whether real stock tips at 16 mm could catch a 16 mm cube
  with its 1 mm edge radius is for the arm to answer. The tips are 15 ± 2 mm (risk 8), so likely not.
- **The pad sits at the stroke limit again:** slack 5.5 mm, the maximum. The cube is just wide enough that every pad
  must open wider than the stock tips. The optimizer gets there by offsetting the pads, not by more stroke.

## Artifacts

- **App database:** `app/data/app.db` on Oliver's laptop. EXP-0005 is `ac6c020607`, EXP-0006 is `aaf38cd0b9`, and the
  part is `e3513b0ab7c4`.
- **D1's CAD:** `app/data/outputs/aaf38cd0b9/cube16_isaac_2026-10-27_EXP-0006_D1*` (gitignored).
- **Clips 9–11:** `app/data/outputs/aaf38cd0b9/clips/` (gitignored), closeup and side views. D1 at the centre, D1 at
  dx 4 mm, and IMP at the centre. All held, matching their stored results.
  - A clip's outcome is the sim's raw hold. `/record_grasp` doesn't report a landing, so it doesn't apply the landing
    rule.
  - The sim server refused clip 12, STOCK at the centre ("the open stock tips are 16.0 mm apart: there's no grasp to
    film"). That's the same fit check that scores stock 0.
- **GB10:** `~/repo/runs/sim_server.log`.

## Next

- **For the demo and the pitch,** the cube shows the full flow: the library (stock and an old finger) fails, the engineer
  asks for a finger, and generation finds one at 92% with a 4.5 mm capture radius. The screw shows the other half of the
  case: when the stock fingers are good enough, Auto-Grasp says so and nothing gets printed.
- **To validate it on the arm:**
  - print D1 for the cube, after the review gate and after confirming the jaw mount (risk 1);
  - run it at commanded offsets against the stock fingers, expecting stock 0;
  - add the cube to `cell_policy` (its policy is built for the screw now).
- **Measure the cube's material and mass** at the cell.
