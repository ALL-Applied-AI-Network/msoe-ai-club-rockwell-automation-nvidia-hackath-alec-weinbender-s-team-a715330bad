# Project context

Living summary of where the project stands. Keep it short and current. Source documents live in [docs/](docs/README.md);
this file records what they mean for us. Gotchas and warnings: [docs/notes/things-to-know.md](docs/notes/things-to-know.md). Update it whenever a fact, decision, deadline or open question changes.

*Last updated: 2026-10-26 (evening: first Isaac runs on the M6 screw)*

## One-line pitch

**Auto-Grasp:** before a new part reaches the robot cell, it tells a factory whether it can grip the part reliably with
the fingers it already has, and if not, which finger to make. Every finger in the factory's library is simulated against
the part in the FANUC ER-4iA digital twin, at the part's candidate grasps and across the cell's grasp error, and ranked
by success rate. It evaluates fingers, not a grasp policy. If none is good
enough (the manufacturing engineer's call), Bayesian optimization generates a printable finger from a trusted family,
for one part or several, and it joins the library. Full use case:
[application-broad-overview.md](docs/application-broad-overview.md); user stories and the suggested first build:
[Auto-Grasp User Stories](<docs/Auto-Grasp User Stories.md>).

Until 2026-10-25 this was **CAD-to-Fingers** (the [team plan](docs/02-team-plan.md)): generate fingers for one part,
optimized to tolerate camera and calibration error, against the stock and imprint fingers. The pipeline below is still
that: it's the generation job. Since 2026-10-26 the backend also has the finger library, evaluation jobs and
qualifications (decision below), on the mock sim, and the frontend for them; multi-part generation isn't built.

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

2026-10-27 14:18 CDT: a full-grid cube16 BO/Sobol/GA comparison (32 candidates/method, seed 0, repeated validation)
completed successfully in `~/optimization-benchmark-20261027` on GB10 using the existing CPU simulator without restarting it.
Retrieved 2026-10-28: independent dense holdouts BO 92.31%, Sobol 91.18%, GA 91.04%; 96 candidates, 2 h 49 min.
One seed only; no proven improvement over Oliver's exact D1 or hardware validation.
[Results and commands](docs/experiments/2026-10-27-cube16-full-grid-comparison.md).
The completed comparison is preliminary; improvement over Oliver's exact D1 is not established.

2026-10-27 optimization tooling: the comparison runner supports the 16 mm cube, distinct-geometry finalists,
repeated selection means and independent holdout comparison. A bounded real CPU pilot completed for BO/Sobol/GA
(276 submitted grasps); all tied on its three-point diagnostic grid, so no full-grid improvement is claimed.
[Noise-aware benchmark log](docs/experiments/2026-10-27-noise-aware-benchmark.md).

2026-10-27 local setup: MICHAEL-SERVER now has passwordless GB10 access, and the app reaches the existing CPU/64-env
service (server archive 121b55d). Six current-client stock/imprint grasps passed with landing readouts. Local main was
fast-forwarded to 64c94a7, retaining the team's BO fixes and prior experiments; see the
[access/sync log](docs/experiments/2026-10-27-gb10-access-and-sync.md).

2026-10-22: A standalone BO/Sobol/genetic comparison runner is available with mock verification and a
[GB10 teammate runbook](docs/notes/benchmark-runbook.md). It does not change production algorithm selection.
See the historical [software experiment log](docs/experiments/2026-10-22-optimization-benchmark.md).

| Component | Path | State |
| --- | --- | --- |
| Web app backend (input flow, batch BO, results, tracker, exports; finger library, evaluation jobs, qualifications) | `app/backend/` | Works end-to-end with the **mock** sim, a geometric capture check (not physics): 1000+ tests, plus an end-to-end run against a live server with real worker processes. Evaluation jobs and the finger library (2026-10-26) have run on the mock only, in tests and the demo seed |
| Web app frontend (Auto-Grasp) | `app/frontend/` | Vite + React UI in NVIDIA Brev's colors (2026-10-22). The old single-file UI was removed on 2026-10-26: the React app is the page at `/` (the backend serves its build). Re-laid out as a dashboard on 2026-10-26: sidebar, Overview, Jobs, Part and Finger Libraries, new evaluations and their ranking. The quick logger is merged into Validation, and the review gate is now a Validation stage |
| Sim service (HTTP bridge to Isaac Sim) | `sim/sim_server/` | Contract v2: mesh parts, part friction, grip-force limit, transport, in-hand pose. **Runs in Isaac on Brev and the GB10** (2026-10-20). Stages 0–3 pass on both, and they agree ([Brev](docs/experiments/2026-10-20-brev-sim-server-bringup.md), [GB10](docs/experiments/2026-10-20-gb10-sim-server-bringup.md)). Stages 4–6 ran on the GB10 ([log](docs/experiments/2026-10-20-gb10-stages-4-6.md)): finger swaps, the in-hand readout, mesh parts and transport work. Heavy parts don't (risk 6), and the GPU path is biased (risk 7). 2.75 grasps/s reference, ~5 with CPU copies, 16–28 on the GPU. **Since 2026-10-26 the GB10 runs `main` (`121b55d`, with the landing readout) on `--envs 64 --device cpu`** (6.4 grasps/s on the screw). The screw has two generation jobs, two evaluation jobs, a reference-path repeatability check and 5 clips ([first runs](docs/experiments/2026-10-26-gb10-m6-screw-generation.md), [evaluation](docs/experiments/2026-10-26-gb10-m6-screw-evaluation.md), [landing check and reruns](docs/experiments/2026-10-26-gb10-landing-check-and-screw-reruns.md)) |
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
10. **The screw's sim results flip a lot between runs, because the fingers brush it** (GB10, 2026-10-26). Two runs of
    the stock fingers on the same 963-point grid agree on only 77–81% of points (the cube: 91–95%), with most flips
    past 4.5 mm. Scores move 1.4–2.3 points between runs, as much as the gap between the generated D1 and stock.
    - It's the part, not the vectorised path: the reference path (`--envs 1`) agrees with itself on 81.1%.
    - An untouched screw moves exactly 0. But the stock fingers move it in about 37% of grasps, differently each run
      (correlation 0.33). The shank sits snugly in the blades' round socket as they come down.
    - Scoring those landings as misses doesn't make the screw repeatable (78.5% agreement).
    - So gaps of a few points between fingers on the screw aren't real
      ([log](docs/experiments/2026-10-26-gb10-landing-check-and-screw-reruns.md),
      [first runs](docs/experiments/2026-10-26-gb10-m6-screw-evaluation.md)).
11. **The stock fingers grip past SMC's limit.** SMC's catalog limits the MHZ□2-16's gripping point L (with no
    overhang) to about 34 mm at 0.5 MPa and about 56 mm at 0.3 MPa or less. The stock blades grip about 70 mm out.
    Past the limit SMC says the gripper's life suffers; it doesn't say the grip fails. Grip force per finger,
    external: about 34 N at 0.5 MPa and 21 N at 0.3
    ([catalog](https://ca01.smcworld.com/catalog/en/rotary_airchuck/MHZ_2-E/6-3-p0381-0463-mhz_en/data/6-3-p0381-0463-mhz_en.pdf),
    pp. 387 and 395). A `max_finger_length_mm` from SMC would fail the stock fingers' own length.
12. **The twin gives the stock fingers more friction than a printed finger.**
    - The stock tips keep the twin's soft material: 1.5 static, 1.3 sliding.
    - A custom finger is sent with the part's estimated friction against printed PLA: 0.4 / 0.3 for the steel screw.
    - The server averages the two materials in contact, so on the screw stock grips at about 0.95 and a printed finger
      at 0.4. That's enough to hold a 7.5 g part either way, but it may help stock pull a part into a centred grip.
    - Neither number is measured: tilt-test the printed material, and check the real stock tips.
13. **For a part that fits the stock fingers, there's little left for a custom finger to win** (2026-10-26, the screw).
    - The Ø6 shank sits in the stock blades' sweet spot: 3–5 mm of room each side with the jaws open, and hooked tips that
      funnel it in.
    - The 6 mm stroke per jaw caps any finger's slack. Every good generated design pushed slack to its maximum (5.4–5.5 mm),
      the same wall the stock blades sit against.
    - A custom finger can only win on details, such as not brushing the part on the way down.
    - **Parts the stock fingers can't open around do show a generated finger's value.** On the 16 mm cube (2026-10-27),
      stock scores 0% and the best library finger 17.6%, while a generated D1 scores 92.3%, holding every grasp out to
      4.5 mm. Its results repeat within 0.03 points
      ([log](docs/experiments/2026-10-27-gb10-cube16-library-and-generation.md)).

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
| 2026-10-25 | Renamed CAD-to-Fingers to **Auto-Grasp**, with a broader use case: evaluate the factory's existing finger library against a new part first, let the manufacturing engineer decide (no fixed pass bar), then generate a finger (one part or several) that joins the library. Two users: manufacturing engineer and robotics engineer | Most new parts can run on fingers already on the shelf; generation is the fallback, and a growing library needs it less ([overview](docs/application-broad-overview.md), [user stories](<docs/Auto-Grasp User Stories.md>)) |
| 2026-10-26 | No grasp policy as an input. A cell is described by its **grasp accuracy** (the error model: spread in position and yaw, plus any consistent offset; presets or measured), and the sim keeps its scripted top-down pick. In library evaluation each finger is tried at the part's candidate grasps and scored at its best | The goal is the fingers' grasping ability. The error grid covers any pipeline that locates the part and then grasps it, which is honest; evaluating a specific VLM pipeline would need it run in the loop. Learned closed-loop policies are out of scope |
| 2026-10-26 | User stories scoped for the first build: flat table and top-down grasps stay (3, 4); bulk upload by files or a folder, no CSV (5); story 11 skipped; no target success rate in generation (14); real-robot validation is per finger-and-part pair (17). The app has a parts library and a finger library. Grasp accuracy is set on the cell profile and copied into each job. Evaluation is a new job kind | Team review of the stories against the backend ([stories](<docs/Auto-Grasp User Stories.md>), [plan](docs/notes/library-evaluation-backend-plan.md)) |
| 2026-10-26 | **Two kinds of job** share the jobs table, list, worker, cancel, resume and experiment IDs: generation (the optimizer) and evaluation (library fingers ranked on a part; its own trials table and `/ranking`). A library finger is a physical finger (stock, generated from a job's design, or uploaded CAD placed in the gripper frame automatically), tried on new parts through `regrip()` or `seat()`. Each finger is scored at its best of the top 3 grasp proposals per pose, and the top 3 fingers plus stock are re-tested on the dense grid. A qualification is one finger on one part: the latest prediction and the real-robot sessions, with the gap flagged outside the 95% Wilson interval. Migration 0007 adds the tables and clears nothing | A job is a scheduled run on the compute, whichever kind; evaluation is the new default path and generation the fallback ([plan, as built](docs/notes/library-evaluation-backend-plan.md#as-built-2026-10-26)) |
| 2026-10-26 | **A finger that lands on the part scores as a miss** (risk 5). The sim server reports `landing` per grasp: the part's shift in the table plane (mm) and its turn (degrees) from the end of the approach to the end of the descent, with the jaws still open. A grasp that moved the part more than 1 mm or 3° fails every task, even when the sim held it (`Outcomes.landed`, `Task.success`). Results and rankings say how many held grasps that turned into misses, or that it wasn't checked. Migration 0008 adds a nullable `landing` to both trial tables; old rows are unmeasured and keep their scores | The twin squeezes a part a finger landed on into the gap and calls it held, while a real arm may knock it away. Two runs of the stock fingers on the screw agree on only 77.5% of points, most flips at the outer offsets where the open fingers come down on the part (risk 10). A miss is the conservative choice, and the count shows how much it changes. An untouched part moves exactly 0 in Isaac (2026-10-26), so any motion is contact; whether a 1 mm / 3° brush knocks a real part away is still to check on the arm |

## Open questions / action items

- [x] **Backend of the user stories' first build** (2026-10-26, mock sim only;
      [plan, as built](docs/notes/library-evaluation-backend-plan.md#as-built-2026-10-26),
      [API](docs/notes/backend-api.md#finger-library-evaluation-jobs-and-qualifications)): grasp accuracy on the cell,
      bulk part upload, the finger library, evaluation jobs and their ranking, generation started from an evaluation,
      adding designs to the library, and qualifications per finger and part.
- [x] **Frontend for it (2026-10-26):** the Finger Library tab, bulk upload on the Part Library, the evaluation flow
      (part or parts, cell, fingers, review), the ranking page with its "generate a finger" button, and real sessions on
      a qualification.
- [x] **Run one evaluation job end to end on the GB10** (2026-10-26, EXP-0002, `--envs 64 --device cpu`): stock 88.6%
      over the imprint 76.0% on the M6 screw, in 495 s against a 415 s estimate
      ([log](docs/experiments/2026-10-26-gb10-m6-screw-evaluation.md)). Its re-run of the stock fingers is how risk 10
      was found.
- [x] **Fix the BO search's patience** (2026-10-26, `SearchPlan.stop_reason`). The Sobol start now only sets the best
      to beat, and BO gets `patience` designs of its own. EXP-0001 had stopped after 16 of 128 designs.
  - [x] Reran the screw's generation job (EXP-0004, 2026-10-26, landing rule on): 32 designs, stopped on patience.
        On the final grid stock scores 66.9% and D1 62.9%. D1 only matches or leads stock past 4.5 mm of error, by no
        more than the noise. **On the screw, the stock fingers stay**
        ([log](docs/experiments/2026-10-26-gb10-landing-check-and-screw-reruns.md),
        [chart](docs/experiments/2026-10-26-screw-success-vs-sigma-landing.png)).
- [x] **Measured the screw's repeatability on the reference path** (2026-10-26): 81.1% agreement on `--envs 1`, so
      risk 10 comes from the part, not the vectorised path.
- [ ] **Repeat the finalists' dense-grid test** (D1 and stock, two or three times) before claiming any gap on the screw
      smaller than about 3 points.
- [x] **Tried a part the stock fingers can't take** (2026-10-27, the 16 mm cube, EXP-0005 and EXP-0006):
      stock 0%, the library's best 17.6%, generated D1 92.3% (risk 13).
  - [ ] Measure the cube's material and mass at the cell. PLA (5 g) was assumed.
  - [ ] To validate it on the arm, add the cube to `cell_policy` (built for the screw now), and print D1 after the review
        gate.
- [ ] Second build: failure reasons per grasp and replays (story 13; plan W7), and the pitch metrics (W8).
- [ ] **Section grasps on the L-bracket have no buildable V-pad** (on `main` before 2026-10-26 too): its best grasp
      proposal grips one arm, and every V-pad design "would land on the centred part" there, so a generation job on it
      is blocked. The demo seed now uses its best whole-part grasp instead. Look at the search space's pad limits for
      section grasps (`models/search_space.py`).
- [ ] **Add height (z) error to the offset grid**, and probably tilt. The grid has dx, dy and yaw only, and the
      fingertips close 2.5 mm above the table, so height error is the likeliest real failure the sim never tests.
- [ ] Measure the real cell's grasp accuracy, to replace the placeholder presets (the default 3 mm sigma; risk 3).
- [ ] Log time from part upload to a qualified finger, and the share of parts that ran on existing fingers; the pitch's
      closing line needs those numbers.
- [ ] **Pick the demo part + task** sized for the jaws. Proposed 2026-10-20: **one M6 × 30 screw into the yellow bin**. It's
      a manufacturing part, the platform's default scene, light, and its Ø6 shank fits the jaws. The table camera
      can't see screws, so position error is large. `cell_policy/` is built for it. Team to confirm.
  - Since 2026-10-27 the simulations suggest showing **two parts**:
    - the screw, where the stock fingers are good enough and Auto-Grasp says not to print anything;
    - the 16 mm cube, where the library fails and a generated finger reaches 92%.
  - Only the screw is in `cell_policy` so far.
- [ ] **Confirm the finger mounting interface on the real jaw**: the STEP's tongue, its holes 4 and 11 mm below the
      shoulder, which way the screws go, and how the stock fingers sit (risk 8). Ask Zhen Zeng (zhenzeng@uwm.edu /
      `#dataset-3-grasping-sorting`), or photograph it at the cell.
- [ ] **Measure the stock fingers at the cell.** There is no CAD of them: the organizers couldn't find any (Slack,
      2026-10-26), and both arms have the same gripper and fingers. The app's library shows the twin's model of them
      (`api/models/finger.py`, `stock_blade`: 76 x 12 x 6 mm, an AA socket 6.97 mm above the tip, soft tips at friction
      1.5 / 1.3). Check the socket, the tip bevel and the soft tips against it in the first session.
- [ ] **Submit to the platform**: fill in `cell_policy/submission/submission.yaml` (team letter in `task_id`, contact),
      `uv run run.py --submit`, then book a slot in the dashboard's Calendar. The first real rollouts check the policy's
      jaw measurement (`cad2fingers_rollouts.jsonl`).
- [ ] Bring up the twin: `bootstrap.sh` host tests and the headless scene build pass on Brev and the GB10 (2026-10-20);
      the starter's stacking pipeline still needs a Cosmos env (optional for us).
- [x] Run the sim server on a GPU ([docs/notes/gpu-test-plan.md](docs/notes/gpu-test-plan.md)): stages 0–3 on Brev and
      the GB10, stages 4–6 on the GB10, and stage 7 (end to end with the app, plus the first Isaac Sim clips) on the GB10
      (2026-10-20, [log](docs/experiments/2026-10-20-gb10-app-end-to-end-and-clips.md)).
- [x] **Landing flag (risk 5): runs in Isaac** (GB10, `121b55d`, 2026-10-26).
  - Stage 4 passes: the flat pads push the cube by exactly the offset minus their slack, and the rule stops counting
    `pad_x0` from 3 mm and `pad_x2` from 5 mm.
  - An untouched part moves exactly 0, so the 1 mm / 3° thresholds sit well above the floor.
  - On the screw, the rule drops stock from 88.6% to 63.4% and the imprint from 76.0% to 49.1% (EXP-0003).
  - [ ] Whether a brush of that size knocks a real screw away: check it in the first real-arm session.
- [ ] **Find why the twin grips at about 2.5 N per jaw** (risk 6), then rerun GPU test plan 5.3–5.5. Meanwhile, pick a
      light demo part (under about 100 g).
- [ ] **Find the GPU-with-copies bias** (risk 7), starting with CCD; then rerun stage 6. Also run the L-bracket's
      reference grid twice, to know its own repeatability.
- [x] Real CAD export (CadQuery → STEP/STL) from the same pieces, with mount holes (2026-10-20). Since 2026-10-20 the mount
      follows SMC's STEP of the jaw. Confirm it on the real jaw and update the cell profile (`finger_mount`,
      `hole_clearance_mm`).
- [ ] Fill in the cell profile's *to confirm* fields: grip force at the cell's air pressure (SMC datasheet), max finger
      length, free space beside the gripper, table mat friction.
  - SMC's figures are in risk 11.
  - Proposed, not applied: `air_pressure_mpa` 0.5 (ask the cell), `grip_force_n` about 33 (a cap; the twin only
    reaches about 2.5 N), and `max_finger_length_mm` 76 (the stock length).
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
