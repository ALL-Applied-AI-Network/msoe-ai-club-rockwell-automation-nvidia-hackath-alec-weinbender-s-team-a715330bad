# Project context

Living summary of where the project stands. Keep it short and current. Source documents live in [docs/](docs/README.md);
this file records what they mean for us. Gotchas and warnings: [docs/notes/things-to-know.md](docs/notes/things-to-know.md). Update it whenever a fact, decision, deadline or open question changes.

*Last updated: 2026-10-19*

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

## Pipeline (as built, 2026-10-19)

1. **Input:** the part as it rests on the table (cylinder standing or lying, or a box; sizes and mass) and the camera-error
   model (sigma in mm and degrees). The task text is stored but not used yet.
2. **Search space:** one pad shape with six parameters defined relative to the part: pad width, groove angle (180 = flat),
   groove depth, slack, fingertip height, lead-in. They're mapped from a unit cube so every point is a finger that fits
   (`app/backend/src/api/models/search_space.py`, geometry in `models/finger.py`).
3. **Batch Bayesian optimization** (BoTorch qLogNEI, CPU). Round 0 = the **stock** and **imprint** baselines plus a Sobol
   sample; each round is one sim request: every design at every point of a fixed grid of camera-error offsets.
4. **Score:** expected success under the error model, from the grid (`models/offset_grid.py`), plus the capture radius.
5. **Output:** the top designs and both baselines re-tested on a denser grid; the winner's geometry (OpenSCAD), grasp pose,
   predicted success and a success-vs-error curve next to the baselines.
6. **Validate:** print the top 2–3 and test them on the real arm against the **stock fingers** and the **imprint** design.

The plan's LLM step is out of the loop (decision below). Stretch: a surrogate model that predicts success instantly.

## Repo status

| Component | Path | State |
| --- | --- | --- |
| Web app (UI, job queue, batch BO, finger geometry, exports, 3D preview) | `app/` | Works end-to-end with the **mock** sim, a geometric capture check (not physics) |
| Sim service (HTTP bridge to Isaac Sim) | `sim/sim_server/` | `/evaluate_batch` written (reference path `--envs 1`, vectorized `--envs N`); host tests pass; **never run in Isaac** ([GPU test plan](docs/notes/gpu-test-plan.md)) |
| Digital twin starter v0.5 (cube stacking demo) | `sim/fanuc_er4ia_sim/` | Vendored as-is from the organizers; not yet run by us |
| CAD output | `app/backend/src/api/clients/cad.py` (`OpenScadCad`) | OpenSCAD of exactly the simulated pieces; **no mount holes** yet; needs CadQuery → STL/STEP with the confirmed mount |

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
- Compute for the twin: Brev Isaac Sim launchable (**RTX PRO 6000 preferred**, L40S fallback ~$3/hr) or the MSOE GB10.
  Record GPU, runtime and credits per run ([tools and resources](docs/references/tools-and-resources.md)).
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

## Open questions / action items

- [ ] **Pick the demo part + task** sized for the jaws (candidates already on the cell: 10 mm cube, vial cap, glass tube).
      Ideally it is a "manufacturing part" per the organizer feedback.
- [ ] **Confirm actual gripper model and finger mounting interface** (bolt pattern, carriage geometry). Ask Zhen Zeng
      (zhenzeng@uwm.edu / `#dataset-3-grasping-sorting`). We also asked for gripper-body + mount CAD in the team plan.
- [ ] Get the **stock finger CAD** (the dataset page lists it) and confirm it matches `assets/gripper/photo_finger_detail.json`.
- [ ] Bring up the twin: run `bootstrap.sh` host tests, then the starter pipeline on Brev or the GB10.
- [ ] Run the sim server on a GPU and check it against the reference path: [docs/notes/gpu-test-plan.md](docs/notes/gpu-test-plan.md).
- [ ] Real CAD export (CadQuery → STL/STEP) from the same pieces, with the confirmed mount holes.
- [ ] Choose and justify the camera-error sigma for the demo (or measure it on the cell).
- [ ] Define success metrics before experiments (pick success / attempt, placement error, cycle time, recovery).
- [ ] Request a supervised physical test at CSI (Shamar Webster, `#data-and-testbed-requests`, webste63@uwm.edu) with a test
      plan, duration, attendees and dates.
- [ ] Watch for the separate **Brev credits** and **MSOE GB10 (Rosie)** access messages.

## Contacts (short)

FANUC robot / twin: Zhen Zeng (zhenzeng@uwm.edu). Testbed, data, physical tests: Shamar Webster (webste63@uwm.edu).
Compute: Dan Schneider (danschneider@nvidia.com). Event, Slack: Brett Storoe (storoeb@msoe.edu). Full table:
[docs/01-hackathon-overview.md](docs/01-hackathon-overview.md#who-to-ping).
