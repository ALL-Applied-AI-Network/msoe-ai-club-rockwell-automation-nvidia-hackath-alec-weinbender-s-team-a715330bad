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
