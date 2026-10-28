# Experiment log

The organizers and judges want **measured results against a baseline**, and "a video alone does not show reliability".
Log every simulation batch and every physical trial session here, including failures.

- One file per experiment: `YYYY-MM-DD-short-name.md` (use the `log-experiment` skill or copy the template below).
- Large outputs (videos, run directories, DB dumps) stay out of git. Record where they live instead.
- Physical trials: record **every attempt**, not only the successful ones.

## Index

| Date | Experiment | Kind | Headline result |
| --- | --- | --- | --- |
| 2026-10-27 | [Full-grid cube16 optimizer comparison, seed 0](2026-10-27-cube16-full-grid-comparison.md) | sim (real twin, complete) | 32 candidates/method: fresh holdout BO 92.31%, Sobol 91.18%, GA 91.04%; 2 h 49 min, one seed only; retrieved 2026-10-28 |
| 2026-10-27 | [Noise-aware optimizer comparison pilot](2026-10-27-noise-aware-benchmark.md) | sim (real twin, sparse pilot) | Repeated finalist selection and independent holdout scoring; bounded BO/Sobol/GA implementation check, not a full-grid accuracy comparison |
| 2026-10-27 | [GB10 access restored and local source sync](2026-10-27-gb10-access-and-sync.md) | sim (real twin) | Passwordless SSH and app GPU connection work; six landing-aware stock/imprint grasps passed on the CPU service; local main updated to 64c94a7 |
| 2026-10-22 | [BO/Sobol/genetic benchmark verification](2026-10-22-optimization-benchmark.md) | other (software/mock) | Cube smoke and screw quick completed; 23 targeted tests passed; full suite 905 passed and one existing timing-sensitive test failed, then passed alone |
| 2026-10-21 | [Windows local setup and mock optimizer verification](2026-10-21-windows-local-setup.md) | other (software/mock) | Live mock job completed BO rounds and CAD export after a Visual C++ runtime update; GB10 SSH still timed out |
| 2026-10-20 | [Sim server bring-up on Brev, stages 0–3](2026-10-20-brev-sim-server-bringup.md) | sim (real twin) | Stock cube held 1/1, 10/10 and 56–61/81 on the grid; 2.1 grasps/s after fixing a uvloop crash; outcomes beyond 5 mm not repeatable |
| 2026-10-20 | [Sim server bring-up on the MSOE GB10, 0.2 and stages 1–3](2026-10-20-gb10-sim-server-bringup.md) | sim (real twin) | Isaac Sim 6.0.1 from aarch64 pip wheels; stock cube 1/1, 10/10, 58–60/81; agrees with Brev 92.6–96.3% (as well as each agrees with itself); 2.8 grasps/s |
| 2026-10-20 | [The app end to end on the GB10 (stage 7), and the first clips](2026-10-20-gb10-app-end-to-end-and-clips.md) | sim (real twin) | Connect, a real experiment (1,206 grasps in about 7 min, ~3 grasps/s) and 4 Isaac Sim clips all work through the app; clips take ~7 s on the GPU; 2 of 4 clips at edge points disagree with the stored result, one each way |
| 2026-10-20 | [Stages 4–6 on the GB10: custom fingers, contract v2, GPU path](2026-10-20-gb10-stages-4-6.md) | sim (real twin) | Swaps work but landing capture makes tight and loose pads score alike; the twin grips at only ~2.5 N per jaw (heavy-block checks fail); 64 GPU copies run at 16–19 grasps/s but hold ~9/81 more than the reference; CPU copies match it at ~5 grasps/s |
| 2026-10-26 | [M6 screw, generation job EXP-0001 in Isaac on the GB10](2026-10-26-gb10-m6-screw-generation.md) | sim (real twin) | At 3 mm / 8°, stock 87.2% vs generated D1 85.9% vs imprint 78.1% (963-point grid, `--envs 64 --device cpu`, 6.4 grasps/s). The search stopped by patience after 16 of 128 designs (Sobol starts count as stale), so it isn't converged; D1 draws level at about 4 mm |
| 2026-10-26 | [M6 screw, library evaluation EXP-0002, and repeatability](2026-10-26-gb10-m6-screw-evaluation.md) | sim (real twin) | Stock 88.6% ranks above the imprint 76.0% (495 s). Stock re-simulated on the same 963-point grid agrees with EXP-0001 on only 77.5% of points (flips 3% within 2 mm, 40% beyond 6.5 mm); D1 vs stock differ no more than stock vs itself. [Success-vs-σ chart](2026-10-26-screw-success-vs-sigma.png) |
| 2026-10-26 | [The landing check in Isaac, and the M6 screw rerun with it](2026-10-26-gb10-landing-check-and-screw-reruns.md) | sim (real twin) | The landing readout works (stage 4 passes: pads push the cube by offset minus slack). An untouched screw moves 0, but the stock fingers brush it in ~37% of grasps, differently each run. The reference path is no more repeatable (81.1%), so the cause is the part. With landings as misses, stock drops to 63.4% and the imprint to 49.1% (EXP-0003); the patience-fixed search ran 32 designs (EXP-0004), and on the final grid stock 66.9% beats D1 62.9%, which only matches or leads it past 4.5 mm of error, within noise. [Chart with the landing rule](2026-10-26-screw-success-vs-sigma-landing.png) |
| 2026-10-27 | [16 mm cube: the library can't grip it, a generated finger can](2026-10-27-gb10-cube16-library-and-generation.md) | sim (real twin) | Stock 0% (as wide as its open tips), the best library finger 17.6% (EXP-0005); generated D1 92.3% at 3 mm / 8°, holding every grasp out to 4.5 mm, 97% up to 2 mm (EXP-0006, 28 designs, 33 min). D1–D3 agree within 0.03 points. [Chart](2026-10-27-cube16-success-vs-sigma.png) |

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
