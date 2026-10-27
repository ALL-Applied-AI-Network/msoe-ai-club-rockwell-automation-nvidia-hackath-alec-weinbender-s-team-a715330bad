---
date: 2026-10-26
kind: sim
owner: Oliver Grudzinski (run by Claude Code from his laptop)
git_commit: 4c9269f (laptop backend and the GB10's ~/repo; the laptop had only uncommitted docs)
---

# M6 screw, library evaluation EXP-0002 in Isaac on the GB10, and repeatability

## Question

The first evaluation job in Isaac. It ranks the finger library on the screw (story 12). Does the ranking agree with the
generation job, and how repeatable is one finger's score when it's simulated again?

## Setup

- **Part, pose, task, cell, error model and grids:** the same as
  [EXP-0001](2026-10-26-gb10-m6-screw-generation.md).
  - The screw lying on its side, drop, UWM CSI cell v1.
  - 3 mm / 8° (placeholder).
  - Search grid 243 offsets, final grid 963.
- **Library:** the cell had no fingers besides stock, and an evaluation needs at least one, so before this run
  EXP-0001's IMP design was added as FNG-0002 (`POST /api/jobs/372a39276d/designs/IMP/library`).
  - FNG-0001: stock fingers.
  - FNG-0002: "M6 screw imprint (EXP-0001 IMP)", generated in Isaac.
- **Grasps:** the part's top proposals.
  - g0: the shank section, 90°.
  - g1: the whole part, 0°, 30.6 mm wide. FNG-0002 is rejected there by the geometry checks (the jaws can't reach
    12.65 mm), and stock scores 0 (16 mm tips).
- **Sim:** the same server as EXP-0001, `--envs 64 --device cpu`, started 20:47.
  - The 5 clips for EXP-0001 were recorded between this job's batches.
- **Spec:** `poses` empty, `finger_ids` null, `error` null (the cell's).

## Results

Ranking, both fingers re-tested on the final grid at their best grasp (g0):

| Rank | Finger | Predicted at 3 mm / 8° | Capture radius | Final-grid points held |
| --- | --- | ---: | ---: | ---: |
| 1 | FNG-0001 stock | **88.6%** | 0.5 mm | 744 / 963 |
| 2 | FNG-0002 imprint | 76.0% | 0 mm | 664 / 963 |

**Time:** 495 s, against an estimate of 415 s (2,655 grasps at the measured 6.4 grasps/s). The clips were recorded in
between this job's batches.

**Repeatability.** Both jobs simulated the same finger at the same grasp on the same 963-point final grid. They're two
runs of the same thing:

| Finger | EXP-0001 | EXP-0002 | Points where both runs agree | Held in only one run |
| --- | ---: | ---: | ---: | ---: |
| Stock | 87.2% (735 held) | 88.6% (744 held) | 746 / 963 (77.5%) | 104 in EXP-0001 only, 113 in EXP-0002 only |
| Imprint | 78.1% (678 held) | 76.0% (664 held) | 707 / 963 (73.4%) | 135 / 121 |

- On this part and path, about **a quarter of the grid points flip between runs**. That's far worse than the cube on the
  GB10's reference path (91–95% agreement, 2026-10-20).
- **The flips grow with distance from the centre** (stock): 6 of 195 points within 2 mm (3%), 23 of 192 at
  2.5–4 mm (12%), 34 of 192 at 4.5–6 mm (18%), and 154 of 384 at 6.5–12 mm (40%).
- The flipped points carry 13% of the weight at 3 mm. They flip both ways, so the score moves only 1.4 points (2.1
  for the imprint).
- D1 and stock in EXP-0001 disagreed on 256 points (26.6%), the same as stock against itself (217, 22.5%). **In this
  twin the generated D1 and the stock fingers can't be told apart on this part.**
- The re-scores reproduce the stored scores at 3 mm exactly: D1 0.859, stock 0.872 / 0.886, IMP 0.781 / 0.760.

**Success vs σ.** Re-scored from the stored outcomes of both jobs, nothing simulated, yaw σ 8° throughout.
[CSV](2026-10-26-screw-success-vs-sigma.csv), [chart](2026-10-26-screw-success-vs-sigma.png):

| σ (mm) | 0.5 | 1 | 2 | 3 | 4 | 4.5 | 5 | 5.5 | 6 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Stock, EXP-0001 | 95.2 | 95.1 | 92.2 | 87.2 | 79.8 | 75.5 | 70.9 | 66.2 | 61.6 |
| Stock, EXP-0002 | 97.1 | 96.6 | 93.9 | 88.6 | 80.8 | 76.4 | 71.8 | 67.2 | 62.6 |
| D1 (EXP-0001) | 94.8 | 92.3 | 90.1 | 85.9 | 79.7 | 76.1 | 72.3 | 68.2 | 64.0 |
| Imprint, FNG-0002 (EXP-0002) | 90.5 | 88.6 | 82.0 | 76.0 | 70.1 | 66.8 | 63.3 | 59.6 | 55.8 |
| Grid coverage | 97.6 | 97.6 | 97.6 | 97.5 | 96.8 | 95.5 | 93.3 | 90.2 | 86.4 |

- **Where D1 overtakes stock:** at 4.5 mm against EXP-0001's stock run, and at 5.5 mm against EXP-0002's. Its lead
  is at most 2.4 points (at 6 mm), about the same as the gap between the two stock runs. So D1 doesn't clearly win at
  any σ.
- **Coverage:** the grid's rings reach 12 mm and its yaw layers ±12°. Error outside the grid counts as a miss: 2.4% of
  the yaw mass at every σ, and 13.6% in all at 6 mm. That lowers every curve alike.

## Failures observed

- **Poor repeatability** (above). Its cause is unknown. Candidates:
  - landing capture near the shank, where a finger touches the screw before the jaws close (risk 5);
  - the screw's 16-piece convex approximation;
  - which environment copy a grasp lands in (`--envs 64`).
  - To tell these apart: run the stock grid twice on `--envs 1`.
- **Clip 5** (stock at (0, −5) mm) held in the recording, though EXP-0001 stored a miss there: one more flip.
  Clips 1–4 matched their stored results.
- **The evaluation can't run on a library of only stock fingers** (`services/evaluations.py`), so its only other
  finger is the generation job's imprint. It's not a real factory library.

## Artifacts

- **App database:** `app/data/app.db` on Oliver's laptop, job `da030ef491`. Ranking: `GET /api/jobs/da030ef491/ranking`.
- **Clips:** `app/data/outputs/372a39276d/clips/{1..5}_{closeup,side}.mp4` (gitignored, about 4.9 s each).
  - 1: D1 at the centre, held.
  - 2: stock at the centre, held.
  - 3: IMP at the centre, held.
  - 4: D1 at (0, −5) mm, held.
  - 5: stock at (0, −5) mm, held, though its stored result is a miss.
- **The re-score and chart script:**
  `C:\Users\GRUDZI~1\AppData\Local\Temp\claude\c--Users-grudzinskio-School-Repos-msoe-ai-club-rockwell-automation-nvidia-hackath-alec-weinbender-s-team-a715330bad\b9e351d3-6fc1-4679-8632-fd5d6afd4711\scratchpad\sigma_curve.py`.
  It's a session scratch file: copy it into the repo if we keep it.
- **GB10:** `~/repo/runs/sim_server.log`.

## Next

- Measure repeatability on the reference path (`--envs 1`) for the stock fingers on the screw, so we know whether it's
  the vectorised path or the part.
- Until repeatability is understood, report D1 against stock as "no difference in the twin", not as a gain.
