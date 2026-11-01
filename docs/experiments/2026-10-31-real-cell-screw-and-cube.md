---
date: 2026-10-31
kind: physical
owner: Alec Weinbender's Team (logged by Claude Code from the cell's results page and the client's rollout log)
git_commit: ea4baad (this repo, with uncommitted cell_policy changes); ff7534e (the client clone, with uncommitted policy.py)
---

# First real-cell session: the M6 screw with stock fingers, the 16 mm cube with printed D1

## Question

Do the sim's predictions hold on the real FANUC ER-4iA cell? Two runs, each 10 rollouts at commanded grasp offsets
(`cell_policy/`):

- **The screw with the stock fingers.** The baseline the generated screw finger has to beat.
- **The cube with the printed EXP-0006 D1.** The sim says stock can't grip it (0%) and D1 holds every grasp out to
  4.5 mm ([log](2026-10-27-gb10-cube16-library-and-generation.md)).

## Setup

- **Cell:** the organizers' FANUC ER-4iA with the SMC MHZL2-16D2 gripper, run through hackathon.sidclab.org. `tcp`
  actions, cameras table, side and wrist. The operator scored each rollout success or failure.
- **Policy:** `cell_policy/policy.py`, a blind scripted top-down pick. Each rollout's prompt tag sets the commanded grasp
  offset. The part and the bin go in the same place every rollout, so the operator's placement error is the same in
  every rollout.
- **Run 1, screw** (`r20261031-ffbf97`, request q86eb04, policy `CAD2Fingers-Screw-Stock`, 13:10–13:28 CDT):
  - Part: the M6 screw, head at (420, −40) mm, yaw 90°. Bin at (480, 120).
  - Fingers: the stock aluminium fingers.
  - Offsets: dx = 0, ±1.5, ±3, ±4.5, ±6, 0 mm; dy = 0, yaw 0.
- **Run 2, cube** (`r20261031-ce75fc`, request q14d8a2, policy `CAD2Fingers-Cube16-EXP-0006-D1`, 13:50–14:01 CDT):
  - Part: the 16 mm cube, centre at (420, −40) mm. Bin at (480, 120). Fingertips close 2.5 mm above the table.
  - Fingers: EXP-0006 D1, printed in PLA, engraved EXP-0006-D1-L and -R, bolted on with two M3 × 10 per jaw.
  - Offsets: dx ±2, ±4 mm; dy ±4 mm; yaw ±12°; and two at the centre.
- **Not run:** the stock fingers on the cube (their tips open about 16 mm, the cube's width, so they'd come down on
  it), and a printed finger on the screw.
- **Randomization:** none beyond the commanded offsets and the operator's placement. One attempt per offset.

## Results

| Run | Fingers | Scored | Successes | Rate (95% Wilson) | Sim prediction | Mean cycle | Faults / interventions |
| --- | --- | ---: | ---: | --- | --- | ---: | --- |
| Screw | Stock | 10 of 10 | 4 | **40%** (16.8–68.7%) | 63–67% at 3 mm / 8°, 81–87% at 0.5 mm (EXP-0003/0004, landing rule) | 30.4 s | 0 / 0 |
| Cube | Printed D1 | 8 of 10 | 7 | **87.5%** (52.9–97.8%) | every grasp held at these offsets (EXP-0006) | 20.9 s | 1 / 1 |

Rates, intervals and cycle times are as the results page computes them.

### Screw, stock fingers, every rollout

| Rollout | Trial | dx (mm) | Result | Notes |
| --- | --- | ---: | --- | --- |
| R01 | t00 | 0 | success | started twice (13:10, 13:11); one scored |
| R02 | t01 | +1.5 | fail | |
| R03 | t02 | −1.5 | fail | |
| R04 | t03 | +3 | success | |
| R05 | t04 | −3 | success | |
| R06 | t05 | +4.5 | fail | |
| R07 | t06 | −4.5 | fail | |
| R08 | t07 | +6 | fail | started three times (13:20, 13:27, 13:28); the scored one is episode 13 |
| R09 | t08 | −6 | fail | started twice (13:23, 13:25) |
| R10 | t09 | 0 | success | |

By distance from the aimed point: 0 mm 2/2, 1.5 mm 0/2, 3 mm 2/2, 4.5 mm 0/2, 6 mm 0/2.

- **Measured 40% is below the sim's stock numbers.** These aren't the same quantity: the sim's are averaged over a
  Gaussian error in x, y and yaw, and these are 10 fixed offsets along one axis averaging 3 mm. Still, the sim's per-point
  stock rate within 2 mm of the centre was about 81–87% with the landing rule, and the real arm scored 2 of 4 there.
- **Not monotone in the offset.** Both ±1.5 mm grasps failed and both ±3 mm grasps held. With one attempt per offset
  that may be chance, or the snug socket the sim showed the screw brushing against (risk 10).
- **Nothing past 3 mm held.** In the sim the stock fingers still hold most grasps out to 3–5 mm along the closing
  direction (the 12 mm face gap around a Ø6 shank).

### Cube, printed D1, every rollout

| Rollout | Trial | Offset | Result | Notes |
| --- | --- | --- | --- | --- |
| R01 | t00 | centre | **not scored** | ran 13:50 per the client log; no score on the results page |
| R02 | t01 | dx +2 mm | **not scored** | ran 13:53; no score |
| R03 | t02 | dx −2 mm | success | started twice (13:55, 13:56) |
| R04 | t03 | dx +4 mm | success | |
| R05 | t04 | dx −4 mm | success | |
| R06 | t05 | dy +4 mm | success | |
| R07 | t06 | dy −4 mm | success | |
| R08 | t07 | yaw +12° | **fail** | controller fault and operator intervention |
| R09 | t08 | yaw −12° | success | |
| R10 | t09 | centre | success | |

- **Every scored grasp at a position offset held**, out to 4 mm in x and y. That matches the sim, which holds every
  grasp to 4.5 mm.
- **The one miss came with a controller fault and an intervention,** at +12°, the grid's outermost yaw layer. The
  results page records no notes, so whether the fingers or the motion caused it is unknown.
- **The interval (52.9–97.8%) contains the sim's ~97–100%** for these offsets. Eight rollouts can't show more than that.
- **The printed mount worked.** D1 bolted to the real jaws with the TCP unchanged, and no fingertip touched the table
  (CONTEXT.md risks 1 and 9).

### Jaw measurements

The policy's jaw-yaw readings at r = 0 were 89.999–90.155° on the screw (14 starts) and 89.69–90.11° on the cube
(11 starts). They agree with the mock runs (89.96°), as the README's first-real-run check asked.

## Failures observed

- **Screw, 6 of 10 missed** with the stock fingers, at ±1.5, ±4.5 and ±6 mm. How each failed (knocked away, closed
  beside the shank, dropped in transport) isn't recorded on the results page. TODO: from the videos or the team's notes.
- **Cube R08 (+12° yaw), a fault and an intervention.** TODO: what faulted, and why.
- **Cube R01 and R02 have no score.** The client logged both, but the run shows 8 of 10 trials and isn't marked
  complete. TODO: were they aborted, and if they ran, what happened?
- **Re-runs:** screw R01, R08 and R09, and cube R03, were started more than once. Only one attempt per trial is
  scored. TODO: why they were re-run, and what the earlier attempts did.

## Artifacts

- **Scores and videos:** the team's private results page, from `uv run run.py --status` in the client clone. The
  request files are `PhysicalAI-Hackathon-2026/.request.q86eb04-screw-stock.json` (screw) and
  `.request.q14d8a2-cube-d1.json` (cube). They're private; don't commit them.
- **Recorded data:** `uv run run.py --download` fetches the LeRobotDataset for the run in `.request.json`.
- **The client's rollout log:** `PhysicalAI-Hackathon-2026/cad2fingers_rollouts.jsonl`, one line per start, with the
  commanded offset and the jaw readings.
- **Submissions:** `cell_policy/submission/screw-stock/` and `cell_policy/submission/cube-d1/`.
- **Request q4cba21** (the 2026-10-29 stock submission) was approved as `r20261031-29112a`, but has no rollouts.

## Next

- Fill in the TODOs above from the videos.
- **Compare per offset, not per σ:** pull the sim's held/landed outcome at exactly these offsets (yaw 0) from EXP-0003,
  EXP-0004 and EXP-0006, so measured and predicted are the same quantity.
- **The screw's printed-finger run** at the same offsets, so the stock 4/10 has something to compare against.
- **The stock fingers on the cube**, if the operator allows it, to confirm the predicted 0 on the arm.
