# Project context

Living summary of where the project stands. Keep it short and current. Source documents live in [docs/](docs/README.md);
this file records what they mean for us. Gotchas and warnings: [docs/notes/things-to-know.md](docs/notes/things-to-know.md). Update it whenever a fact, decision, deadline or open question changes.

*Last updated: 2026-10-15*

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

## Pipeline (from the plan)

1. **Input:** part CAD (or images) + task text.
2. **LLM** picks a finger template (flat pad / V-groove / pocket) and initial dimensions.
3. **Bayesian optimization** tunes dimensions. Each candidate gets repeated grasps in the ER-4iA twin, with the part offset from
   where the camera thinks it is.
4. **Output:** printable finger CAD + grasp pose + predicted success rate.
5. **Validate:** print the top 2–3 and test them on the real arm against the **stock fingers** and a simple **imprint** design.

Stretch: a surrogate model that predicts success rate instantly to screen candidates.

## Repo status

| Component | Path | State |
| --- | --- | --- |
| Web app (UI, job queue, optimizer, LLM step, exports, 3D finger preview) | `app/` | Works end-to-end with **mock** LLM and **mock** sim |
| Sim service (HTTP bridge to Isaac Sim) | `sim/sim_server/` | **Stub**: `run_grasps` not implemented |
| Digital twin starter v0.5 (cube stacking demo) | `sim/fanuc_er4ia_sim/` | Vendored as-is from the organizers; not yet run by us |
| CAD output | `app/backend/adapters.py` `make_scad` | Placeholder OpenSCAD; needs real CAD (e.g. CadQuery → STL/STEP) |

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
3. The app's design space (`SPACE` in `app/backend/adapters.py`) and its default form values assume large parts. They need to be
   re-ranged for this gripper.
4. The sim-predicted success rate is unvalidated until we run physical trials, so book CSI time early.

## Decisions

| Date | Decision | Why |
| --- | --- | --- |
| 2026-10-14 | Dataset 3, CAD-to-Fingers | Team plan |
| 2026-10-15 | Repo layout: `app/` (backend + frontend), `sim/` (twin + sim server), `docs/`, `data/` | Repo setup |

## Open questions / action items

- [ ] **Pick the demo part + task** sized for the jaws (candidates already on the cell: 10 mm cube, vial cap, glass tube).
      Ideally it is a "manufacturing part" per the organizer feedback.
- [ ] **Confirm actual gripper model and finger mounting interface** (bolt pattern, carriage geometry). Ask Zhen Zeng
      (zhenzeng@uwm.edu / `#dataset-3-grasping-sorting`). We also asked for gripper-body + mount CAD in the team plan.
- [ ] Get the **stock finger CAD** (the dataset page lists it) and confirm it matches `assets/gripper/photo_finger_detail.json`.
- [ ] Bring up the twin: run `bootstrap.sh` host tests, then the starter pipeline on Brev or the GB10.
- [ ] Implement `sim/sim_server` `run_grasps`: swap the finger geometry, spawn the part with offsets, grasp, lift, check.
- [ ] Re-range the `SPACE` design space and replace `make_scad` with real CAD export.
- [ ] Define success metrics before experiments (pick success / attempt, placement error, cycle time, recovery).
- [ ] Request a supervised physical test at CSI (Shamar Webster, `#data-and-testbed-requests`, webste63@uwm.edu) with a test
      plan, duration, attendees and dates.
- [ ] Watch for the separate **Brev credits** and **MSOE GB10 (Rosie)** access messages.

## Contacts (short)

FANUC robot / twin: Zhen Zeng (zhenzeng@uwm.edu). Testbed, data, physical tests: Shamar Webster (webste63@uwm.edu).
Compute: Dan Schneider (danschneider@nvidia.com). Event, Slack: Brett Storoe (storoeb@msoe.edu). Full table:
[docs/01-hackathon-overview.md](docs/01-hackathon-overview.md#who-to-ping).
