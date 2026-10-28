---
title: Portable BO, Sobol and genetic benchmark
source: Repository implementation and local verification
author: Team working notes
received: 2026-10-22
kind: note
---

# Run the optimization benchmark for a teammate

2026-10-27 update: the local checkout is synced to team main (`64c94a7`), including the BO patience fix and
landing-aware task score. GB10 access and a six-grasp real Isaac check now pass; see the
[current log](../experiments/2026-10-27-gb10-access-and-sync.md). Use the updated
`app/data/benchmark-handoff-20261027.zip` when sharing; the 20261022 archive is historical. Existing team results already
cover screw BO and the 16 mm cube, so coordinate any additional campaign around the remaining submission work.
The benchmark currently supports one resolved resting pose per case; the main app also supports multi-pose jobs.

## Noise-aware experiments

A full-grid seed-0 comparison completed successfully on GB10 and was retrieved on 2026-10-28: fresh holdout scores
BO 92.31%, Sobol 91.18%, GA 91.04%. This is one seed, not a robust algorithm win or improvement over the exact D1.
See its [results and monitoring log](../experiments/2026-10-27-cube16-full-grid-comparison.md) before starting any additional
work against the shared simulator. `cube16-full-seed0.json` uses 32 designs per method and three selection repeats,
with a 70,038 submitted-grasp upper bound. Method order is stable by seed value even when seeds run as separate jobs.
`run_benchmark.sh` bounds the optimizer's CPU threads and records an exit code; `benchmark_status.py RUN` reads a local
checkpoint without mutating or resuming it.

`case: "cube16"` uses the unchanged 16 mm cube STEP, matching the team's current generation example.
`selection_repeats` controls how many fresh grids each distinct finalist receives before selection (default 1 for
existing configurations; 3 in the new cube16 configurations). Finalists with identical collision geometry share one
slot. Ranking uses mean task success, conservative minimum capture radius as a tiebreak, then original rank. The
winning design still receives three separate holdout repeats afterward; only those repeats enter paired-method
comparisons. The JSON preserves every raw observation and a separate selection mean, SD and repeat count.

For a bounded real-service check:

```text
uv run --package backend python app/backend/scripts/benchmark.py app/backend/scripts/benchmarks/cube16-pilot.json --dry-run
uv run --package backend python app/backend/scripts/benchmark.py app/backend/scripts/benchmarks/cube16-pilot.json --backend http --sim-url http://127.0.0.1:19011 --output app/data/benchmarks/my-cube16-pilot
```

The app-managed tunnel uses port 9000 instead of 19011 when the app's GPU session is connected.
This pilot has 14 candidates per method, seed 0, three selection repeats and three independent holdout repeats.
It submits at most **276 grasps**, estimated at 55.2 seconds of simulator time at 5 grasps/s, plus CAD/proposal/request
overhead. Its grid is **only center and +/-4 mm at yaw zero**, for search and validation. Every report, plot and CSV
labels it PILOT. Its scores are diagnostic and cannot be compared with the team's full-grid accuracy numbers.

`cube16-smoke.json` and `cube16-comparison.json` retain the standard 243/963 grids and three selection repeats. They
are much larger runs; always dry-run and coordinate shared resources first. Neither launches automatically.

`grasps` counts requests actually submitted after client-side geometry rejection. The server can skip some of those
(for example stock fingers too narrow for the cube). `measured_grasps` separately counts non-null landing measurements
returned by the current server; missing measurements do not establish the number of attempted physics steps. Reports
do not silently call submitted work the exact physics cost.

The runner does not need the web app, Node, an API key or a physical robot. It compares existing batch BO (qLogNEI),
scrambled Sobol and a real-valued genetic search. Mock results test software, **not physics or finger quality**.
Use a separate checkout/environment for this runner; do not replace the shared simulator's checkout or Isaac interpreter.

## 1. Get the implementation and install

These changes are initially uncommitted: pulling the existing branch alone will not fetch them. Obtain the handoff ZIP
or the full changed working tree from the teammate who prepared it. Extract to a new folder, not over the running server.
The ZIP must include new benchmark files, the backend, workspace manifests/lockfile and unchanged `cad/` assets.
The local handoff archive is `app/data/benchmark-handoff-20261022.zip`.
Do not include `.env`, `.venv`, credentials or runtime data. No password belongs in a command or report.

From that repository folder, PowerShell:

```powershell
uv python install 3.12
uv sync --all-packages --locked --python 3.12
uv run --package backend python app/backend/scripts/benchmark.py app/backend/scripts/benchmarks/cube-quick.json --dry-run
uv run --package backend python app/backend/scripts/benchmark.py app/backend/scripts/benchmarks/cube-quick.json --output app/data/benchmarks/my-cube-check
```

Linux, including a separate runner checkout on GB10 (NOT Isaac's environment):

```bash
uv python install 3.12
uv sync --all-packages --locked --python 3.12
uv run --package backend python app/backend/scripts/benchmark.py app/backend/scripts/benchmarks/cube-quick.json --dry-run
uv run --package backend python app/backend/scripts/benchmark.py app/backend/scripts/benchmarks/cube-quick.json --output app/data/benchmarks/my-cube-check
```

If `uv` is unavailable, use the team's installation steps in `SETUP.md`. On Windows, PyTorch also needs the current
Microsoft Visual C++ x64 runtime. Linux/ARM64 dependency installation has not been revalidated by this local Windows run.
The runner explicitly defaults to mock and ignores app `.env` settings. It creates and removes its own temporary
preparation database, never opening the web app's database. No frontend setup is needed to run it.

## 2. Inspect the existing GB10 service

Stay connected to MSOE VPN when accessing from a laptop. Check the host key with the team before first SSH login.
Use your existing SSH key; ask the team to register it if passwordless authentication fails.

```powershell
ssh -o BatchMode=yes -o ConnectTimeout=10 hackathon11@spark1.ai.msoe.edu 'hostname; cd ~/repo; git rev-parse HEAD; test ! -f COMMIT || cat COMMIT; curl --max-time 5 -fsS http://127.0.0.1:9011/health; ps -eo pid,args | grep "[s]im_server"'
```

The same SSH command works in Bash. Missing Git metadata on a deployed tree is possible; use its `COMMIT` marker
and confirm its deployed source with the teammate. Record the actual server revision separately from the runner revision.

Before reportable physics runs, the operator must verify:

- The service is the team's existing simulator on port 9011, compatible with contract v2, not the web API.
- The deployed revision is recorded; health alone does not prove the code revision.
- Reference-compatible settings are `--envs 64 --device cpu`, not the optimistic GPU-copy path. Compare `/health`
  physics settings to the [GB10 stages 4–6 log](../experiments/2026-10-20-gb10-stages-4-6.md).
- Teammates agree on the queue time and total simulation budget. Even smoke is a long physics run.
- If settings need changing, coordinate with the service owner. This runner **never starts, restarts or stops** a server.

Unknown revision/settings stay **unverified** in the results; the runner does not certify them. Save the inspection output
and operator confirmation beside `results.json` as `server-verification.txt` before sharing results.

## 3. Connect and preflight without evaluating grasps

On a laptop, keep this SSH tunnel open in a separate PowerShell or Bash terminal:

```text
ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -L 19011:127.0.0.1:9011 hackathon11@spark1.ai.msoe.edu
```

Then run (same command in PowerShell and Bash):

```text
uv run --package backend python app/backend/scripts/benchmark.py app/backend/scripts/benchmarks/cube-quick.json --backend http --sim-url http://127.0.0.1:19011 --preflight-only --output app/data/benchmarks/gb10-preflight
```

If the runner is on GB10 itself, substitute `http://127.0.0.1:9011`. Preflight requires simulator-specific health fields
and saves them; it performs CAD preparation but submits no grasps. `--dry-run` does not contact the service at all.
Both checks are necessary but neither validates physics. Choose a new output directory for every invocation.

## 4. Run the chosen experiment

After operator verification, start small. This command submits real simulation work, but no physical-robot commands:

```text
uv run --package backend python app/backend/scripts/benchmark.py app/backend/scripts/benchmarks/cube-quick.json --backend http --sim-url http://127.0.0.1:19011 --output app/data/benchmarks/gb10-cube-quick
```

Available JSON configurations under `app/backend/scripts/benchmarks/`:

| Case | Quick | Smoke | Comparison |
| --- | --- | --- | --- |
| `cube` / `screw` | 14 candidates per method, seed 0 | 32 per method, seeds 0–2 | 128 per method, seeds 0–4 |

Example full local mock smoke (no VPN needed):

```text
uv run --package backend python app/backend/scripts/benchmark.py app/backend/scripts/benchmarks/cube-smoke.json --output app/data/benchmarks/cube-smoke
```

Run `--dry-run` on the desired JSON before any HTTP run. It prints exact batch sizes, grid sizes, maximum grasps and
estimated simulator seconds. The cube smoke plans **146,556 grasps**, approximately **8.14 hours at an assumed 5 grasps/s**,
before proposal/CAD overhead. This is not a measured runtime guarantee. Rejected designs reduce actual simulator work.
Large comparisons are opt-in; no script launches them automatically. Avoid running competing campaigns simultaneously.

## Comparison protocol

- Each part is prepared once. Cube: unchanged 10 mm STEP, PLA, stable pose 0, grasp angle 0. Screw: unchanged M6 STEP,
  steel, 7.5 g, lowest-height stable pose, first nonblocked ranked grasp proposal. Failure to find a valid grasp aborts.
  The resolved geometry, pose, grasp, default cell profile and default drop/error specifications are persisted.
- Camera-error distribution, material friction and screw mass are assumptions, not newly measured hardware facts.
- All methods share the Sobol initialization, candidate budget, parameter mapping and batch schedule. Method order
  rotates across seeds. The current BO acquisition/fallback remains unchanged; a fallback is explicitly reported.
- GA uses a population the size of initialization, size-3 tournaments sampled with replacement, uniform crossover,
  Gaussian mutation (per-coordinate probability `1/d`, SD 0.1), and clipping to `[0,1]`. Elitist survival keeps the best
  population from all evaluated parents/offspring; equal scores prefer earlier evaluation. No duplicate repair/resampling.
- Patience never ends a benchmark early. Its hypothetical production stop is recorded at completed batch boundaries.
- Invalid geometry consumes candidate budget, yields zero score, and sends zero simulator grasps. Duplicate parameters
  and geometry are observations, not additional stopping criteria. Equal candidates need not mean equal actual grasps.
- Stock/imprint search baselines are shared across methods once per seed, outside search budgets. Each method's top
  three candidates get dense evaluation; score, capture radius, then earlier rank select the winner. Baselines also get
  dense evaluation. Winners and baselines each get three additional dense repeats per seed.
- Seeds control search randomness, not Isaac internals: this service exposes no matched physics RNG control. Grid offsets
  and settings are matched, and repeated dense evaluations estimate simulator variability without claiming determinism.
- A near-edge grasp can flip between repeats. Landing capture can inflate baseline and custom-finger scores; weak grip
  limits heavy/slippery objects. GPU copies were optimistic. Do not interpret mock convergence or a CPU run alone as
  real-robot validation. Weighted grid points are not independent Bernoulli trials; do not attach binomial intervals.

## Outputs, failures and returning results

Each run folder contains `results.json`, `candidates.csv`, `report.md`, `convergence-candidates.svg` and
`convergence-grasps.svg`. JSON includes raw outcomes, full resolved preparation, asset SHA256, package versions,
runner revision/dirty state, tracked diff, source/lockfile SHA256 hashes, simulator metadata and batch diagnostics. Keep the source handoff with results:
Git's tracked diff alone cannot reproduce new untracked source files.

Completed batches are checkpointed by atomic JSON replacement. Connection failures exit nonzero and produce an
**incomplete** report with retained observations. Hard termination can prevent report generation, but the last JSON
checkpoint remains. There is no automatic cross-process resume: an in-flight HTTP request might already have executed.
Do not concatenate reruns or treat incomplete data as an equal-budget comparison. Coordinate any replacement run.

Zip the entire completed output folder, plus `server-verification.txt`, and return it to the requesting teammate:

```powershell
Compress-Archive -LiteralPath app/data/benchmarks/gb10-cube-quick -DestinationPath app/data/benchmarks/gb10-cube-quick.zip
```

```bash
tar -czf app/data/benchmarks/gb10-cube-quick.tar.gz -C app/data/benchmarks gb10-cube-quick
```

Record real runs, including failures, in `docs/experiments/`. Do not commit runtime folders. No output is an approved
print or robot command; retain the app's DRAFT/review gate and supervised physical-hardware review.
