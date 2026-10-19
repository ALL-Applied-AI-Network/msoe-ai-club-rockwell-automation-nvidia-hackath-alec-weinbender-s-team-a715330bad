---
name: log-experiment
description: Record a simulation batch, optimizer run, perception test or physical trial session in docs/experiments/ so results are reproducible and comparable against a baseline. Use when the user reports results ("we ran…", "got 34/40 grasps", "physical test today"), asks to log/record an experiment or trial, or after Claude itself runs a sim/optimizer job whose results matter.
---

# log-experiment

Judges require measured results against a baseline, and the dataset page says a video alone does not show reliability. Each
experiment gets one Markdown file in `docs/experiments/`.

## Steps

1. Create `docs/experiments/YYYY-MM-DD-short-name.md` from the template in `docs/experiments/README.md`.
2. Fill in what is known. Get facts from the user's message, the app (`app/data/app.db` or the `/api/jobs/<id>` and
   `/api/export/*.jsonl` endpoints), or the twin's run directory (`execution_report.json`, `sort_plan.json`,
   `perception_evaluation.json`). Record `git rev-parse --short HEAD`.
3. **Never fabricate numbers.** Leave a field as `TODO` and ask the user for anything missing that matters: the baseline,
   attempt counts, the randomization (camera error σ mm/deg, seeds), versions, and whether this was **mock sim, real twin, or
   physical**. Mock-simulator results must be labelled as mock.
4. Report success rates with attempts, successes and a 95% Wilson interval (`app/backend/src/api/services/optimizer.py::wilson` computes it).
   For physical trials, list **every attempt**, including failures and operator interventions.
5. Note where the large artifacts live (Brev path, shared drive). Don't commit videos or run directories.
6. Add a row to the index table in `docs/experiments/README.md` with a one-line headline result.
7. If the result changes the plan or answers an open question, update `CONTEXT.md` (decisions or open questions).
