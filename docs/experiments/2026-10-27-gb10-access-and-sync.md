---
title: GB10 access restored and local checkout synchronized
source: Local commands, GB10 health and small real Isaac batches
author: Team working notes
received: 2026-10-27
date: 2026-10-27
kind: sim
git_commit: 64c94a7 (local working changes); server archive marker 121b55d
---

# GB10 access and current app verification

## Access and source versions

Passwordless SSH from MICHAEL-SERVER to `hackathon11@spark1.ai.msoe.edu` succeeded after installing the local public key.
The user confirmed the server host key. GlobalProtect must remain connected on MICHAEL-SERVER. Its log shows an RDP
disconnect at 12:49:49 followed by Switch off at 12:49:50; the user-switch tunnel grace period is configured as zero.

The existing server was idle (`queued: 0`, GPU utilization 0%, no other users listed by `who`). Its process is:

```text
/home/hackathon11/isaac-sim-6.0.1/venv/bin/python -m sim_server --port 9011 --envs 64 --device cpu
```

`~/repo` is a deployed archive, not a Git checkout. `COMMIT` reports `121b55d`, copied 2026-10-26. That includes the
team's landing measurement and BO patience fix. The server was not updated, restarted or stopped in this verification.

The local checkout was 28 commits behind. After preserving the uncommitted work and a consistent SQLite backup under
ignored `app/data/pre-sync-20261027/`, main fast-forwarded to `origin/main`, `64c94a7`. The preservation stash is retained.
Local benchmark changes were reapplied and adapted to the new per-pose outcome format and section-grasp span. Production
patience, landing-as-miss scoring, finger-library work and frontend changes from the team were retained.

## Real Isaac connectivity batches

10 mm cube, 1.24 g, part friction 0.6/0.5, stock and imprint, dx 0/-2/+2 mm, dy 0, yaw 0, no transport or force override.
Each batch has **six grasps**, not a complete offset grid or optimization campaign.

| Batch | Client | Held | Landing-aware task success | Elapsed |
| --- | --- | --- | --- | --- |
| Before local source sync | Old client | stock 3/3, imprint 3/3 | unavailable: old client discarded landing data | 7.34 s |
| After local source sync | Current client | stock 3/3, imprint 3/3 | stock 3/3, imprint 3/3; every measured landing (0 mm, 0 deg) | 6.47 s |

Settings returned by the server: CPU, 64 environments, average friction combine, physics dt 1/60 s, TGS,
position/velocity iterations 16/2, robot iterations 32/1, contact/rest offset 0.2/0 mm, 2 physics steps per frame,
control 30 FPS, jaw force limit 180 N. These match the documented reference-compatible configuration. The force limit
does not establish the actual holding force; the earlier weak-grip caveat still applies.

Raw artifacts (ignored):

- `app/data/benchmarks/gb10-preflight-20261027/`: standalone HTTP preflight, no simulated grasps.
- `app/data/benchmarks/gb10-contract-20261027/results.json`: first six grasps.
- `app/data/benchmarks/gb10-landing-contract-20261027/results.json`: six current-client grasps and landing measurements.
- `app/data/benchmarks/gb10-landing-contract-20261027/app-connection.json`: app connection and managed-tunnel health.

No real-arm connection or physical validation occurred. These samples demonstrate access and contract compatibility,
not improved finger performance. Larger simulations were not launched: the team already has screw and 16 mm cube runs.

## Local app and regression checks

Updated locked dependencies with `uv sync --all-packages --locked --python 3.12` and `npm.cmd ci --prefix app/frontend`.
The upstream lockfiles were used unchanged. API startup migrated the backed-up local database through revision 0008.
The local ignored `.env` now selects HTTP simulation and GB10 compute, with CPU reference flags for any future startup.

The app's GPU connection reached `ready`; its managed SSH forward on local port 9000 returns the CPU simulator's health.
The API health endpoint and built dashboard return HTTP 200 at `http://127.0.0.1:8000/`; Vite runs at
`http://127.0.0.1:5173/`. The current frontend uses `/`, not the older `/app.html`.

- Focused benchmark, optimizer and search-plan tests: **46 passed in 121.79 s**.
- Benchmark tests after the section-grasp/landing adaptation: **14 passed in 31.39 s**.
- Frontend build: passed, 894 modules. One initial build was attempted while npm installation was still running and
  failed because `tsc` was not installed yet; rerunning after installation passed.
- Ruff lint and Git whitespace checks passed after conflict resolution.
- Current-source cube quick mock benchmark: complete, 14 candidates per method, seed 0, 70 observations including
  validation, 13.37 s, no BO fallback. This verifies the adapted runner; it is not a physics result.
- Full offline suite: **1,040 passed in 399.96 s** using `.venv/Scripts/python.exe -m pytest -q`.
  This excludes Isaac integration tests; the real six-grasp checks are recorded separately above.
- Final Ruff format check: **275 files already formatted**; lint and `git diff --check` passed.

## Existing team results and next priorities

The [screw reruns](2026-10-26-gb10-landing-check-and-screw-reruns.md) already assess the patience fix and simulator noise.
The [16 mm cube run](2026-10-27-gb10-cube16-library-and-generation.md) is the stronger generation example:
stock 0%, best library finger 17.6%, generated D1 92.3% at assumed 3 mm/8 deg error. These are teammates' recorded Isaac
results, not outcomes of the six-grasp connectivity check above.

The remaining submission priorities are the reviewed 16 mm cube policy/placement, correct team/contact fields, video
and summary, and a booked supervised real-arm session with mount/material/accuracy measurements. Do not fabricate
physical results or fill unknown submission fields. No platform submission or physical-policy change was made here.

The cube's original job database and CAD/video artifacts are on Oliver's laptop, not in Git or automatically copied
by this sync: EXP-0006 `aaf38cd0b9`, outputs `app/data/outputs/aaf38cd0b9/`, clips 9–11. Obtain that existing output folder
and the relevant exported job/part metadata for video, review and printing; the local app's database is a separate one.
