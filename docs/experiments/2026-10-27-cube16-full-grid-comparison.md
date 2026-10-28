---
title: Full-grid cube16 BO, Sobol and GA comparison, seed 0
source: Detached GB10 runner and its saved checkpoints
author: Team working notes
received: 2026-10-27
date: 2026-10-27
kind: sim
git_commit: 64c94a7 plus archived local benchmark changes; sim server 121b55d
status: COMPLETE, single-seed Isaac comparison retrieved 2026-10-28
---

# Full-grid optimizer comparison: first matched seed

## Question

At equal candidate budgets, do BO, Sobol or genetic search produce a better validated 16 mm cube finger, or reach
similar quality at lower cost? Unlike the earlier sparse pilot, this run uses the full search and validation grids.
The user authorized starting this experiment on 2026-10-27. The first seed completed; no multi-seed conclusion is valid yet.

Oliver's exact EXP-0006 D1 artifact/job export is unavailable. Its documented 92.3% is a historical reference only,
not a freshly measured comparator. This run must not claim to beat that exact finger without its saved design.

## Configuration and cost

- Config: `app/backend/scripts/benchmarks/cube16-full-seed0.json`.
- Original 16 mm cube STEP, PLA assumption, pose 0, valid 0-degree face grasp, default drop task and 3 mm/8 deg error.
- Seed 0, 32 candidate designs per method: identical 12 Sobol starts, then five batches of four. BO and GA therefore
  get 20 post-initialization proposals each; Sobol continues its sequence. Patience is diagnostic, not a stop rule.
- Full search grid: 243 offsets per candidate. Full validation grid: 963 offsets.
- Up to three distinct geometry finalists per method, three selection repeats per finalist, then three independent
  winner holdouts. Stock and imprint receive matched selection/holdout grids outside candidate budgets.
- Upper bound: **70,038 submitted grasps**, about **3.89 h at an assumed 5 grasps/s**, plus overhead and contention.
  Rejected geometry and server stock-fit skips reduce actual physics work. Count submitted and returned measurements
  separately. The earlier tiny pilot's timing does not establish full-batch throughput.
- Only seed 0 is launched. Method order now depends on the seed value, so later separately launched seeds 1/2 will
  rotate order consistently rather than always beginning with BO.

## Durable execution and isolation

The runner is deployed in its own directory and virtual environment:

```text
/home/hackathon11/optimization-benchmark-20261027/
```

It does not modify `~/repo` (the running simulator) or `~/autograsp` (the hosted app). Dependencies were installed from
the existing lockfile using `uv sync --locked --no-dev --package backend --python 3.12`. ARM64 CAD import, job preparation
and HTTP preflight succeeded. Python is 3.12.15; PyTorch uses two CPU threads, with OMP/MKL/OpenBLAS limits set to two.
The CPU simulator retains 64 environments and its existing reference-compatible settings.

Source archive: local `app/data/benchmark-fullgrid-source-20261027.tar.gz`, copied to
`/home/hackathon11/optimization-benchmark-source-20261027.tar.gz`.
SHA256: `b4ee25713b03c85b3767496b3aea9e4e116a524b2a94078cfe334b27fd331369`.
The archived source manifest records main revision and hashes of all source files, including uncommitted additions.
The runner also stores source hashes, runtime versions, actual thread count and archive-manifest hash in `results.json`.

Launched **2026-10-27 14:18 CDT**, with `setsid nohup` and detached stdin. Launcher PID/session ID **2688150**,
parent PID 1, verified through a fresh SSH connection. The worker calls `127.0.0.1:9011` on GB10 directly and does not
depend on MICHAEL-SERVER, its RDP session or VPN after launch. The shared simulator was healthy and idle before launch.

The command inside that isolated directory is:

```bash
bash app/backend/scripts/run_benchmark.sh app/backend/scripts/benchmarks/cube16-full-seed0.json app/data/benchmarks/full-seed0 http://127.0.0.1:9011
```

The helper writes the final shell exit code to `app/data/benchmarks/full-seed0.exit-code`. Atomic checkpoints retain
completed batches if the worker fails. Automatic resume is still unsupported; do not launch a replacement or another
copy on top of the output directory, because an in-flight server request may already be running.

## Progress and artifacts

### Completed results, retrieved 2026-10-28

The manifest is complete and the launcher exit code is 0. Finished 2026-10-27 at 17:07 CDT; total elapsed
10,131.43 seconds (2 h 49 min). All 96 candidate evaluations completed. Across search, selection and holdout phases,
70,038 grasps were submitted and 64,017 landing measurements returned. Missing measurements are not evidence of
executed physics attempts; stock fit skips are included in submitted counts.

| Method | Dense selection mean | Independent holdout mean (3 repeats) | Holdout SD | Capture radius at selection |
| --- | --- | --- | --- | --- |
| BO | 92.3202% | 92.3126% | 0 | 4.5 mm |
| Sobol | 91.1750% | 91.1750% | 0 | 4.5 mm |
| GA | 90.9623% | 91.0391% | 0 | 3.5 mm |

BO leads Sobol by 1.1376 percentage points and GA by 1.2735 points on these fresh holdouts. Imprint holdout is
26.4726%; stock is 0 from the fit check, not demonstrated physical failure. These are weighted simulator success
scores, not physical trial success rates. Identical three-repeat scores do not establish zero underlying uncertainty.

BO had five duplicate parameter/geometry proposals; GA had three; Sobol had none. No rejected candidates or BO fallback
batches were recorded. The log contains numerical jitter warnings and a BoTorch acquisition-optimization retry; the
run nevertheless completed. Search proposal overhead was 2.92 seconds for BO versus roughly 1,253 simulator seconds
per method. Duplicate avoidance is a concrete future efficiency improvement; do not alter this completed experiment.

BO reproduces approximately the historical D1 score, not a demonstrated improvement over Oliver's unavailable exact
design. One seed supports a preliminary ranking only. No additional campaign was launched during retrieval.

Downloaded artifacts are in local `app/data/benchmarks/cube16-full-seed0-20261027/`: raw `results.json`, `candidates.csv`,
`report.md`, two standalone convergence SVGs and `runner.log`; the sibling `.exit-code` file records 0.
The GB10 directory remains authoritative and unchanged. Hardware performance and print approval remain unvalidated.
Local and remote raw JSON SHA256 match: `5ae789c76227aaed375022c5cdb5fbd81ebcc02873c171ce9a5070576aceb03d`.

At the initial check around 14:20 CDT, the process was alive and the first 12-design BO batch was running
(simulator log showed chunk 12 of 46). Two baseline observations were checkpointed: stock 0 from the fit check,
imprint 0.25943 on the search grid. Those are preliminary baseline measurements, not final results.

Authoritative files on GB10:

```text
optimization-benchmark-20261027/app/data/full-seed0.pid
optimization-benchmark-20261027/app/data/full-seed0.log
optimization-benchmark-20261027/app/data/benchmarks/full-seed0/results.json
optimization-benchmark-20261027/app/data/benchmarks/full-seed0.exit-code
```

Read-only status from PowerShell or Bash:

```text
ssh hackathon11@spark1.ai.msoe.edu '/home/hackathon11/optimization-benchmark-20261027/.venv/bin/python /home/hackathon11/optimization-benchmark-status-20261027.py /home/hackathon11/optimization-benchmark-20261027/app/data/benchmarks/full-seed0'
```

The status utility is outside the active source snapshot and does not change the experiment. `incomplete` with no exit
code means only that completion has not been recorded; verify the PID before inferring that it is still running.
On completion, inspect `report.md`, candidate CSV and convergence SVGs in the output directory. Require both a complete
manifest and a zero exit code; preserve failures. Copy the directory back to local `app/data/benchmarks/` for analysis.

## Verification and interpretation

Pre-push verification on 2026-10-28:

- `uv run pytest app/backend/tests/services/test_benchmark.py app/backend/tests/services/test_optimizer.py -q`:
  **33 passed in 187.33 s**.
- `uv run pytest -q`: **1,044 passed, 1 failed in 445.36 s**. The unchanged compute test
  `test_a_vpn_outage_while_connected_is_waited_out_and_the_forward_reopened` observed a stale connected message at
  its timing boundary. Rerun alone with its full pytest node ID: **1 passed in 1.12 s**. The full-suite failure remains
  recorded; no compute implementation/test changes were made to mask it.
- `uv run ruff check .`: passed; `uv run ruff format --check .`: 278 files already formatted.
- `npm.cmd run build --prefix app/frontend`: passed, 894 modules; existing large-chunk warning remains.
- `git diff --cached --check`: passed. Runtime data, environments, credentials and generated artifacts excluded.

Local regression for schedule/cost accounting and independently launched seed order: **2 passed, 17 deselected in
16.95 s**. Ruff lint, formatting and Git whitespace checks passed before deployment. Remote launcher `bash -n` passed;
preflight records a standard 243/963 grid, 96 candidates and two PyTorch threads. This does not validate final quality.

Analyze independent holdout means, repeat variation, selection/search optimism, landing failures, submitted/measured
work and total time. A single seed can screen methods, not establish a robust method win. Expand to matched seeds only
after inspecting this run and shared-machine availability. No robot-policy or submission changes and no physical commands.
