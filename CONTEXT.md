# Project context

Living summary of where the project stands. Keep it short and current. Source documents live in [docs/](docs/README.md);
this file records what they mean for us. Gotchas and warnings: [docs/notes/things-to-know.md](docs/notes/things-to-know.md). Update it whenever a fact, decision, deadline or open question changes.

*Last updated: 2026-10-22*

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
   **stock fingers** and the **imprint**. The real arm is reached through the organizers' platform
   ([dashboard](docs/06-participant-dashboard.md)): a run is 10 rollouts in a booked 30-minute slot, scored by their
   operator and recorded. Our printed fingers are declared under `custom_hardware`. [cell_policy/](cell_policy/README.md)
   is the policy (a screw into the bin) and the submission. Each rollout commands one test-plan offset.

The plan's LLM step is out of the loop (decision below). Stretch: a surrogate model that predicts success instantly.
`DEMO_DATA=true` runs the app on generated demo data (mock results, made-up physical trials) in `app/data/demo`.

## Repo status

| Component | Path | State |
| --- | --- | --- |
| Web app backend (input flow, batch BO, results, tracker, exports) | `app/backend/` | Works end-to-end with the **mock** sim, a geometric capture check (not physics): 466+ tests, plus an end-to-end run against a live server with real worker processes |
| Web app frontend (Auto-Grasp) | `app/frontend/` | New Vite + React UI in NVIDIA Brev's dark style, on the `frontend-shell` branch (2026-10-22): every screen in the [frontend plan](docs/notes/frontend-plan.md) works against the demo data; not yet served at `/` (the old single-file UI still is) |
| Sim service (HTTP bridge to Isaac Sim) | `sim/sim_server/` | Contract v2: mesh parts, part friction, grip-force limit, transport, in-hand pose. **Runs in Isaac on Brev and the GB10** (2026-10-20). Stages 0–3 pass on both, and they agree ([Brev](docs/experiments/2026-10-20-brev-sim-server-bringup.md), [GB10](docs/experiments/2026-10-20-gb10-sim-server-bringup.md)). Stages 4–6 ran on the GB10 ([log](docs/experiments/2026-10-20-gb10-stages-4-6.md)): finger swaps, the in-hand readout, mesh parts and transport work. Heavy parts don't (risk 6), and the GPU path is biased (risk 7). 2.75 grasps/s reference, ~5 with CPU copies, 16–28 on the GPU |
| Digital twin starter v0.5 (cube stacking demo) | `sim/fanuc_er4ia_sim/` | Vendored from the organizers. Host tests and the headless scene build pass on Brev and the GB10 (2026-10-20); the stacking demo needs a Cosmos env and hasn't run. Only edit: the `.sh` files marked executable in git (2026-10-20, contents unchanged) |
| CAD output | `app/backend/src/api/models/finger_cad.py`, `clients/cad.py` | CadQuery STEP (the pair) + STL per side, the cell profile's mount (default since 2026-10-20: SMC's jaw from its STEP, the root cut back for the jaw's tongue, M3 holes along the jaw travel; **confirm on the real jaw**), engraved IDs, export checks, print sheet. Checked against the STEP's jaw solid: no overlap, faces touching, holes aligned |
| Organizers' CAD of the cell | `cad/` | Gripper STEP, M6 screw, bin, 10/16 mm cubes, vial, cap, table texture; unchanged, with SHA-256s ([page](docs/07-cad-models.md)). All import through the app's part upload |
| Real-cell policy + submission | `cell_policy/` | Scripted fingertip policy: one screw into the bin, at each rollout's test-plan offset; placement generator; `submission.yaml` for the stock baseline. Unit tests pass, and the client's `--mock` says "Ready for the real robot" (0 of 461 actions rejected). **Not run on the real arm** |

## Hardware and twin facts (from `sim/fanuc_er4ia_sim/docs/`)

- **Robot:** FANUC ER-4iA. Robot USD is loaded from Isaac's asset root (override: `FANUC_ROBOT_USD`).
- **Gripper in the twin:** **SMC MHZL2-16D2** pneumatic parallel gripper, **6 mm travel per jaw → 0–12 mm straight-face gap**.
  The stock custom fingers are about 76 × 12 × 6 mm aluminium blades with a hooked tip and an AA-sized circular recess. The
  tip gap is about 4 mm closed and 16 mm open.
- **TCP:** J6 origin → faceplate 70 mm + faceplate → fingertip 223 mm (UTOOL1) = **293 mm**.
- **Contact model:** rigid tips, distal 32 mm high-friction (static 1.5 / dynamic 1.3), *unmeasured* compliance and friction.
- **Cameras:** table (overhead) 1920×1080, side 1920×1080, wrist 1280×720 pinhole. No lens distortion is modelled.
- **Objects on the real cell** ([CAD Models](docs/07-cad-models.md), in `cad/`): M6 × 30 countersunk screws (head Ø12,
  shank Ø6, about 7.5 g), 10 and 16 mm cubes, bins 50 × 50 × 55 mm (35 × 35 × 25 mm pocket), a vial Ø27.18 × 203 mm and its
  cap. **The platform's default scene is 8 screws and the yellow bin.** The twin scales the vial to Ø17 × 140, has
  `SCREWS = []` and `SHOW_BINS = False`, and renders a white table, because its mat texture isn't in the starter. The
  real surface's texture is `cad/manipbench-table-surface.png`.
- **Each SMC jaw (from the STEP)** is a flat tongue 5 mm thick along the travel, 8 mm wide and 15 mm long. Its inner face
  is 7.45 mm from the centreline with the jaws closed. Two Ø3.4 mm holes run along the travel, 4 and 11 mm below the
  shoulder ([cad/README.md](cad/README.md)).
- **Starter task:** stack 6 rotated 10 mm cubes (Y,Y,B,B,R,R). Perception uses Cosmos3-Nano plus a calibrated image-geometry
  front end. Validated on Linux + Isaac Sim 6.0 + RTX A6000 (not Windows).
- Compute for the twin (access received 2026-10-20; bring-up order in the
  [GPU test plan](docs/notes/gpu-test-plan.md#0-machines-and-access)):
  - **Brev:** $500 of team credits on Alec's account (admin; teammates join through Team → invite link). Isaac Sim
    launchable on an **RTX PRO 6000** or **4500**, both stoppable ([email](docs/05-brev-credits.md)).
  - **MSOE GB10:** `ssh hackathon11@spark1.ai.msoe.edu` over the MSOE VPN; free, shared with other teams, ARM64
    ([email](docs/04-gb10-access.md); password not in the repo; use your SSH key). Set up 2026-10-20 and **the default
    machine**: Isaac Sim 6.0.1 from NVIDIA's aarch64 pip wheels in `~/isaac-sim-6.0.1`, the sim server on port 9011,
    driver 580.178.04 (R580 needed). Isaac's start-up fails intermittently there, so retry
    ([GPU test plan 0.2](docs/notes/gpu-test-plan.md#02-msoe-gb10-free-shared-set-up)).
  - Record GPU, runtime and credits per run ([tools and resources](docs/references/tools-and-resources.md)).
- Three interpreters: **host** `.venv`, **Isaac** `python.sh`, **Cosmos** env. Never swap them.

## Key risks / mismatches

1. **SCHUNK vs SMC.** Our plan and the dataset page say "SCHUNK". The twin, and now the organizers' dashboard FAQ, say
   **SMC MHZL2-16D2** with custom aluminium fingers (2026-10-20), and its STEP is published. The finger mount now follows
   that STEP, which contradicts the twin's photo-based mount (holes across the travel, 10 and 23 mm below the root).
   **Confirm on the real jaw before printing**: the tongue, the holes and the screw direction.
2. **Tiny stroke.** A 12 mm max straight-face opening (16 mm at the hooked tips) means the plan's examples (tennis balls ~67 mm,
   eggs) **cannot be grasped** with the current actuator. This is what the organizers meant by "not all of the existing items will
   fit in the fingers". The demo part must fit inside the jaw stroke, or the fingers must be redesigned so the stroke is used
   differently (e.g. offset or angled fingers that change the effective opening). On the cell this rules out the 16 mm cube,
   the cap's plug (Ø20.8–23.6) and the vial (Ø27.18) for the stock fingers. The M6 screw's shank (Ø6) and the 10 mm cube fit.
3. **The error model decides whether fingers matter.** The default 3 mm (1 sigma) is a placeholder; the twin's own perception
   error was 0.19 mm, at which stock fingers rarely miss. Gains show at larger errors (cheaper camera, less calibration), so
   justify or measure sigma and show success-vs-error curves.
4. The mock sim scores capture geometry only, so its optimum (most slack and lead-in, flat pad) says nothing about real
   physics. The sim-predicted success rate is unvalidated until physical trials, so book CSI time early.
5. **The real twin's scores aren't noise-free, and can flatter a baseline** (Brev, 2026-10-20). Grasps within about 5 mm
   of centre repeat exactly, but near a design's capture edge about 9% of grid points flip between runs. And the stock
   fingers "held" a cube placed 8–12 mm off along the jaw axis, outside the open fingers, most likely because a finger
   landed on it and the descent squeezed it into the gap; a real arm may knock it away instead. On the GB10 the same
   **landing capture made a 12 mm-gap flat pad score like a 16 mm one** (55 vs 56 of 81), so it blunts the comparison
   between designs, not only the baseline ([log](docs/experiments/2026-10-20-gb10-stages-4-6.md)).
6. **The twin grips weakly: about 2.5 N per jaw** (GB10, 2026-10-20). A 300 g block holds only at μ ≥ 0.6–0.7 whatever
   the force limit, and at μ 0.3 parts over about 100 g drop. Heavy or slippery parts score as dropped for every design
   until this is understood (the close target for custom fingers, the jaw drive, or contact offsets).
7. **The GPU path with copies is biased optimistic** (GB10, 2026-10-20). `--envs 64` (GPU) holds about 9/81 more cube
   grasps than the reference, repeatably; GPU physics alone and CPU copies alone don't. Use `--envs 64 --device cpu`
   (about 5 grasps/s, matches the reference) for results we report, until the cause (CCD first) is found.
8. **The stock blade's orientation is inferred, not measured.** The twin puts the blade's 12 mm along the jaw travel,
   with straight faces 0–12 mm apart, but that range comes from the actuator's travel. SMC's jaw is a 5 mm tongue whose
   inner faces are 14.9 mm apart (jaws closed: 2.9 mm, since each moves 6 mm). That also fits the measured 4 ± 1 /
   15 ± 2 mm tip gaps if the blade were a 6 mm plate bolted to the tongue's inner face. Our printed fingers fit the STEP's
   jaw either way. The stock baseline (the twin's fingers) may be off by a few mm: photograph the real jaw and fingers.
9. **Finger length moves the real fingertips.** "tcp" actions command the stock fingertip (UTOOL1, 293 mm), and the cell
   rejects TCP z below −334 mm, about 1 mm above the surface. Printed fingers must end where the stock ones do (the app
   keeps the tips at z = 0 with the root against the jaw's shoulder), or `cell_policy` must offset them.

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
| 2026-10-20 | The app connects the sim to a GPU target from its GPU panel (`COMPUTE_BACKENDS=brev,gb10`), one at a time, forwarded to `SIM_URL`, so the rest of the app never knows which machine it is. Brev instances (created in the Brev console) are started, and stopped when asked or after 20 idle minutes. The shared GB10 is connected and disconnected, never stopped or auto-stopped. Each session runs in a detached process; jobs wait for a ready target | One prepared Brev instance stays stopped for the hackathon, so credits never burn unattended; the GB10 is free but shared, so a teammate's job is never cut off ([app/README.md](app/README.md#gpu-from-the-app)) |
| 2026-10-20 | A round whose connection drops (VPN, port forward) waits up to `SIM_RECONNECT_MINUTES` (120) and is resent under its `Idempotency-Key`; the sim server answers a resend from the run it already made | Long runs go through the GB10 over the MSOE VPN, which can drop; a lost round would otherwise fail the job and be run twice ([app/README.md](app/README.md#simulator-service)) |
| 2026-10-20 | The organizers' CAD files live unchanged in `cad/`, with their SHA-256s and where they came from | Small, shared by the app and the sim; `data/` is gitignored |
| 2026-10-20 | The default finger mount is SMC's jaw from its STEP (`SMC_FLAT_JAW_MOUNT`, face `+x`). The root is cut back to the tongue's inner face for 15.5 mm, with M3 holes along the jaw travel 4 and 11 mm below the root, self-tapping, 6 mm deep. The photo reconstruction stays as `PHOTO_MOUNT`. At startup, a database whose default profile is the old default, unedited, gets the new one as its next version | The STEP is SMC's model of the real gripper (the dashboard says so); the photo mount's 23 mm hole lies past the end of its jaw |
| 2026-10-20 | Physical validation runs through the organizers' platform with a blind scripted policy: the screw and bin are placed the same way every rollout, and each rollout's prompt carries the test-plan offset to command. Stock run and printed run use the same offsets | The commanded offset is the controlled error the fingers are designed for; the operator's placement error is the same for both; the recording carries the offset ([cell_policy/](cell_policy/README.md)) |
| 2026-10-22 | A job covers one or more resting poses, each with its own grasp. One physical finger, built for the likeliest (primary) pose, is simulated in every pose (one sim request per pose per round; the sim contract is unchanged) and scored by the poses' likelihoods renormalised over the ones covered; a pose it can't grip scores 0. Migration 0006 adds `trials.pose_outcomes`; one-pose jobs and old rows score exactly as before. Clips, test plans and physical validation stay on the primary pose for now | Parts come off a feeder or out of a bin in more than one pose; a finger that only works in one is worth less than its score said. The likelihoods are trimesh's quasi-static estimate, not measured, and the score assumes the cell knows each part's pose ([backend-api.md](docs/notes/backend-api.md#step-2-resting-pose)) |

## Open questions / action items

- [ ] **Pick the demo part + task** sized for the jaws. Proposed 2026-10-20: **one M6 × 30 screw into the yellow bin**. It's
      a manufacturing part, the platform's default scene, light, and its Ø6 shank fits the jaws. The table camera
      can't see screws, so position error is large. `cell_policy/` is built for it. Team to confirm.
- [ ] **Confirm the finger mounting interface on the real jaw**: the STEP's tongue, its holes 4 and 11 mm below the
      shoulder, which way the screws go, and how the stock fingers sit (risk 8). Ask Zhen Zeng (zhenzeng@uwm.edu /
      `#dataset-3-grasping-sorting`), or photograph it at the cell.
- [ ] Get the **stock finger CAD** (the dataset page lists it; the CAD Models page says "more parts will follow") and confirm
      it matches `assets/gripper/photo_finger_detail.json`.
- [ ] **Submit to the platform**: fill in `cell_policy/submission/submission.yaml` (team letter in `task_id`, contact),
      `uv run run.py --submit`, then book a slot in the dashboard's Calendar. The first real rollouts check the policy's
      jaw measurement (`cad2fingers_rollouts.jsonl`).
- [ ] Bring up the twin: `bootstrap.sh` host tests and the headless scene build pass on Brev and the GB10 (2026-10-20);
      the starter's stacking pipeline still needs a Cosmos env (optional for us).
- [x] Run the sim server on a GPU ([docs/notes/gpu-test-plan.md](docs/notes/gpu-test-plan.md)): stages 0–3 on Brev and
      the GB10, stages 4–6 on the GB10, and stage 7 (end to end with the app, plus the first Isaac Sim clips) on the GB10
      (2026-10-20, [log](docs/experiments/2026-10-20-gb10-app-end-to-end-and-clips.md)).
- [ ] **Decide how to score a part disturbed before the jaws close** (a finger landed on it): a miss, or a flag. Then
      read the part's pose at the end of the descent in the sim server and report it (risk 5). Rerun stage 4 after:
      `pad_x0` should drop from about 1.5 mm.
- [ ] **Find why the twin grips at about 2.5 N per jaw** (risk 6), then rerun GPU test plan 5.3–5.5. Meanwhile, pick a
      light demo part (under about 100 g).
- [ ] **Find the GPU-with-copies bias** (risk 7), starting with CCD; then rerun stage 6. Also run the L-bracket's
      reference grid twice, to know its own repeatability.
- [x] Real CAD export (CadQuery → STEP/STL) from the same pieces, with mount holes (2026-10-20). Since 2026-10-20 the mount
      follows SMC's STEP of the jaw. Confirm it on the real jaw and update the cell profile (`finger_mount`,
      `hole_clearance_mm`).
- [ ] Fill in the cell profile's *to confirm* fields: grip force at the cell's air pressure (SMC datasheet), max finger
      length, free space beside the gripper, table mat friction.
- [ ] Measure printed PLA/PETG friction against the demo part (tilt test) to replace the material estimates in
      `app/backend/src/api/models/material.py`.
- [x] Measure Isaac throughput (GB10, 2026-10-20): 2.75 grasps/s reference, ~5 with `--envs 64 --device cpu`, 16–19
      with 64 GPU copies, 28 with 256. Set `SIM_GRASPS_PER_S` to match the path in use.
- [ ] Test plan diagonals are at (±3, ±3) mm (4.2 mm out); the spec said "diagonals at 3 mm": confirm which is meant.
- [ ] Choose and justify the camera-error sigma for the demo (or measure it on the cell).
- [ ] Define success metrics before experiments (pick success / attempt, placement error, cycle time, recovery).
- [ ] Request a supervised physical test at CSI (Shamar Webster, `#data-and-testbed-requests`, webste63@uwm.edu) with a test
      plan, duration, attendees and dates. The platform's slots ([dashboard](docs/06-participant-dashboard.md)) are now the
      main route, and the printed fingers are reviewed with the request (`custom_hardware`).
- [x] Brev credits ($500) and GB10 access received (2026-10-20).
- [ ] Alec: activate Brev from Dan Schneider's invite and add the team as members.
- [x] GB10: check and set up (2026-10-20): driver 580.178.04 passes, Isaac Sim 6.0.1 installed from pip wheels
      ([GPU test plan 0.2](docs/notes/gpu-test-plan.md#02-msoe-gb10-free-shared-set-up)).

## Contacts (short)

FANUC robot / twin: Zhen Zeng (zhenzeng@uwm.edu). Testbed, data, physical tests: Shamar Webster (webste63@uwm.edu).
Compute: Dan Schneider (danschneider@nvidia.com); GB10 resources: Riley (driley@nvidia.com). Event, Slack: Brett Storoe (storoeb@msoe.edu). Full table:
[docs/01-hackathon-overview.md](docs/01-hackathon-overview.md#who-to-ping).
