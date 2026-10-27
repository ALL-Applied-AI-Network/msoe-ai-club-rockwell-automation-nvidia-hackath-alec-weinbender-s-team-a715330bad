# Experiment log

The organizers and judges want **measured results against a baseline**, and "a video alone does not show reliability".
Log every simulation batch and every physical trial session here, including failures.

- One file per experiment: `YYYY-MM-DD-short-name.md` (use the `log-experiment` skill or copy the template below).
- Large outputs (videos, run directories, DB dumps) stay out of git. Record where they live instead.
- Physical trials: record **every attempt**, not only the successful ones.

## Index

| Date | Experiment | Kind | Headline result |
| --- | --- | --- | --- |
| 2026-10-20 | [Sim server bring-up on Brev, stages 0–3](2026-10-20-brev-sim-server-bringup.md) | sim (real twin) | Stock cube held 1/1, 10/10 and 56–61/81 on the grid; 2.1 grasps/s after fixing a uvloop crash; outcomes beyond 5 mm not repeatable |
| 2026-10-20 | [Sim server bring-up on the MSOE GB10, 0.2 and stages 1–3](2026-10-20-gb10-sim-server-bringup.md) | sim (real twin) | Isaac Sim 6.0.1 from aarch64 pip wheels; stock cube 1/1, 10/10, 58–60/81; agrees with Brev 92.6–96.3% (as well as each agrees with itself); 2.8 grasps/s |
| 2026-10-20 | [The app end to end on the GB10 (stage 7), and the first clips](2026-10-20-gb10-app-end-to-end-and-clips.md) | sim (real twin) | Connect, a real experiment (1,206 grasps in about 7 min, ~3 grasps/s) and 4 Isaac Sim clips all work through the app; clips take ~7 s on the GPU; 2 of 4 clips at edge points disagree with the stored result, one each way |
| 2026-10-20 | [Stages 4–6 on the GB10: custom fingers, contract v2, GPU path](2026-10-20-gb10-stages-4-6.md) | sim (real twin) | Swaps work but landing capture makes tight and loose pads score alike; the twin grips at only ~2.5 N per jaw (heavy-block checks fail); 64 GPU copies run at 16–19 grasps/s but hold ~9/81 more than the reference; CPU copies match it at ~5 grasps/s |
| 2026-10-26 | [M6 screw, generation job EXP-0001 in Isaac on the GB10](2026-10-26-gb10-m6-screw-generation.md) | sim (real twin) | At 3 mm / 8°, stock 87.2% vs generated D1 85.9% vs imprint 78.1% (963-point grid, `--envs 64 --device cpu`, 6.4 grasps/s). The search stopped by patience after 16 of 128 designs (Sobol starts count as stale), so it isn't converged; D1 draws level at about 4 mm |
| 2026-10-26 | [M6 screw, library evaluation EXP-0002, and repeatability](2026-10-26-gb10-m6-screw-evaluation.md) | sim (real twin) | Stock 88.6% ranks above the imprint 76.0% (495 s). Stock re-simulated on the same 963-point grid agrees with EXP-0001 on only 77.5% of points (flips 3% within 2 mm, 40% beyond 6.5 mm); D1 vs stock differ no more than stock vs itself. [Success-vs-σ chart](2026-10-26-screw-success-vs-sigma.png) |

## Template

```markdown
---
date: YYYY-MM-DD
kind: sim | physical | perception | other
owner: <name>
git_commit: <short sha the run used>
---

# <Short name>

## Question
What are we trying to learn? What result would change our plan?

## Setup
- Part / object:
- Finger design(s): (template + params, or file)
- Baseline: (e.g. stock fingers, imprint design)
- Simulator / twin version, Isaac Sim version, physics settings:
- Randomization: (camera error sigma mm / deg, seeds, n grasps per design)
- Model versions: (LLM, perception model)
- Compute: (Brev instance type, GB10, local)

## Results
| Design | Attempts | Successes | Rate (95% CI) | Notes |
| --- | ---: | ---: | --- | --- |

## Failures observed
What failed, how, and what we think caused it.

## Artifacts
Where outputs live (paths, not the files themselves).

## Next
```
