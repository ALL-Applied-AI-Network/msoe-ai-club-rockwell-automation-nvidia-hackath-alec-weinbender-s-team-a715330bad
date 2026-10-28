---
title: Noise-aware optimizer comparison pilot
source: Benchmark code, offline tests and GB10 pilot artifacts
author: Team working notes
received: 2026-10-27
date: 2026-10-27
kind: sim
git_commit: 64c94a7 with local benchmark changes; server marker 121b55d
---

# Noise-aware BO, Sobol and GA comparison

## Question and implementation

Can the benchmark avoid choosing a lucky single-run finalist and avoid wasting its finalist slots on duplicate geometry?
The team's screw experiments document noisy outcomes and a search/dense-score gap. This change adds distinct-geometry
finalists and selection on repeated-grid means. Final comparisons use three new holdout repeats after selection, rather
than the observations used to pick a winner. It also adds the unchanged 16 mm cube case.

No production algorithm, API, database schema, robot policy or submission file was changed for this experiment.
Existing benchmark configurations default to one selection repeat; the new cube16 configurations request three.

## Bounded pilot

The GB10 was idle at preflight: queue 0, CPU physics, 64 environments, GPU utilization 0%, no logged-in users listed.
No server configuration or lifecycle change was made.

```text
.venv/Scripts/python.exe app/backend/scripts/benchmark.py app/backend/scripts/benchmarks/cube16-pilot.json --backend http --sim-url http://127.0.0.1:9000 --output app/data/benchmarks/cube16-noise-pilot-20261027
```

- Part: original `cad/manipbench-cube-16mm.step`, PLA assumption, material-derived mass, pose 0, valid 0-degree grasp.
- Same initial 12 Sobol designs, 14-candidate budget, seed 0 and batch schedule [12, 1, 1] for each method.
- Three selection repeats for each distinct finalist and for stock/imprint; three independent repeats of every winner
  and baseline. Patience is recorded but does not stop the search.
- Search and selection grids: **center and +/-4 mm along the jaws, yaw zero only**. Upper bound: 276 submitted grasps.
  This is an implementation pilot, not a dense accuracy evaluation. No claim of beating the team's D1 follows.
- Landing capture is scored as a miss using the current task code. Returned landing measurements are recorded separately
  from submitted grasp counts, because stock-fit checks can skip physics entirely.
- Server: deployed archive marker 121b55d, `--envs 64 --device cpu`, average friction combine, reference settings recorded
  by preflight and each batch.
- Raw results: ignored `app/data/benchmarks/cube16-noise-pilot-20261027/`.
- Mock counterpart: ignored `app/data/benchmarks/cube16-noise-mock-20261027/`.

## Verification

- Initial focused benchmark suite: 18 passed in 63.73 seconds, including rejection of a lucky single-run winner,
  geometry deduplication, exact repeated-validation budgets, and cube16 pilot preparation.
- Final focused benchmark suite: **18 passed in 45.97 seconds**, including a regression that deliberately inflated
  selection scores never enter paired holdout comparisons.
- Ruff lint passes; format check reports **276 files already formatted**. Git whitespace checks pass.
- After the final report formatting/statistics changes, both reporting/holdout regression cases passed again
  (**2 passed, 16 deselected in 57.81 seconds**).

## Results

The real pilot completed in **249.52 seconds**, with 92 saved observations, 42 searched candidate designs,
**276 submitted grasp requests** and **255 returned landing measurements**. The 21 missing measurements correspond
to the seven stock-baseline grids: the 16 mm cube fails the server's stock-fit check, so those are synthetic misses.
All three methods produced actual proposals after the common initialization, with zero BO fallback batches.

| Method | Distinct finalists | Selection repeats per finalist | Independent holdout repeats | Pilot holdout score |
| --- | ---: | ---: | ---: | ---: |
| Existing batch BO | 3 | 3 | 3 | 0.864665 |
| Sobol | 3 | 3 | 3 | 0.864665 |
| Genetic | 3 | 3 | 3 | 0.864665 |

**There is no method win in this pilot.** Every winning design succeeds at all three tested offsets. The value
0.864665 is the probability mass covered by the sparse grid under the assumed error model, not an 86.5% full-grid
accuracy estimate. The imprint also succeeds at those three points, which illustrates how little a sparse grid can
say about full capture behavior. Stock returns zero from the fit check. Across-seed variation is not estimable from
one seed; zero observed variation across the three holdout repeats does not establish noise-free physics elsewhere.

The mock counterpart completed in **11.33 seconds** and is labeled MOCK PILOT throughout. Its role is software validation.
Reports were re-rendered from unchanged raw observations after presentation fixes; `report-renderer.json` records the
renderer hash. SVG artifacts parse as valid XML. No submission or robot-policy files changed.

## Interpretation and next experiment

The code now rejects a lucky single-grid winner in the synthetic noise regression, preserves distinct geometry in
finalist slots, and keeps selection observations out of the reported paired comparison. This is an improvement in
result reliability, not a demonstrated increase in robot success. Production selection is unchanged.

The pilot's effective submitted throughput is about 1.1 grasps/s, much lower than the assumed 5 grasps/s estimate:
tiny batches do not fill 64 environments, and request/setup overhead matters. Do not extrapolate its timing or scores
to a full campaign. A reportable optimizer comparison still needs the standard grid, several seeds, repeated selection,
fresh holdouts and an agreed compute budget. The cube16 smoke/comparison configurations provide those inputs, but were
not launched automatically. Existing team D1 results remain the reference until such a comparison supports a change.
