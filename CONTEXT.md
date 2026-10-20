# Project context

Living summary of where the project stands. Keep it short and current. Source documents live in [docs/](docs/README.md);
this file records what they mean for us. Gotchas and warnings: [docs/notes/things-to-know.md](docs/notes/things-to-know.md). Update it whenever a fact, decision, deadline or open question changes.

*Last updated: 2026-10-20*

## One-line pitch

**CAD-to-Fingers:** give it a new part and a task, and it outputs 3D-printable gripper fingers for the existing gripper on the
FANUC ER-4iA cell. The fingers are optimized in the digital twin to tolerate camera and calibration error, and each design
comes with a grasp pose and a predicted success rate that we then check in physical trials.

Hackathon: Rockwell Automation + NVIDIA Innovation Lab, Fall 2026, **Dataset 3: Grasping and Sorting**
([overview](docs/01-hackathon-overview.md), [dataset](docs/03-dataset-3-grasping-sorting.md),
[our plan](docs/02-team-plan.md)).

## Deadlines

| Date | What | Status |
| --- | --- | --- |
| Thu 2026-10-08 | Kickoff | done |
| Wed 2026-10-14 23:59 CT | Team plan | **submitted**; feedback received |
| **Sun 2026-11-01 23:59 CT** | **Final submission:** ~5 min video, one-page summary, repo link, references/credits | open |
| Thu 2026-11-05 17:00–20:00 | Finals, MSOE Diercks Hall, live presentation | open |

Judges want: (1) the solution **running on real hardware** (the FANUC arm, in a supervised test at CSI), (2) a specific problem,
(3) a business case for other manufacturers, and (4) **measured results against a baseline**, including where it fails.

## Pipeline (as built, 2026-10-20)

The backend follows the [input-flow plan](docs/notes/input-flow-backend-plan.md); its API, as built, is in
[backend-api.md](docs/notes/backend-api.md).

1. **Inputs, the eight steps.**
   - Upload a STEP or STL (CadQuery: measured, split into convex pieces once). Choose the material and mass.
   - Pick a resting pose (trimesh stable poses).
   - Choose the task: drop, place or insert, with tolerances and an optional transport move.
   - Confirm a versioned cell profile.
   - Choose the grasp axis: auto proposals, or a manual pick, both checked by geometry.
   - Choose finger families and their parameter ranges or locks (typed `VPadParams`).
   - Set the camera-error model: presets, bias, or a sigma range.
   - Review the plan.
2. **Search.**
   - One batch-BO search per family: 128 designs, 2d + 4 Sobol starting designs, and a batch size set by the sim's
     environments.
   - Each round is one sim request: every design at every grid offset, plus the stock and imprint baselines.
   - The sim returns held, the in-hand pose and held after transport. All of it is stored, so any sigma, bias, task or
     tolerance re-scores later without simulating again.
3. **Finalize.**
   - The top 3 per search and the baselines are re-tested on the dense grid and labelled D1…, STOCK and IMP.
   - D1 is exported as STEP plus one STL per side, with the profile's mount holes (with print clearance) and an
     engraved ID (`EXP-0001-D1-L`).
   - Export checks run: solid, matches the sim, min wall, finger length.
   - A print sheet is produced.
4. **Outputs.**
   - Job cards with live progress.
   - The results view, with re-scoring.
   - The results tracker: a print selection, printed fingers, test plans the sim predicts, the spreadsheet round-trip,
     and predicted vs measured with Wilson intervals.
   - **Mock or Isaac badge** on everything.
5. **Validate:** print the top designs and test them on the real arm, with the generated test plan, against the
   **stock fingers** and the **imprint**.

The plan's LLM step is out of the loop (decision below). Stretch: a surrogate model that predicts success instantly.
`DEMO_DATA=true` runs the app on generated demo data (mock results, made-up physical trials) in `app/data/demo`.

## Repo status

| Component | Path | State |
| --- | --- | --- |
| Web app backend (input flow, batch BO, results, tracker, exports) | `app/backend/` | Works end-to-end with the **mock** sim, a geometric capture check (not physics): 466+ tests, plus an end-to-end run against a live server with real worker processes |
| Web app frontend | `app/frontend/` | New Vite + React UI being built against [backend-api.md](docs/notes/backend-api.md); the old single-file UI no longer matches the API |
| Sim service (HTTP bridge to Isaac Sim) | `sim/sim_server/` | Contract v2: mesh parts, part friction, grip-force limit, transport, in-hand pose. **Runs in Isaac on Brev** (2026-10-20): GPU test plan stages 0–3 pass on the reference path with stock fingers, 2.1 grasps/s; custom fingers, contract v2 and the GPU path not yet checked ([log](docs/experiments/2026-10-20-brev-sim-server-bringup.md)) |
| Digital twin starter v0.5 (cube stacking demo) | `sim/fanuc_er4ia_sim/` | Vendored from the organizers. Host tests and the headless scene build pass on Brev (2026-10-20); the stacking demo needs a Cosmos env and hasn't run. Only edit: the `.sh` files marked executable in git (2026-10-20, contents unchanged) |
| CAD output | `app/backend/src/api/models/finger_cad.py`, `clients/cad.py` | CadQuery STEP (the pair) + STL per side, mount holes from the cell profile (positions from the twin's photo reconstruction: **confirm on the real jaw**), engraved IDs, export checks, print sheet |

## Hardware and twin facts (from `sim/fanuc_er4ia_sim/docs/`)

- **Robot:** FANUC ER-4iA. Robot USD is loaded from Isaac's asset root (override: `FANUC_ROBOT_USD`).
- **Gripper in the twin:** **SMC MHZL2-16D2** pneumatic parallel gripper, **6 mm travel per jaw → 0–12 mm straight-face gap**.
  The stock custom fingers are about 76 × 12 × 6 mm aluminium blades with a hooked tip and an AA-sized circular recess. The
  tip gap is about 4 mm closed and 16 mm open.
- **TCP:** J6 origin → faceplate 70 mm + faceplate → fingertip 223 mm (UTOOL1) = **293 mm**.
- **Contact model:** rigid tips, distal 32 mm high-friction (static 1.5 / dynamic 1.3), *unmeasured* compliance and friction.
- **Cameras:** table (overhead) 1920×1080, side 1920×1080, wrist 1280×720 pinhole. No lens distortion is modelled.
- **Objects on the real cell (photos):** ~10 mm yellow cubes, yellow vial caps, clear glass tubes.
- **Starter task:** stack 6 rotated 10 mm cubes (Y,Y,B,B,R,R). Perception uses Cosmos3-Nano plus a calibrated image-geometry
  front end. Validated on Linux + Isaac Sim 6.0 + RTX A6000 (not Windows).
- Compute for the twin (access received 2026-10-20; bring-up order in the
  [GPU test plan](docs/notes/gpu-test-plan.md#0-machines-and-access)):
  - **Brev:** $500 of team credits on Alec's account (admin; teammates join through Team → invite link). Isaac Sim
    launchable on an **RTX PRO 6000** or **4500**, both stoppable ([email](docs/05-brev-credits.md)).
  - **MSOE GB10:** `ssh hackathon11@spark1.ai.msoe.edu` over the MSOE VPN; free, shared with other teams, ARM64
    ([email](docs/04-gb10-access.md); password not in the repo). Isaac Sim 6.0 there is a source build and needs an
    **R580 driver**: check `nvidia-smi` first.
  - Record GPU, runtime and credits per run ([tools and resources](docs/references/tools-and-resources.md)).
- Three interpreters: **host** `.venv`, **Isaac** `python.sh`, **Cosmos** env. Never swap them.

## Key risks / mismatches

1. **SCHUNK vs SMC.** Our plan and the dataset page say "SCHUNK"; the twin's CAD-derived model is an SMC MHZL2-16D2.
   Finger mounts must match the real actuator. **Confirm on the physical cell before designing mounts.**
2. **Tiny stroke.** A 12 mm max straight-face opening (16 mm at the hooked tips) means the plan's examples (tennis balls ~67 mm,
   eggs) **cannot be grasped** with the current actuator. This is what the organizers meant by "not all of the existing items will
   fit in the fingers". The demo part must fit inside the jaw stroke, or the fingers must be redesigned so the stroke is used
   differently (e.g. offset or angled fingers that change the effective opening).
3. **The error model decides whether fingers matter.** The default 3 mm (1 sigma) is a placeholder; the twin's own perception
   error was 0.19 mm, at which stock fingers rarely miss. Gains show at larger errors (cheaper camera, less calibration), so
   justify or measure sigma and show success-vs-error curves.
4. The mock sim scores capture geometry only, so its optimum (most slack and lead-in, flat pad) says nothing about real
   physics. The sim-predicted success rate is unvalidated until physical trials, so book CSI time early.
5. **The real twin's scores aren't noise-free, and can flatter a baseline** (Brev, 2026-10-20). Grasps within about 5 mm
   of centre repeat exactly, but near a design's capture edge about 9% of grid points flip between runs. And the stock
   fingers "held" a cube placed 8–12 mm off along the jaw axis, outside the open fingers, most likely because a finger
   landed on it and the descent squeezed it into the gap; a real arm may knock it away instead.

## Decisions

| Date | Decision | Why |
| --- | --- | --- |
| 2026-10-14 | Dataset 3, CAD-to-Fingers | Team plan |
| 2026-10-15 | Repo layout: `app/` (backend + frontend), `sim/` (twin + sim server), `docs/`, `data/` | Repo setup |
| 2026-10-19 | uv workspace: one `pyproject.toml` per component (`app/backend`, `sim/sim_server`), one root `uv.lock` | Deploy parts separately, keep deps consistent ([rule](.claude/rules/coding-style.md)) |
| 2026-10-19 | Backend restructured into routers / services / clients / models (package `api`), pydantic-settings config, pytest suite | Testable without HTTP; API contract unchanged ([rule](.claude/rules/coding-style.md#application-backend)) |
| 2026-10-19 | Database: SQLAlchemy ORM + Alembic migrations, connection via a database client and `DB_URL` | Readable schema, safe schema changes, Postgres-ready; existing `app.db` files are kept |
| 2026-10-19 | Sim server runs under Isaac's `python.sh` (FastAPI/uvicorn pip-installed into it); Isaac owns the main thread and `/evaluate` batches are queued to it one at a time | Isaac isn't importable from the uv venv and must be driven from one thread; the optimizer sends batches concurrently ([sim/README.md](sim/README.md#sim_server)) |
| 2026-10-19 | Batch Bayesian optimization with BoTorch (qLogNEI) on CPU-only torch, against a sim that runs designs x offsets per request (vectorized in Isaac) | Throughput; the GP is small, the GPU is for physics |
| 2026-10-19 | One pad shape with six part-relative parameters replaces the flat / V-groove / pocket templates | Every sample is a valid finger; no categorical template for the GP |
| 2026-10-19 | Score = expected success under the camera-error model over a fixed offset grid, plus capture radius | A sim grasp is near-deterministic, so a grid removes sampling noise, and one run scores any error level |
| 2026-10-19 | No LLM in the loop: round 0 = stock + imprint baselines + Sobol sample | Starting points don't need it; the baselines are the judges' comparison |
| 2026-10-19 | Sim contract: `POST {SIM_URL}/evaluate_batch`, fingers sent as convex pieces in the gripper frame | The sim server needs no design-space knowledge; what's simulated is what's exported |
| 2026-10-19 | Migration 0002 clears jobs made before it | Demo data; old rows don't fit the new design space |
| 2026-10-20 | Input flow + outputs backend per [the plan](docs/notes/input-flow-backend-plan.md) (decisions D1–D17 there): typed family params (`VPadParams`), closed gap reported not searched, 128 designs per BO search, raw outcomes stored and re-scored on demand | Agreed with Matt on 2026-10-19 |
| 2026-10-20 | Migration 0003 rebuilds the job tables empty and adds parts, cell profiles, printed fingers and test plans | Demo data again; the new spec doesn't fit old rows |
| 2026-10-20 | CadQuery is the only CAD kernel (part import, finger CAD); fingers are built as convex solids, so the sim's pieces and the printed STEP are the same solids | [cadquery-design.md](docs/notes/cadquery-design.md) |
| 2026-10-20 | Demo data lives in its own database (`DEMO_DATA=true` → `app/data/demo`), never the real one; its physical trials are labelled made up | Lets the UI be built and shown without mixing invented numbers into real results |

## Open questions / action items

- [ ] **Pick the demo part + task** sized for the jaws (candidates already on the cell: 10 mm cube, vial cap, glass tube).
      Ideally it is a "manufacturing part" per the organizer feedback.
- [ ] **Confirm actual gripper model and finger mounting interface** (bolt pattern, carriage geometry). Ask Zhen Zeng
      (zhenzeng@uwm.edu / `#dataset-3-grasping-sorting`). We also asked for gripper-body + mount CAD in the team plan.
- [ ] Get the **stock finger CAD** (the dataset page lists it) and confirm it matches `assets/gripper/photo_finger_detail.json`.
- [ ] Bring up the twin: `bootstrap.sh` host tests and the headless scene build pass on Brev (2026-10-20); the starter's
      stacking pipeline still needs a Cosmos env (optional for us).
- [ ] Run the sim server on a GPU ([docs/notes/gpu-test-plan.md](docs/notes/gpu-test-plan.md)): stages 0–3 done on Brev
      2026-10-20 ([log](docs/experiments/2026-10-20-brev-sim-server-bringup.md)); next stages 4–6 (custom fingers,
      contract v2, the GPU path and its throughput).
- [ ] **Decide how to score a part disturbed before the jaws close** (a finger landed on it): a miss, or a flag. Then
      read the part's pose at the end of the descent in the sim server and report it (risk 5).
- [x] Real CAD export (CadQuery → STEP/STL) from the same pieces, with mount holes (2026-10-20). Positions are still the
      twin's photo reconstruction: confirm on the real jaw and update the cell profile (`finger_mount`, `hole_clearance_mm`).
- [ ] Fill in the cell profile's *to confirm* fields: grip force at the cell's air pressure (SMC datasheet), max finger
      length, free space beside the gripper, table mat friction.
- [ ] Measure printed PLA/PETG friction against the demo part (tilt test) to replace the material estimates in
      `app/backend/src/api/models/material.py`.
- [ ] Measure Isaac throughput (grasps/s at 64 envs) so run-time estimates are real (`SIM_GRASPS_PER_S` until then).
- [ ] Test plan diagonals are at (±3, ±3) mm (4.2 mm out); the spec said "diagonals at 3 mm": confirm which is meant.
- [ ] Choose and justify the camera-error sigma for the demo (or measure it on the cell).
- [ ] Define success metrics before experiments (pick success / attempt, placement error, cycle time, recovery).
- [ ] Request a supervised physical test at CSI (Shamar Webster, `#data-and-testbed-requests`, webste63@uwm.edu) with a test
      plan, duration, attendees and dates.
- [x] Brev credits ($500) and GB10 access received (2026-10-20).
- [ ] Alec: activate Brev from Dan Schneider's invite and add the team as members.
- [ ] GB10: run the free check (driver, disk, sudo, compiler) before building Isaac Sim there
      ([GPU test plan 0.2](docs/notes/gpu-test-plan.md#02-msoe-gb10-free-check-it-first)).

## Contacts (short)

FANUC robot / twin: Zhen Zeng (zhenzeng@uwm.edu). Testbed, data, physical tests: Shamar Webster (webste63@uwm.edu).
Compute: Dan Schneider (danschneider@nvidia.com); GB10 resources: Riley (driley@nvidia.com). Event, Slack: Brett Storoe (storoeb@msoe.edu). Full table:
[docs/01-hackathon-overview.md](docs/01-hackathon-overview.md#who-to-ping).
