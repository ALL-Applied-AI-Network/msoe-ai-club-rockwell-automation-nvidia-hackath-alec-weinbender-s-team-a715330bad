---
title: Local setup and batch BO assessment
source: repository code inspection and local environment verification
author: Team development notes
received: 2026-10-21
kind: note
---

# Batch BO assessment

## Full-grid evidence (2026-10-28)

The first matched 32-candidate-per-method CPU Isaac comparison completed in 2 h 49 min. Independent dense holdouts
score BO 92.31%, Sobol 91.18% and GA 91.04%. BO leads this seed; across-seed uncertainty remains unmeasured. It does
not demonstrate improvement over Oliver's historical D1, whose exact saved design remains unavailable. BO repeated
five designs and GA three; avoiding duplicate evaluations is a concrete next efficiency experiment, not an implemented
production change. See the [full experiment](../experiments/2026-10-27-cube16-full-grid-comparison.md).

## Noise-aware comparison changes (2026-10-27)

The benchmark now supports the actual 16 mm cube, unique-geometry finalists and configurable repeated selection.
Cube16 configurations use three selection grids per finalist, choosing on their mean rather than the best single
score. Three further winner/baseline repeats remain held out; paired BO/Sobol/GA comparisons use only those fresh
scores. A regression case verifies that a lucky 0.95/0.10/0.10 candidate loses to a stable 0.65/0.65/0.65 candidate.
Existing production job selection is unchanged until the experiment supports adopting this additional validation cost.

A bounded 276-requested-grasp pilot tests the implementation on GB10 with three offsets. It is explicitly labeled
PILOT and cannot establish a full-grid quality gain. See the
[noise-aware experiment log](../experiments/2026-10-27-noise-aware-benchmark.md).

## Current status after team sync (2026-10-27)

The sections below describe the earlier checkout. Main is now synced to `64c94a7`: the team has already corrected
patience so Sobol initialization does not consume BO patience, added per-pose evaluation and section grasps, and treats
measured landing capture as a miss. The standalone benchmark was adapted to the current single-pose outcome format
and uses that landing-aware task score. It is an optional research tool, not a replacement for the team's production BO.

Real GB10 access is restored. Existing team experiments already include screw BO reruns and the 16 mm cube generation
result. Focus deadline work on the reviewed cube policy, physical session and submission; another broad search campaign
is not a prerequisite. See the [current access and verification log](../experiments/2026-10-27-gb10-access-and-sync.md).

## Implemented benchmark (2026-10-22)

The standalone [benchmark runner and handoff](benchmark-runbook.md) now compare existing batch BO, Sobol and one seeded
real-valued genetic algorithm without changing production selection. Candidate budgets, initialization, grids and batch
schedules are matched; patience is diagnostic only. Reports include actual simulator costs, rejected/duplicate designs,
BO fallback, dense finalists, repeated winners/baselines and paired seed differences.

Local cube smoke (32 candidates per method, seeds 0–2) and screw quick (14 per method, seed 0) completed with the mock
and real BoTorch proposals. These are software checks, not evidence to select a physical finger or search algorithm.
See the [verification log](../experiments/2026-10-22-optimization-benchmark.md). A teammate can use the runbook to execute
the same protocol against the existing GB10 CPU-physics service. The earlier access blocker was resolved; see the
2026-10-28 results above. The access notes below preserve the original setup investigation, not current connectivity.

## What exists

The optimizer designs gripper fingers, rather than optimizing the robot controller. Each finger family gets its own search over normalized continuous parameters. With three or more free parameters it uses CPU BoTorch: a `SingleTaskGP`, standardized scores, and sequential batch selection with `qLogNoisyExpectedImprovement`. Round zero uses `2d + 4` scrambled Sobol designs; failed proposals continue the same Sobol sequence. One- and two-dimensional spaces already use Sobol sweeps. No genetic algorithm is currently needed to get started.

Batch sizes account for simulator environment count, offsets and active BO searches, with a cap intended to leave four learning rounds. The default BO budget is 128 candidate designs. Patience is measured in designs, not rounds, and requires a gain greater than 0.005. A geometry rejection consumes a candidate slot but makes no simulator call for that design.

Each candidate is evaluated across a fixed offset grid. The objective is task success weighted by the selected camera-error distribution; capture radius breaks final ranking ties rather than being a second GP objective. Raw held flags, in-hand poses and transport outcomes support rescoring. Error outside the grid's covered cells counts as failure. Dense final validation refines position sampling but retains the original yaw layers.

Completed rounds are committed atomically. Resume reloads those trials; the HTTP client uses idempotency keys when retrying a lost request. Finalization retests the top three plus stock and imprint baselines. These are useful existing features to preserve.

## Priorities before algorithm changes

1. **Establish trustworthy simulator comparisons.** The existing experiment logs report landing capture, weak gripping and optimistic results with GPU environment copies. Confirm the server's actual settings and use the reference-compatible `--envs 64 --device cpu` configuration for reported comparisons. These are Isaac server flags; they do not move Isaac into the laptop's Python environment. Coordinate any restart of the shared server with teammates. Use a lightweight 10 mm cube first, then the M6 screw; avoid heavy or slippery parts until the force issue is understood.
2. **Measure BO against equal-budget Sobol.** The public job specification chooses methods by dimension; it does not expose an arbitrary BO/Sobol switch. A future isolated benchmark harness should reuse the same search space, Sobol generator, simulator and scoring, with benchmark-only search configurations. Do not compare a six-dimensional BO job with a two-dimensional Sobol job, and do not add a public API switch merely for this assessment.
3. **Measure noise and stopping behavior.** Repeat identical finalist and baseline grids to separate physical repeatability from search-seed variation. Test whether design-count patience ends BO before useful learning occurs. An inferred GP noise level is already present; explicit measured observation variance is a candidate improvement only after repeated-run data supports it.
4. **Measure wasted work and proposal time.** Record geometry rejections, duplicate physical geometries after parameter mapping, GP failures, acquisition time, simulator time and request occupancy. The fallback skips previous sequence indices, but that alone does not guarantee a Sobol fallback cannot coincide with an earlier BO candidate. Add deduplication or tune batch size only if these measurements show material waste.

## Proposed benchmark, not yet run

- Start with one finger family and the 10 mm cube, a fixed valid grasp, profile, material, mass, task, error model and free-parameter ranges. Save the complete inputs and both code revisions. Use the existing search grid and dense final grid unchanged for both methods.
- Smoke campaign: 32 candidates per method, paired seeds 0, 1 and 2. If useful differences survive repeatability checks, expand to 128 candidates and seeds 0 through 4. Sobol uses the same seed and initial sequence as BO. Match per-request design counts to the BO batch schedule to avoid confusing algorithm quality with request overhead.
- For a strict budget comparison, the benchmark-only BO configuration must disable patience termination by setting patience above the candidate budget; Sobol must evaluate that same budget in the same full-dimensional space. Do not alter production defaults. Also report existing production BO's early-stopping cost and quality separately.
- Evaluate stock and imprint once per paired search comparison and keep their results separate from candidate slots. Both methods retest their three best candidates and the baselines on the dense grid. Repeat the selected winner and both baselines on three fresh dense-grid evaluations, reporting every repetition; use these repeats for the reported winner score rather than the ranking pass.
- Plot best search score against cumulative simulator grasps, and report dense finalist scores, independent winner repeat scores, capture radius, actual grasp count, wall time, proposal time, GP fallback count and variation across paired seeds. Keep search, selection validation and repeated validation costs separate. Count only grasps actually submitted; stored rejected-design rows still contain nominal `n_grasps` and cannot alone measure simulator work. Stored trial durations divide batch elapsed time among submitted designs and do not measure proposal time.
- Keep simulator settings and machine fixed, record other GPU users, and alternate BO/Sobol execution order between seeds. Treat a gain as actionable only if it persists in the fresh evaluations across paired seeds and exceeds repeatability variation, with cost reported alongside quality. Otherwise retain existing BO and prioritize simulator fidelity or runtime improvements.
- Log every campaign and failure under `docs/experiments/`, including commit IDs, actual server flags, seeds, object assets, raw outcomes and timing artifacts. Local mock outcomes verify software flow only. Weighted grid scores and their correlated outcomes are not independent Bernoulli trials; do not attach a binomial confidence interval to them.

## Local operation

Setup was performed on Windows host `MICHAEL-SERVER` (not a detected guest VM), from commit `b69befd`. Installed uv 0.13.4 and managed Python 3.12.15, enabled `.githooks`, and installed both workspace members and frontend dependencies from their existing lockfiles. Node 26.3.0 and npm 11.16.0 were already installed. Neither lockfile changed.

Initial verification on 2026-10-21:

- Ruff lint passed; format check reported 237 files already formatted.
- Frontend production build passed. Vite served `/app.html` on port 5173, and its `/api/cell-profiles` proxy returned the backend's seeded profile.
- Backend startup migrated a fresh local SQLite database through revision `0005`; `/health` returned `{"status":"ok"}` on port 8000.
- Sim-server host tests passed: 266 tests in 48.32 seconds. These exercise Isaac-free logic and do not validate physics or GPU execution.
- Backend configuration, database, model, database-client and health-route tests passed: 239 tests in 78.86 seconds.
- After the runtime update, the complete offline suite passed: 893 tests in 267.80 seconds. This includes backend and sim-server host tests, not Isaac integration tests.
- After the runtime update, optimizer tests passed: 11 tests in 87.24 seconds. A live HTTP mock job (`065d6f52ca`, seed 0, 14-candidate budget, 10 mm PLA cube) completed all search rounds and final validation, producing a STEP, two STLs and a print sheet. See the [software verification log](../experiments/2026-10-21-windows-local-setup.md). This is not an Isaac or physical result.
- Initially optimizer tests and full-suite collection failed because CPU PyTorch 2.14.1 could not initialize `torch/lib/c10.dll` (`WinError 1114`). A standalone torch import also failed, so this was not confined to pytest or CAD import order.
- The installed Visual C++ runtime was 14.29.30153. Downloaded and signature-checked Microsoft's 14.44.35211 x64 installer. Silent installation failed with error 1459 (`0x800705b3`, failed elevation in this execution session). After the user installed it through the interactive desktop, Windows reported 14.44.35211 and standalone PyTorch import succeeded (`2.14.1+cpu`, CUDA false). Microsoft documents that the runtime must be at least as recent as the build tools used by the application: [runtime guidance](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist).
- `npm audit` reported one high-severity affected package, the locked Vite 8.3.1 (Windows launch-editor advisories). The audit lists 8.3.5 as a fix. No dependency upgrade or forced audit fix was applied. Development servers bind to localhost.

The root `.env` selects mock LLM, simulator and compute backends explicitly. It is ignored by Git. No API key or local Isaac installation is required. Run from the repository root in PowerShell:

```powershell
& "$env:USERPROFILE\.local\bin\uv.exe" run --package backend uvicorn api.main:app --host 127.0.0.1 --port 8000
```

In another terminal:

```powershell
npm.cmd run dev --prefix app/frontend -- --host 127.0.0.1
```

Use `http://127.0.0.1:5173/app.html` for the React UI and `http://127.0.0.1:8000/docs` for the job API. The frontend is still being built; the old root page does not match the current job API. A new terminal should find `uv` on PATH; the absolute command above also works in already-open terminals.

### Switch to GB10 after connectivity is verified

Initial SSH checks failed resolving `spark1.ai.msoe.edu`; Windows showed the PANGP adapter disabled and only Google DNS on active Ethernet. After the user reconnected GlobalProtect on this host, the adapter was up, the hostname resolved to `10.205.19.146`, and Windows selected the VPN route. SSH to port 22 still timed out. Authentication, remote code version, server health and server flags remain unverified. No remote server was started or restarted. Once SSH is reachable, verify passwordless access and inspect the existing server:

```powershell
ssh -o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=10 hackathon11@spark1.ai.msoe.edu 'hostname; cat ~/repo/COMMIT; curl --max-time 5 -fsS http://127.0.0.1:9011/health; ps -eo pid,args | grep "[s]im_server"'
```

If the host is new, verify its SSH fingerprint with the team before accepting it interactively. If authentication fails, register your own public key through the team's normal access process; never store the shared password in a file.

Once the server's code and settings are checked, replace the simulator and compute settings in the ignored `.env` with:

```dotenv
LLM_BACKEND=mock
SIM_BACKEND=http
SIM_URL=http://127.0.0.1:9000
COMPUTE_BACKENDS=gb10
COMPUTE_GB10_SIM_ARGS=--envs 64 --device cpu
```

Restart the local backend and connect `spark1` in the GPU panel. The flags apply when a server is started; they do not reconfigure an already-running server. Disconnecting the panel leaves the shared server running. Record measured outcomes only after actual Isaac runs, and retain the DRAFT/review gate for printable fingers.
