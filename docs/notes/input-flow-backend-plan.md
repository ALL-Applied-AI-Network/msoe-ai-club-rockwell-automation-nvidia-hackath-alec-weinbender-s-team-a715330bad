---
title: Input flow and outputs backend: implementation plan
source: our own plan, from the "CAD-to-Fingers" input flow spec (revised), pipeline design and outputs spec (2026-10-19)
author: Alec Weinbender's Team
received: 2026-10-19
kind: note
status: IMPLEMENTED 2026-10-20; the API as built (and where it differs from this plan) is in backend-api.md
---

# Input flow and outputs backend: implementation plan

This plan is the contract the implementing agents share. If code and plan disagree, fix one of them; don't let them
drift.

**Scope:** the backend for the eight input steps, the outputs (job list, results page, results tracker, exports), and
the pipeline changes both imply. That means every Must and Should item in the two specs' priorities tables, with mesh
parts in the sim now.

**Out of scope (Later):**

- design-space cloud;
- imprint with clearance;
- optimizing over grasp axes;
- quick logger;
- across-experiments plot;
- Google Sheets sync and automatic logging;
- the results-summary PDF.

**Frontend:** the old single-form UI and its form endpoint are dropped. Whoever builds the wizard and the results pages
works from section 7.

**Starting point:** branch `batch-bo-sim-server`, plus the CadQuery agent's uncommitted work
([cadquery-design.md](cadquery-design.md)): finger solids and STEP/STL export, part import (`read_part` → `PartCad`,
with V-HACD pieces), and `cad_files`. All of it is kept, and its pending migration folds into 0003.

## 1. Decisions

| # | Decision |
| --- | --- |
| D1 | The stored upload is a **`PartRecord`** at `/api/parts`. **`Part`** keeps its name and means the part as the gripper meets it: posed and rotated to the grasp axis. It's what the fingers, the mock and the sim see. |
| D2 | **Closed gap is reported per design, not searched** (agreed). The V-pad already offsets its pads (face = slack + width/2 − stroke), so wide parts fit. |
| D3 | **Each family's parameters are a pydantic model** (`VPadParams`), and `Design` carries typed params instead of `dict[str, float]` (requested). Range and lock keys are checked against the model's fields. |
| D4 | **Raw outcomes are stored per design**, as arrays on the trial row: held, in-hand pose, held after transport. There's one row per design per grid (search or final). Scores for other sigmas, biases, tasks or tolerances are recomputed on request. There is no Score table and no row per grasp. |
| D5 | The **in-hand pose** is relative to the *commanded* gripper frame at the end of the lift: dx, dy and dz in mm, tilt and yaw in degrees. Offset = 3D distance from the centred position. |
| D6 | **Transport:** a 0.12 m move along base +X (across the jaws) in 1.2, 0.6 or 0.3 s (slow, normal, fast), then 0.5 s of settle. Held after transport = the part is still more than 25 mm up. |
| D7 | **Friction:** each material has one pair coefficient against the printed pad (appendix A, estimates), scaled by the surface option. The sim puts the same pair on the part and on the fingers, so it comes out exact under any combine mode except multiply. |
| D8 | **Grip force:** the twin's jaw drive allows 180 N. The profile's grip force starts empty and *to confirm*, and while it's empty the twin's drive is used. A fragile part's max force caps whatever is sent. |
| D9 | **Budget: 128 designs** for every batch-BO family search (agreed), with 2d + 4 initial designs. Sobol sweeps: 16 at d = 1, 32 at d = 2. A single evaluation at d = 0. The user can override the budget. |
| D10 | **Error presets:** 0.19 mm / 0.5°, 1 mm / 3°, 3 mm / 8°, 5 mm / 12°. Everything except the twin's 0.19 mm is marked as a placeholder. |
| D11 | **Primitive vs mesh** is decided on the convex hull. A box or cylinder hull becomes that exact primitive: the cup-shaped vial cap is a cylinder. Anything else is a mesh of V-HACD pieces, labelled approximate. |
| D12 | The **cell profile drives finger geometry and CAD**: stroke, free space, mount features, hole clearance, max finger length. The sim models the twin's SMC gripper, and a job whose profile doesn't match the twin gets a warning. Physics dt, solver iterations and the environment count stay sim-server flags. The server reports them, and the job records them. |
| D13 | **Migration 0003 clears existing jobs**, as 0002 did. |
| D14 | **Experiment ID:** `EXP-0001` and up, from a counter column, fixed for life. The name can be renamed. Exported file names start with `<slug(name)>_<EXP-id>`. **Duplicate** returns a copy of the job's spec named "… (copy)" for the wizard to edit. It doesn't start a run. |
| D15 | **Design labels:** after the final test, the non-baseline designs are labelled `D1`, `D2`, … by final score. The baselines are `STOCK` and `IMP`. A printed finger's ID is `<EXP-id>-<label>-<L\|R>`, and it's engraved, not embossed: 0.4 mm deep, so it can't touch anything. |
| D16 | **A manual grasp gets a geometry check only**, not a sim check (an open question in the spec; this is the cheap answer for Nov 1). |
| D17 | **Test plans:** a job can have several. Trial IDs (`T0001`, …) are unique per job. Logged physical trials reference (plan, trial ID). A re-upload overwrites a trial and appends the old value to its history. The sim predicts every planned row in the worker before anyone tests. |

## 2. Frames

| Frame | Definition | Used by |
| --- | --- | --- |
| CAD frame | the file as authored, mm (an STL in inches is scaled on upload), centred in x and y, base at z = 0 | `PartRecord.measured` |
| Table frame | CAD frame × the chosen `RestingPose` rotation, then re-centred: resting on z = 0, footprint centred | thumbnails, grasp step, face picks |
| Grasp frame (= gripper frame G at the grasp) | table frame rotated by −θ about z (θ = closing direction), shifted so the grasp centre is the origin | `Part`, fingers, mock, sim, offsets, in-hand pose |

## 3. Domain models (`api/models/`)

Phase 0 writes these, so their fields are fixed before any agent starts. Functions marked *(stub)* raise
`NotImplementedError` until their workstream fills them in.

- **`family.py`**
  - `VPadParams`: `family: Literal["vpad"]`, pad_width_mm, groove_angle_deg (default 180), groove_depth_mm (default 0),
    slack_mm, tip_height_mm, lead_in_mm (default 0). Every field carries its description.
  - `FamilyParams`: the union of built families' params (just `VPadParams` for now).
  - `ParamRange` (lo, hi).
  - `FamilyChoice`: family, ranges, locks. Validated against the params model.
  - `FAMILIES` registry: vpad built; imprint planned; cradle planned, lying cylinders only.
- **`design.py`: `Design`**: kind (search | locked | stock | imprint), params `FamilyParams | None`, `family` property.
- **`part.py`: `Part`**
  - shape is cylinder | box | mesh.
  - Cylinder `axis`: z, y or x (replaces `upright`).
  - `pieces` for a mesh, in the grasp frame.
  - mass_g, `friction`.
  - Properties: `extent_mm` and `round_from_above`.
- **`material.py`**
  - `Material` and `Surface` literals.
  - `MATERIALS`: density and pad friction for each material.
  - `pair_friction(material, surface)`.
- **`part_record.py`**
  - `PartMeasurement`: extent_mm, volume_mm3, centre_of_mass_mm, face_types, material_hint, pieces (CAD frame).
  - `PartRecord`
    - Identity: id, created, name, file_path, source, units, measured.
    - Material: material, density_g_cm3, surface.
    - Mass: mass_g, mass_source, mass_unit.
    - Handling: fragile, max_grip_force_n, clearance_mm.
    - pose.
    - `computed_mass_g`, `friction`.
- **`resting_pose.py`**: `RestingPose` (rotation 3×3, label, source, probability, extent_mm). `resting_poses()`
  *(stub, B)*.
- **`grasp.py`**
  - Models:
    - `GraspCandidate`: angle_deg, centre_mm, width_mm, contact_area_mm2, opposition_deg, parallel_faces,
      com_offset_mm, fits, stock_fits, verdict (ok | warn | blocked), warnings, blocked_reasons.
    - `GraspProposals`: candidates, rejected, nothing_fits.
    - `GraspPick`: a point and normal.
    - `GraspChoice`: angle_deg, centre_mm, source (auto | manual), grip_height_mm.
  - Functions *(stub, B)*: `propose_grasps()`, `check_grasp()`, `posed_part()`, `table_mesh()`.
- **`cell_profile.py`**
  - `FingerMount`
    - holes: x, z, diameter, and counterbore diameter and depth;
    - locating features: pin or slot, with x, z, diameter and length;
    - mount face size.
  - `CellSimSettings`.
  - `Gripper`
    - stroke per jaw;
    - blade x, y, z;
    - mount (kept length);
    - free space x and y;
    - pad friction;
    - jaw open gap at the tips;
    - TCP.
  - `CellProfile`
    - robot, tcp_mm, gripper model;
    - stroke, grip force, air pressure;
    - finger mount, hole clearance, stock fingers;
    - max finger length;
    - free space, approach and lift;
    - pad friction, mat friction;
    - cameras;
    - sim settings;
    - `to_confirm`;
    - the `gripper` property.
  - `DEFAULT_PROFILE` ("UWM CSI cell").
- **`task.py`**: `Task` (kind, offset_tolerance_mm, tilt_tolerance_deg, transport). `Task.success(outcomes)` is written
  in phase 0.
- **`error_model.py`**: `ErrorModel` (preset, sigma_mm, sigma_range_mm, sigma_deg, bias_mm, bias_direction_deg) and
  `PRESETS`.
- **`outcome.py`**: `Outcomes`, per design: held, in_hand (`[dx, dy, dz, tilt, yaw] | None` per point),
  held_after_transport.
- **`search_plan.py`**
  - Models:
    - `ParamSummary`: per parameter: default range, user range, effective range, lock, note.
    - `SearchConfig`: key, family, free, locked, method, n_initial, budget, batch_size, patience.
    - `JobPlan`: part, families, searches, grid, final_grid, totals, estimate, warnings, sim backend.
  - `plan_job()` *(stub, C)*.
- **`job.py`**
  - `JobSpec`: name, part_id, cell_profile_id, task, grasp, families, error, budget, seed.
  - `Job`
    - identity: id, experiment_id, name;
    - status: queued, running, finalizing, done, failed, cancelled, interrupted;
    - part_id, cell_profile_id, sim_backend (mock | isaac);
    - spec, part, plan;
    - progress: n_done, n_total, round, n_rounds;
    - best_value, best_trial;
    - failure: error (traceback), failure (one line), failed_step;
    - control: cancel_requested, pid;
    - finished, duplicated_from, print_designs.
  - `Trial`: number, round, search, grid, kind, label, params, success_rate, capture_radius_mm, n_grasps, held,
    in_hand, held_after_transport.
  - `JobResult`: winner label, trial, design, grasp pose, predicted success, capture radius, export files, export checks.
- **`printed_finger.py`**: `PrintedFinger` (id, job_id, finger_id, design_label, side, material, print_date, notes).
- **`test_plan.py`**
  - `TestPlanRow`: trial_id, design_label, finger_id, kind (pointwise | random | extra), offset, repeat, predicted,
    predicted_in_tolerance.
  - `TestPlan`: id, job_id, seed, designs, rows, prediction_status.
- **`physical_trial.py`**: `PhysicalTrial` (job_id, plan_id, trial_id, design_label, finger_id, offset, repeat,
  outcome held | missed | skipped, in_tolerance, notes, video_link, operator, timestamp, history).

## 4. Pipeline

### 4.1 Part (input steps 1–2), workstream B

**Upload (`read_part`, extended in phase 0):**

- STEP: centre of mass, face-type counts, and a material hint from the file text.
- STL: `units` is required; inches are scaled ×25.4.
- SolidWorks files (`.sldprt`, `.sldasm`, `.slddrw`) get 415 with "In SolidWorks: File > Save As > STEP."

**Store:** the file and `mesh.npz` under `uploads/part_<id>/`, and the record. Pieces are computed once, in the CAD
frame; every later pose or axis only transforms them.

**Mass:** computed = volume × density. `PATCH` can take a measured mass instead, and records which one is used.

**Resting poses:** `trimesh.poses.compute_stable_poses` on the mesh. Poses with the same footprint and height are merged
(a cylinder's 48 side facets become one "on its side"). The top 4 are kept, plus "as in the CAD file". Labels are
standing, on its side, lying flat, standing on an end and lying on its side.

### 4.2 Grasp axis (input step 5), workstream B

**Inputs:**

- the mesh in the table frame and its centre of mass;
- the half-angle α = atan μ (μ = the pair friction);
- the gripper limits: widest part = 2 × (free space x − pad wall − minimum slack), and the stock opening.

**Auto proposal:**

1. Sweep θ from 0 to 179° in 1° steps. Width = the extent along u over z ≥ 1 mm.
2. Patches = the faces within max(0.3 mm, 2% of the width) of each extreme, with normals within α of ±u.
3. Centre = the u-midpoint, and along v the centre of mass clamped to where both patches exist. The clamp distance is
   `com_offset_mm`.
4. Keep θ if both patches have at least 1 mm² and the width fits.
5. Group neighbouring θ that touch the same faces. Each group's representative is the θ with the most contact area.
6. Rank: parallel flat faces (≤ 2°) first, then contact area, then narrower width. Return the top 3.
7. A part that's round from above returns one candidate, "any direction works".
8. Count rejections by the first rule each fails.

**Warnings (never blockers):**

- faces more than 10° from parallel;
- off-centre: more than max(2 mm, 10% of the depth);
- the stock fingers can't open wide enough, so the stock baseline will score 0.

**Nothing fits:**

- the reason, with numbers;
- then suggestions in the spec's order, each backed by a check:
  1. offset fingers;
  2. another resting pose (name it);
  3. a narrower feature, from trimesh sections ("z 4–9 mm is 11.2 mm wide");
  4. an internal grip (the part is hollow, open at the top, and its volume is under 60% of its hull's);
- otherwise "needs a longer-stroke gripper or a suction cup".

**Manual choice:**

- Input is an `angle_deg`, or one or two picks in the table frame.
- One pick: θ comes from the face's horizontal normal (|n_z| < 0.7); a ray along −n finds the opposite face.
- Two picks: θ comes from the line between the points.
- Same checks. A width that doesn't fit, or no material at an extreme, is **blocked**. Non-parallel faces, an
  off-centre grab, or a pick that isn't the first touch is a **warn**.

**Locking grip height:** `grip_height_mm` locks `tip_height_mm` in every family.

**`posed_part(record, grasp) → Part`:**

- pose → −θ → centre;
- classify by the hull:
  - a box if it's within 2% of its bounding box;
  - a cylinder (axis z, y or x) if a silhouette is round and the hull is within 3% of πr²L;
  - otherwise a mesh;
- mass and friction come from the record.

### 4.3 Design space (input step 6), workstream C

- **`SearchSpace(part, choice, gripper, clearance_mm)`** keeps the coupled unit-cube mapping over the free fields of the
  family's params model.
- **Ranges:** user ranges are intersected with the feasible range at each sample. Locked fields drop out of the cube and
  are clipped into the feasible range.
- **Clearance caps:** pad width ≤ depth + 2 × clearance, and slack + groove depth + lead-in + wall ≤ clearance.
- **`describe()`** returns a `ParamSummary` per field.
- **Finger geometry takes a `Gripper`.** Today's constants become its defaults, and the mock gets overlap checks for mesh
  parts.
- **Each design reports its closed gap**, 2 × the face position with the jaws closed.
- **Preview:** the min and max ghosts for one parameter (the others at 0.5 in the cube), or explicit designs.

### 4.4 Search setup (input steps 6–8), workstream C

**Method:** see D9.

**Batch size:** q = clamp(round(10 × envs ÷ offsets ÷ number of searches), 4, 32), capped so at least 4 learning rounds
remain.

**Stopping:** a search stops after no 0.005 gain over its last 3d designs, or when its budget is spent.

**Final test:** the top 3 of each search, plus stock, imprint and any locked designs, on the dense grid.

**Time estimate:** grasps ÷ measured throughput (the median over recent rounds on the same backend and environment
count). When nothing has been measured, the estimate is "unknown", or `SIM_GRASPS_PER_S` if it's set.

### 4.5 Error model and scoring (input step 7), workstream C

- **Weights**
  - No bias: today's exact masses.
  - With bias: each cell's mass under N(bias, σ²I), by Gauss–Legendre quadrature over its annular sector.
  - Designing for a range: the mean over 6 sigmas spread across the range.
- **Warning:** bias + 2σ beyond the outer ring.
- **Grid preview:** points, weights, the 1σ and 2σ circles, the yaw layers and warnings.
- **Per design**
  - expected success;
  - capture radius, by task success;
  - curve at σ = 0.5, 1, 2, 3, 4 and 5 mm.

### 4.6 Printable CAD (outputs), workstream E

- **Bodies:** both fingers, left and mirrored right, as separate bodies.
- **Files:** a STEP of the pair, and one STL per finger.
- **From the cell profile:**
  - mount holes, with diameter + `hole_clearance_mm` (default 0.25, a profile setting);
  - counterbores;
  - locating pins (bosses) or slots (cuts);
  - the mount face.
- **Engraved ID:** `<EXP>-<label>-<side>`, 0.4 mm deep, on a non-contact face of the blade, below the mount holes, with
  each side's text reading correctly. With no room or no font, the check says so and the file is still written.
- **Checks before export.** A failure blocks the download, with the check's name and numbers:
  - the solid is valid and closed;
  - its volume and bounding box match the sim pieces (within 0.5%, after allowing for the holes and text);
  - minimum wall 1.2 mm, flagging groove shoulders and thin walls;
  - total finger length ≤ the profile's max (skipped, and noted, while that's still to confirm).
- **Print sheet (PDF, fpdf2):**
  - orientation: lying on the face opposite the pad, so the pad and groove face up with no supports;
  - material (matching the friction assumed in the sim), infill and walls;
  - print time and filament left blank;
  - the finger ID and the mount-confirmation caveat.

### 4.7 Optimizer, jobs and results (outputs), workstream F

- **Rounds:** each round is one sim request, carrying every active search's batch; round 0 adds the baselines and locked
  designs. Each round is checkpointed in one transaction.
- **One GP per search**, falling back to Sobol for that round if the fit fails.
- **Statuses:** queued → running → finalizing → done. A failure stores the traceback plus a one-line `failure` and a
  `failed_step` (the input step to fix, e.g. 5 when no grasp fits).
- **Sent with every batch:** `grip_force_n` (the lesser of the profile's and the part's, when either is known) and
  `transport`.
- **Finalize**
  - The final-grid trials (labelled D1 and up, STOCK, IMP), the result and the D1 CAD are written together.
  - The winner has the best target score; capture radius breaks ties.
  - Run metadata: versions, GPU, grids, seed, sim backend and its `describe()`, cell profile version, plan, and the
    stop reason per search.
- **Results view (`GET /api/jobs/{id}/results`, and `POST /rescore` with other error or task inputs)**
  - header;
  - summary: best vs stock and imprint at the target, with predicted success, capture radius, task metric and designs
    evaluated;
  - curves;
  - held maps (best and stock on the final grid);
  - in-hand histogram (place and insert);
  - where it fails: missed directions and distances, plus caveats;
  - best finger: params, grasp pose text, files;
  - final test table;
  - physical validation summary (from G);
  - run details: search progress (best vs designs evaluated), budget, batch, rounds, stop reasons, error model,
    versions, GPU, seed.
- **Job list (cards)**
  - name and ID, part, task, badge, status;
  - while running: round x of y, designs evaluated out of the budget, best so far;
  - when done: winner vs stock;
  - when failed: the failure line and the step to fix;
  - the physical badge (none, in progress, validated, from G);
  - filters (part, status, backend), newest first.
- **Exports:** grasp pose (JSON and text), run metadata JSON, and `trials.jsonl` (with backend, search, label and the
  raw outcomes).

### 4.8 Results tracker (outputs), workstream G

- **Print selection:** choose designs from the final table; stock and imprint are always included.
- **Printed fingers:** record each one (finger ID, design, side, material, print date, notes).
- **Test plan generation, per selected design:**
  - 25 point-wise offsets (centre; ±dx and ±dy at 1, 2, 3, 4 and 6 mm; diagonals at 3 mm), × 3 repeats;
  - 30 seeded random offsets drawn from the job's error model, including bias and yaw.
- **Prediction:** the worker sims every unique (design, offset) and stores, for each row, whether it's held and whether
  it's in tolerance.
- **Spreadsheet round-trip**
  - Download as XLSX (outcome and in-tolerance dropdowns, predicted column hidden) or CSV, with the spec's columns.
  - Upload:
    - rows are matched by `trial_id`;
    - unknown IDs are rejected with the row number and reason;
    - blank outcomes stay pending;
    - a re-upload overwrites and keeps history;
    - new rows with a design and offset become extra trials;
    - a blank timestamp is filled in on upload.
- **Views (`GET /api/jobs/{id}/validation`)**
  - per design: predicted vs measured success on the plan, the 95% Wilson interval, and agreement ("22 of 25 offsets");
  - mismatch map: per offset, agreed, sim-only success, or real-only success;
  - curve overlay: measured success on the random rows, with its Wilson interval, at the target sigma;
  - the badge: none yet, in progress, or validated.
- **Exports:** `physical.jsonl` and CSV, and test plans as XLSX and CSV.

### 4.9 Mock sim, workstream D

Geometry only, and badged Mock everywhere. In-hand estimates:

- dx → 0;
- dy stays at the offset's dy for flat pads, and → 0 for a groove on a round part within its capture;
- yaw → 0 for a box between flat pads within 25°;
- tilt and dz are 0.

Held after transport = held.

## 5. Sim contract v2 (`POST /evaluate_batch`), workstream A

**Request:**

```text
part: shape "cylinder" | "box" | "mesh"
      cylinder: diameter_mm, length_mm, axis "z" | "y" | "x"   ("upright" still accepted)
      box: box_mm [x, y, z]
      mesh: pieces [{points, triangles}]   grasp frame, mm, origin on the table under the grasp centre
      mass_g
      friction [static, dynamic] | null    null = the twin's part material (0.9 / 0.8)
designs, offsets: unchanged
grip_force_n: float | null                 per-jaw force limit on the jaw drive; null = the twin's 180 N
transport: null | "slow" | "normal" | "fast"
```

**Response:**

```text
held: [[bool]]
in_hand: [[[dx_mm, dy_mm, dz_mm, tilt_deg, yaw_deg] | null]]   end of the lift, vs the commanded gripper frame
held_after_transport: [[bool]] | null
sim: {envs, device, physics_dt, friction_combine, ...}
```

**Server changes:**

- **Mesh parts:** one rigid body, with one `convexHull` collider per piece. The pieces are recentred to mid-height.
- **Cylinder axis x.**
- **Part friction:** a per-request part material.
- **Grip force:** `Articulation.set_max_efforts` on the jaw DOFs.
- **Transport segment** in `robot/motion.py`.
- **In-hand pose:** an Isaac-free function in `robot/poses.py`.
- **Updated:** the example batches, `send_batch.py`, the GPU test plan and the host tests.

Nothing Isaac-side can be checked without a GPU. Each piece of code says so, and the GPU test plan gets the steps to
check it.

## 6. Database (migration 0003)

**New tables:**

- `parts`;
- `cell_profiles` (unique on name and version; a job points at the exact version);
- `printed_fingers`;
- `test_plans` (rows stored as JSON).

**Rebuilt empty:**

- `jobs` gains experiment_number (unique), experiment_id, name, part_id, cell_profile_id, sim_backend, spec, plan,
  round, n_rounds, failure, failed_step, duplicated_from and print_designs.
- `trials` gains search, grid, label, in_hand and held_after_transport.
- `results`: cad_files and checks.
- `physical_trials` is redone per section 3: unique on (job_id, trial_id), with history.

The reviews table is cleared.

## 7. API (the contract for the frontend)

| Area | Method and path | Body → response |
| --- | --- | --- |
| Step 1 | `POST /api/parts` | multipart: `part_file`, plus `units` (required for STL) → the record. 415 for SolidWorks files, 422 for unreadable ones |
| Step 1 | `GET /api/parts`, `GET /api/parts/{id}` | records |
| Steps 1–2 | `PATCH /api/parts/{id}` | material, density, surface, mass_g (null = computed), mass_unit, fragile, max_grip_force_n, clearance_mm, pose (an index or "as_authored") |
| Step 2 | `GET /api/parts/{id}/poses` | the top 4 stable poses + as authored |
| Steps 2, 5 | `GET /api/parts/{id}/mesh?pose=` | binary STL in the table frame |
| Step 4 | `GET/POST /api/cell-profiles`, `GET/PUT /api/cell-profiles/{id}` | PUT makes a new version and returns its id |
| Step 5 | `POST /api/parts/{id}/grasps`, `POST /api/parts/{id}/grasps/check` | proposals; a checked manual choice |
| Step 6 | `POST /api/fingers/preview` | `{part, cell_profile_id, choice, vary? \| designs?}` → pieces, problems, closed gap |
| Step 7 | `POST /api/grids` | `{part, error, final?}` → points, weights, circles, warnings |
| Steps 6–8 | `POST /api/jobs/plan` | `JobSpec` → `JobPlan`; stores nothing |
| Step 8 | `POST /api/jobs` | `JobSpec` → `{id, experiment_id, name}`; 422 with reasons if blocked |
| Jobs | `GET /api/jobs?part_id=&status=&backend=`, `GET /api/jobs/{id}/events` | cards; SSE of card fields |
| Jobs | `PATCH /api/jobs/{id}` (rename), `POST /api/jobs/{id}/duplicate` (→ spec), cancel, resume | |
| Results | `GET /api/jobs/{id}/results`, `POST /api/jobs/{id}/rescore` | the results view (4.7) |
| Results | `GET /api/jobs/{id}/finger?design=` | the pair's pieces, for the 3D preview |
| Results | `GET /api/jobs/{id}/designs/{label}/cad?format=step\|stl&side=L\|R`, `/checks`, `/print-sheet.pdf`, `/grasp-pose?format=json\|text` | 409 + the failed checks if the export is blocked |
| Results | `GET /api/jobs/{id}/run-metadata.json`, `GET /api/export/trials.jsonl?job_id=` | |
| Tracker | `PUT /api/jobs/{id}/print-selection`, `GET/POST /api/jobs/{id}/printed-fingers` | |
| Tracker | `POST /api/jobs/{id}/test-plans`, `GET /api/jobs/{id}/test-plans[/{plan_id}]`, `GET …/{plan_id}.xlsx\|.csv`, `POST …/{plan_id}/upload` | the upload returns accepted, pending and row errors |
| Tracker | `POST /api/jobs/{id}/physical`, `GET /api/jobs/{id}/validation`, `GET /api/export/physical.jsonl\|.csv?job_id=` | |
| Catalog | `GET /api/meta` | materials, surfaces, families with field schemas, error presets, task kinds, sim backend |
| Kept | review (the safety gate) | |

## 8. Workstreams

**Phase 0, foundation (me):**

- the section 3 models;
- `Task.success` and the small pure helpers;
- `tables.py` and migration 0003;
- the SimClient v2 protocol;
- the CadClient protocol v2, with `read_part` extended;
- `finger.py` split into geometry (`finger.py`) and printable solid (`finger_cad.py`);
- every new router module registered in `main.py` as an empty stub;
- dependencies added (trimesh, openpyxl, fpdf2);
- conftest moved to CadQuery.

**Phase 1, five agents in parallel, each owning disjoint files:**

| Agent | Owns | Delivers |
| --- | --- | --- |
| A: sim server | `sim/sim_server/**`, `sim/README.md`, `docs/notes/gpu-test-plan.md` | Section 5 |
| B: part pipeline | `models/part_cad.py`, `resting_pose.py`, `grasp.py`, `part_record.py` (functions), `services/parts.py`, `routers/parts.py` | Sections 4.1–4.2 |
| C: design space and scoring | `models/finger.py`, `search_space.py`, `offset_grid.py`, `error_model.py`, `search_plan.py`, `routers/fingers.py`, `routers/grids.py` | Sections 4.3–4.5 |
| D: profiles and sim client | `services/cell_profiles.py`, `routers/cell_profiles.py`, `clients/sim.py`, `routers/meta.py` | Profile CRUD and seeding, the v2 mock and HTTP client (4.9), the catalog |
| E: printable CAD | `models/finger_cad.py`, `clients/cad.py` (export side), `models/export_check.py`, `models/print_sheet.py` | Section 4.6 |

**Phase 2, two agents in parallel:**

| Agent | Owns | Delivers |
| --- | --- | --- |
| F: optimizer, jobs, results | `services/optimizer.py`, `services/jobs.py`, `services/results.py`, `routers/jobs.py`, `services/export.py`, `routers/export.py`, `worker.py` | Section 4.7 |
| G: results tracker | `services/test_plans.py`, `services/physical_trials.py`, `services/printed_fingers.py`, `routers/test_plans.py`, `routers/physical_trials.py`, `routers/printed_fingers.py`, the spreadsheet I/O | Section 4.8. F's worker calls G's `predict_test_plan` |

**Phase 3, integration (me):**

- the full suite and ruff;
- an end-to-end mock run through the API: generated STEP → pose → grasp → plan → job → results → rescore → print
  selection → test plan → spreadsheet round-trip → validation;
- a review agent;
- docs: an API page, CONTEXT.md, things-to-know, app/README;
- one commit.

**Rules for every agent:**

- Edit only owned files; ask through the report if something else needs changing.
- Run your own tests, plus `ruff format` and `ruff check` on your own files.
- Never edit the vendored twin.
- Mock stays the default.
- Make no claims about Isaac behaviour.
- Don't commit.

## 9. What gets validated where

| Area | Checked by |
| --- | --- |
| Backend | pytest, offline, with the mock and CadQuery-generated parts (cube, cylinder, cup-shaped cap, L-bracket, a part too wide) |
| Sim server | host tests: contract, conversion, motion with transport, in-hand math, mesh payloads |
| Isaac behaviour | **Not validated** until the GPU test plan runs on Brev or the GB10 |

## Appendix A: material estimates (to measure with a tilt test)

| Material | Density (g/cm³) | Friction vs printed PLA pad (static / dynamic) |
| --- | --- | --- |
| Glass | 2.50 | 0.40 / 0.30 |
| PLA | 1.24 | 0.50 / 0.40 |
| ABS | 1.05 | 0.50 / 0.40 |
| Aluminium | 2.70 | 0.45 / 0.35 |
| Steel | 7.85 | 0.40 / 0.30 |
| Rubber | 1.10 | 0.90 / 0.80 |
| Other | user-entered | 0.60 / 0.50 (the profile's pad friction) |

Surface factor: smooth ×1.0, oily ×0.5, textured ×1.2.
