---
title: Optimization benchmark local verification
source: Local commands and saved benchmark artifacts
author: Team working notes
received: 2026-10-22
date: 2026-10-22
kind: other
git_commit: d216d9b098ec117edafc1077cdcaff06d8b05276 (dirty working tree)
---

# BO, Sobol and genetic benchmark verification

Windows MICHAEL-SERVER, Python 3.12 root venv, CPU BoTorch and mock geometric simulator. No Isaac or physical-robot
validation was performed. Source and lockfiles are hashed in the final run manifests; the working tree is uncommitted.

## Commands and outcomes

- `.venv/Scripts/python.exe -m pytest app/backend/tests/services/test_optimizer.py app/backend/tests/services/test_benchmark.py -q`:
  **23 passed in 85.50 s**. Covers existing optimizer behavior, shared initialization, budgets, GA determinism/bounds/elitism,
  diagnostic patience, rejections, duplicates, fallback, finalists/repeats, dry-run isolation, preflight, failure checkpoints
  and output-directory protection.
- `.venv/Scripts/python.exe -m pytest -q`: **905 passed, 1 failed in 267.41 s**. Failure:
  `test_a_vpn_outage_while_connected_is_waited_out_and_the_forward_reopened` in existing `test_compute.py`.
  Its simulated outage interval unexpectedly included a previous Connected message. Isolated rerun of that exact test:
  **1 passed in 1.03 s**. This appears timing-sensitive; no unrelated compute code/test was changed. The full suite is
  not claimed to be completely green.
- `.venv/Scripts/ruff.exe check .`: passed. `.venv/Scripts/ruff.exe format --check .`: 246 files already formatted.
- `npm.cmd run build --prefix app/frontend`: passed, 152 modules; no frontend source or lockfile changes.
- `git diff --check`: passed.

Final mock runs (from repository root):

```text
.venv/Scripts/python.exe app/backend/scripts/benchmark.py app/backend/scripts/benchmarks/cube-smoke.json --output app/data/benchmarks/cube-smoke-final-20261022
.venv/Scripts/python.exe app/backend/scripts/benchmark.py app/backend/scripts/benchmarks/screw-quick.json --output app/data/benchmarks/screw-quick-final-20261022
```

| Run | Candidates per method | Seeds | Observations including validation | Geometric mock grasps | Elapsed |
| --- | ---: | --- | ---: | ---: | ---: |
| Cube final smoke | 32 | 0, 1, 2 | 372 | 146,556 | 135.36 s |
| Screw final quick | 14 | 0 | 70 | 35,730 | 34.91 s |

Both manifests have status `complete`, actual BO proposals and zero fallback batches. Cube BO had one duplicate and
GA had seven duplicates in the first smoke run; these are recorded, not silently resampled. Dense repeat scores are
deterministic under this mock and cannot estimate Isaac noise. No physical algorithm recommendation follows from them.

Screw preparation successfully used the original STEP (16 convex pieces), a low-height stable pose and the existing
ranked valid-grasp proposal. Additional verification run `screw-verified-20261022` completed in 33.09 s with 70 observations.
Earlier smoke/quick development runs also completed and remain under ignored `app/data/benchmarks/`.

BoTorch emitted numerical jitter warnings during cube proposals, but did not fall back. A PowerShell command redirecting
native stderr reported exit 1 despite a completed JSON manifest; the unredirected verification run also reached complete.
Use the runner's exit status and manifest together, and preserve stderr when investigating failures.

## Remote blocker and handoff

Latest read-only retry: `Resolve-DnsName spark1.ai.msoe.edu` returned DNS server failure; SSH reported that it could not
resolve the hostname. Windows reported the PANGP GlobalProtect adapter disabled and no selected VPN route. Earlier checks
with a VPN route still timed out before SSH authentication, so VPN connectivity alone does not establish account/network
access. No SSH key, server version or Isaac settings were validated in this session.

Use the [teammate runbook](../notes/benchmark-runbook.md) and source handoff archive under
`app/data/benchmark-handoff-20261022.zip`. The archive contains the current source tree, including untracked additions,
and excludes Git-ignored environments, credentials and runtime data. Return real run folders plus operator-recorded
server revision/settings; log all real failures. CPU-reference physics validation remains pending.
