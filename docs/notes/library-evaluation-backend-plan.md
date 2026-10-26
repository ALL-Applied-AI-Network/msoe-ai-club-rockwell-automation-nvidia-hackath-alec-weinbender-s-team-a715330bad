---
title: "Finger library and evaluation backend: implementation plan"
source: our own plan, from the Auto-Grasp user stories and the backend gap review (2026-10-26)
author: Alec Weinbender's Team
received: 2026-10-26
kind: note
status: "FIRST BUILD IMPLEMENTED 2026-10-26 (W1-W6, W9); W7, W8 not started. The API as built is in backend-api.md"
---

# Finger library and evaluation backend: implementation plan

This plan covers the backend for the new direction in
[Auto-Grasp User Stories](<../Auto-Grasp User Stories.md>):
1. Evaluate a new part against the fingers a factory already has.
2. Generate a finger only when none of them is good enough.
3. Check each finger-and-part prediction on the real robot.

It builds on the backend as it is today ([backend-api.md](backend-api.md),
[input-flow-backend-plan.md](input-flow-backend-plan.md)). If code and plan disagree, fix one of them.

## As built (2026-10-26)

The first build (W1–W6 and W9) is in the backend, tested on the mock sim only. The API as built, screen by screen, is
the last section of [backend-api.md](backend-api.md#finger-library-evaluation-jobs-and-qualifications). Where the
build differs from the plan below:

- **Two kinds of job (L6), as planned:** `jobs.kind` is `generation` (the optimizer) or `evaluation`. An evaluation job's
  trials have their own table (`evaluation_trials`) rather than new columns on `trials`, so nothing that reads a
  generation job's trials changed. Its results are `GET /api/jobs/{id}/ranking`. `/results` and the designs' routes
  answer 409 for an evaluation job, and `/ranking` answers 409 for a generation job.
- **Comparing a new finger with the library (L14):** `compare_fingers` wasn't built; the optimizer is unchanged. To
  compare, add the new design to the library, then run the evaluation again (`POST /api/jobs/{id}/duplicate`). That
  ranks it with the existing fingers on the same grid and grasps.
- **Finger preview:** `GET /api/fingers/{id}/geometry` returns the finger's convex pieces in G, as the design previews
  do, rather than an STL.
- **Decided:**
  - Q1: no confidence range on sim results (L11).
  - Q2: uploaded fingers are auto-placed, with `mirror` and `upside_down` options.
  - Q3: uploaded fingers grip at 2.5 mm, or at the grasp's locked height.
  - Q5: the cell's stock fingers are always in an evaluation, also when fingers are chosen.
  - Q6: the top 3 non-blocked proposals per pose (`EVAL_GRASPS`).
- **Q4 and Q7 stand as recommended:**
  - one finger, mirrored for the other jaw;
  - sessions have a `kind`, `natural` or `commanded`.
- **Found while building, already on `main`:** the demo seed's L-bracket job was blocked. Its best grasp proposal grips
  one arm (a section grasp), and the V-pad family has no buildable design for that section. The demo now uses the best
  whole-part grasp; the bug is an open item in CONTEXT.md.
- **Not done:**
  - W7 (failure reasons, replays) and W8 (metrics);
  - the frontend: a Fingers tab, the evaluation flow and the ranking page. The typed client (`schema.d.ts`) is
    regenerated, and the wizard sends `kind: "generation"`;
  - any run on Isaac (section 9).

**Scope, first build:**

| Story | What | Starts from |
| --- | --- | --- |
| 1, 5 | Part upload, one file or many (or a folder), with a part number and an intake status | `/api/parts` upload |
| 7, 8 | A finger library: register, browse and filter fingers | new |
| 9 | Grasp accuracy saved on the cell profile | the error model, per job today |
| 10 | Evaluation jobs: rank every compatible finger on a part | new job kind |
| 12 | Evaluation results: ranked, with the grasps simulated and a "generate" option | new view |
| 14 | Generation, linked to the evaluation it came from | the existing optimizer |
| 16 | Add a generated design to the library | the existing export |
| 17 | Real-robot validation per finger and part | new; the per-job tracker stays |

**Second build:** story 13: failure reasons per grasp and replays of failed trials. Also the pitch metrics (time
from upload to a qualified finger, and the share of parts that run on existing fingers).

**Not in this plan:**
- **3, 4:** flat table, top-down approach. Already built; kept as is.
- **6:** more cells. Cell profiles already exist; the sim still models only the SMC cell.
- **11:** re-evaluation. Skipped.
- **15:** multi-part generation. Later.
- Height and tilt error in the offset grid.
- Presentation in bins, trays or fixtures.
- Keep-out zones.

**Frontend:** the new UI gets a **Fingers** tab next to **Parts**. It also needs an evaluation flow (part or parts,
cell, fingers, review) and an evaluation results page. Section 5 is the contract for both.

## 1. Decisions

| # | Decision |
| --- | --- |
| L1 | **Two libraries, one pattern.** Parts (`PartRecord`, `/api/parts`, exists) and fingers (`FingerRecord`, `/api/fingers`, new). Each is a stored record, reused across runs. A job snapshots what it uses at creation, so later edits never change old results. |
| L2 | **A `FingerRecord` is a physical finger, not a design.** Its geometry is absolute, in the gripper frame G of [finger.py](../../app/backend/src/api/models/finger.py): jaws closed, fingertips at z = 0, the other finger mirrored in x. It's stored as convex pieces, the form the sim and the mock already take. There are three sources:<br>- **stock**: the cell's own fingers. The sim uses its real model, as today.<br>- **generated**: a final design from a generation job, stored as the `Part` it was built for, its `Design` and the cell profile version.<br>- **uploaded**: a finger CAD file, split into V-HACD pieces like a part. |
| L3 | **Finger IDs are fixed numbers, `FNG-0001`, and names can be renamed**, as experiments do. Printed fingers keep their engraved IDs (`EXP-0042-D1-L`). A generated library finger records the job and label it came from. |
| L4 | **"Compatible" means the same cell profile name**, which stands for the same gripper and mount. By default an evaluation uses every unarchived finger for its cell profile, plus that cell's stock finger. |
| L5 | **How a library finger grips a new part.**<br>- **Generated** (and imprint) fingers use `regrip(built_for, part, design)`. It already keeps the pad profile fixed, closes the jaws to where the new part seats against it, and sets the tip height.<br>- **Uploaded** fingers use a new `seat()`. It steps the jaws closed until the finger's sections at a few heights meet the part's footprint (`sections()`, `overlaps()`), then subtracts the usual squeeze. The tip height is the grasp's locked grip height, else the stock rule (2.5 mm).<br>- Every combination of finger, pose and grasp goes through `problems()` first. One that fails scores 0 with its reasons and is never simulated. |
| L6 | **An evaluation is a kind of job.** `Job.kind` is `"design"` (today's jobs) or `"evaluation"`. Both share the worker process, live progress, cancel and resume, GPU gating, experiment IDs, job cards and the trials table. `spec` and `plan` become unions tagged by `kind`; old rows read as `"design"`. |
| L7 | **One evaluation covers one part.** A batch of parts creates one evaluation per part, grouped by a `batch_id`. |
| L8 | **The app chooses the grasps; the user may only limit them.**<br>- For each covered resting pose, the candidates are the pose's grasp proposals that aren't blocked.<br>- A pose with a locked grasp (story 4) uses only that grasp.<br>- A finger's score is Σ over poses of w_pose × (its best expected success over that pose's grasps). This assumes the cell knows the pose and runs that finger's best grasp for it.<br>- Results always name that grasp, because the cell has to be set up to run it. |
| L9 | **Two stages, as in generation.** Every combination is scored on the search grid. Then each of the top `EVAL_FINALISTS` = 3 fingers, plus stock, is re-tested on the refined grid at its best grasp per pose. That removes the "best of several grasps" optimism. Fingers below the top 3 keep their search-grid score, labelled as such. |
| L10 | **Grasp accuracy lives on the cell profile.** `CellProfile.grasp_accuracy` is an `ErrorModel`, defaulting to the "typical" preset. It's copied into each job's spec at creation; a spec may override it for a what-if run. Results show the accuracy used, and re-scoring at any other accuracy already works without simulating again. |
| L11 | **No confidence range on sim results.** A sim result shows its success rate and the grasps simulated (grid points × poses). The success-vs-accuracy curves already show how sensitive a finger is. Wilson intervals stay for real trials only. |
| L12 | **A qualification is one finger on one part.** It's unique per `(finger_id, part_id)` and holds:<br>- the latest sim prediction: which job and trial, the accuracy, the grasp, and the success;<br>- earlier predictions, as history;<br>- the real results logged against the pair.<br>Status is derived: `simulated` until real results exist, then `validated`. A gap is flagged when the prediction falls outside the real results' 95% Wilson interval. Every finished evaluation or generation job updates the predictions of the pairs it covered. |
| L13 | **Real results are logged as sessions of counts**: trials, successes, notes, operator, date and a `kind`.<br>- A `natural` session (the cell's own error) compares with the expected success at the cell's accuracy.<br>- A `commanded` session (our blind scripted platform runs) compares with the sim's prediction at the commanded offsets, through the existing test plans.<br>The per-offset tracker of generation jobs stays as is. |
| L14 | **"Generate a finger" starts from an evaluation.** It prefills a `JobSpec`: part, cell, poses, accuracy, the best finger's grasp per pose, V-pad.<br>The new `JobSpec.compare_fingers` (default: the evaluation's top 3 library fingers) adds those fingers as extra baselines in the generation job's final test. They're labelled by finger ID, so the new design is compared on the same grid and grasps. |
| L15 | **Adding a design to the library doesn't touch the review gate.** Printing a finger and mounting it on the robot still need `/review` approval. |
| L16 | **Bulk upload is many files in one request.** A folder upload is the frontend sending a folder's files.<br>- Each file is processed on its own, so one bad file doesn't stop the rest.<br>- One units setting applies to every STL in the batch. At most 50 files.<br>- A part gets an optional `part_number` and an intake status: `ready` (material or measured mass set), `needs_properties`, or `file_error` with the reason. |

## 2. Domain models (`api/models/`)

### `finger_record.py` (new)

```python
FingerSource = Literal["stock", "generated", "uploaded"]
FingerFamily = Literal["stock", "vpad", "flat", "imprint", "other"]  # for filtering; "flat" and "other" are uploads


class FingerRecord(BaseModel):
    id: str  # internal key, used in URLs
    number: int  # fixed for life; finger_code shows it as FNG-0001
    name: str  # renamable
    created: float
    source: FingerSource
    cell_profile_name: str  # the gripper it fits (L4)
    family: FingerFamily
    material: str = "PLA"  # what it's made of, e.g. "PLA", "PETG", "aluminium"
    pad_friction: tuple[float, float]  # static, dynamic; default: the cell profile's pad_friction
    quantity_on_hand: int = 0
    notes: str = ""
    archived: bool = False  # left out of new evaluations; old results keep it
    # generated
    built_for: Part | None = None
    design: Design | None = None
    cell_profile_id: int | None = None  # the version it was built with
    origin_job_id: str | None = None
    origin_label: str | None = None  # D1, D2, ...
    # uploaded
    file_path: str | None = None
    extent_mm: tuple[float, float, float] | None = None
    pieces: list[Piece] | None = None  # in G; None for stock (the sim's own) and generated (rebuilt from the design)

    def grip(self, part: Part, gripper: Gripper, *, tip_height_mm: float | None = None) -> Finger:
        ...
        # stock: stock_finger(part); generated: regrip(built_for, part, design); uploaded: seat(...) (L5)
```

`seat(pieces, part, gripper, tip_height_mm) -> Finger` goes in `finger.py`, next to `regrip()`.

### `qualification.py` (new)

```python
class Prediction(BaseModel):
    job_id: str
    trial_number: int | None  # its final-grid trial if it had one, else its search-grid trial
    kind: Literal["evaluation", "design"]
    error: ErrorModel  # the accuracy it was scored at
    grasps: list[GraspChoice]  # per covered pose
    success: float
    n_grasps: int
    sim_backend: SimBackend  # a mock's prediction is never a result
    created: float


class RealSession(BaseModel):
    id: int
    trials: int
    successes: int
    kind: Literal["natural", "commanded"]
    test_plan_id: int | None = None  # commanded sessions: the plan whose offsets were run
    notes: str = ""
    operator: str | None = None
    date: str | None = None


class Qualification(BaseModel):
    id: int
    finger_id: str
    part_id: str
    prediction: Prediction | None
    history: list[Prediction] = []
    sessions: list[RealSession] = []
    # derived: status ("simulated" | "validated"), measured success, Wilson interval, gap_flagged
```

### Changes to existing models

- **`CellProfile`:** add `grasp_accuracy: ErrorModel = ErrorModel()` (L10). Old profiles parse with the default.
- **`JobSpec`:**
  - add `kind: Literal["design"] = "design"`;
  - `error: ErrorModel | None = None`, filled in from the cell at creation;
  - add `compare_fingers: list[str] = []` (L14).
- **`EvaluationSpec` (new, `evaluation_spec.py`):**
  - `kind: Literal["evaluation"]`, `name`, `part_id`, `cell_profile_id`, `task: Task = Task()`;
  - `poses: list[EvaluationPose]`: a pose choice plus an optional locked `GraspChoice`. Empty means the part's likely poses, with automatic grasps;
  - `finger_ids: list[str] | None`: None means every compatible finger (L4);
  - `error: ErrorModel | None`: None means the cell's.
- **`AnySpec = Annotated[JobSpec | EvaluationSpec, Field(discriminator="kind")]`.** The same goes for the plan: `JobPlan` gains `evaluation: EvaluationPlan | None`, which lists the covered poses, their candidate grasps, the fingers with any geometry rejections, the grid sizes and the time estimate.
- **`Trial`:** add `finger_id`, `pose_key` and `grasp_key` (for example `p0g1`), all None for design jobs. An evaluation stores one trial per finger, pose, grasp and grid.
- **`PartRecord`:** add `part_number: str | None`, and a computed `intake_status`.

## 3. Pipeline

### 3.1 Grasp accuracy on the cell (story 9), workstream W1

- `CellProfile.grasp_accuracy`, edited through the existing profile `PUT`, which creates a new version.
- `create_job` copies the cell's accuracy into `spec.error` when the spec leaves it unset. Every job then records what it used.
- The presets stay placeholders until the cell's accuracy is measured (CONTEXT.md, risk 3).

### 3.2 Part intake, many files (stories 1, 5), workstream W2

- `POST /api/parts/batch` takes `files: list[UploadFile]` and `units`. For each file it calls the existing `create_part`, catching that file's errors. It returns one row per file: `{filename, status, part | reason}`.
- Only `.step`, `.stp` and `.stl` are read. Any other file in a folder is reported as `skipped`.
- Files are processed one after another in a threadpool.
- `PATCH /api/parts/{id}` also takes `name` and `part_number`.

### 3.3 Finger library (stories 7, 8, 16), workstream W3

- **Stock seeding:** at startup, every cell profile name without a stock finger gets one, the same way the default cell profile is seeded today.
- **Upload (story 7):** `POST /api/fingers` is a form with the file, name, cell profile, family, material, friction, quantity and units.
  - A new `CadClient.read_finger` reuses the part reader.
  - It **auto-places** the finger in G: lowest point at z = 0, innermost face (toward the other finger) at x = 0, centred in y.
  - Then it splits the finger into pieces, at most 16 pieces of at most 64 vertices each, as for parts.
  - Checks:
    - the finger stays inside the cell's free space;
    - it's no longer than `max_finger_length_mm`, when that's set;
    - it overlaps the stock blade's kept mount region, as a sanity check that it was placed the right way up.
  - `GET /api/fingers/{id}/mesh` returns the placed finger as STL, for a preview next to the jaw. See Q2.
- **Add from a job (story 16):** `POST /api/jobs/{id}/designs/{label}/library` creates a generated `FingerRecord` from a final design: the job's primary-pose `Part`, the `Design` and the cell profile version. It's refused for STOCK, which is already in the library, and for mock jobs unless `force` is set.
- **Browse (story 8):** `GET /api/fingers` filters by family, cell profile, source and archived. Each finger comes with a qualification summary: parts evaluated, best success, validated count.

### 3.4 Evaluation job (story 10), workstream W4

`services/evaluation.py` runs it, started by the same `python -m api.worker <job_id>`, which dispatches on `job.kind`.

1. **Plan** (at `POST /api/jobs/plan` and at creation):
   - Resolve the poses: the spec's, or the part's likely ones (at most 4).
   - Resolve the grasps per pose: the locked one, or the non-blocked proposals (`propose_grasps`).
   - Resolve the fingers (L4).
   - Build `finger.grip()` for every combination of finger, pose and grasp, and run `problems()`.
   - Combinations that fail are recorded as rejections, with their reasons, and never simulated.
   - Estimate the time with the existing `throughput()`. If nothing at all can grip the part, the plan says so, with the existing `NothingFits` suggestions.
2. **Search stage:** one sim batch per (pose, grasp), carrying every finger still standing for it, on that pose's search grid. Each batch is checkpointed when it finishes, the way rounds are, so a resumed job skips finished batches. Stock goes in every batch as `None`, as today.
3. **Score** each combination with the existing task and error-model scoring. Each finger's score is its best grasp per pose, weighted over the poses (L8).
4. **Final stage:** the top 3 fingers and stock are re-tested at their best grasp per pose on the refined grid (L9).
5. **Write results:** in one transaction, store the ranking and upsert a qualification prediction for every finger evaluated on this part (L12).

### 3.5 Evaluation results (story 12), workstream W5

`GET /api/jobs/{id}/results` returns a result tagged by `kind`. For an evaluation it has:

- **A header:** part, cell, accuracy, task, poses, sim badge (mock or Isaac), and caveats (the existing `caveats()`, plus "flat table, top-down, no height error").
- **One row per finger, ranked:**
  - finger code, name and source;
  - success, grasps simulated, and which grid the score comes from;
  - capture radius;
  - its best grasp per pose: angle, centre, section, tip height, jaw close;
  - its score at every other grasp, for drill-down;
  - its rejection reasons, if it couldn't fit;
  - the real measured rate, if its qualification has one.
- **For the top fingers:** success-vs-accuracy curves and where grasps fail, by direction and distance (the existing `FailureView`).
- **A `generate` option:** the spec it would prefill (3.6). There's no pass bar: the manufacturing engineer decides
  whether the best finger is good enough.

`POST /api/jobs/{id}/rescore` works for evaluations too: it re-ranks at another accuracy or task without simulating again.

### 3.6 Generation from an evaluation (story 14), workstream W5

- `POST /api/jobs/{id}/generate-spec` takes an optional `finger_id` and returns the prefilled `JobSpec` (L14). The frontend opens the existing wizard with it.
- **In the optimizer's final test:** each `compare_fingers` entry is gripped with `FingerRecord.grip()` and re-tested with the finalists and the stock and imprint baselines, labelled by its finger code. The results' summary then reads, for example, "D1 92% vs FNG-0003 61% (best existing)".
- The design's results don't change otherwise. A target success rate isn't an input (the story drops it).

### 3.7 Qualifications and real results (story 17), workstream W6

- **Endpoints:**
  - `GET /api/qualifications`, filtered by finger and/or part;
  - `GET /api/qualifications/{id}`;
  - `POST /api/qualifications/{id}/sessions` to log a session of counts;
  - `PATCH` and `DELETE` on a session.
- Each response carries the derived status, the pooled measured rate, its Wilson interval and `gap_flagged`.
- **Commanded sessions** (L13) take their prediction from the linked test plan's prediction, not the accuracy-weighted one. For a generated finger, the existing per-job physical trials for its origin job and label also count, and are shown as their own session.
- **Generation jobs** add predictions for their top design (labelled D1) and the compared fingers, against the job's part. D1 becomes a library finger, with its qualification, once someone adds it (3.3).

### 3.8 Second build: failure reasons and replays (story 13), workstream W7

- **Failure codes:** sim contract v2 gains an optional `failure` code per offset:
  - `unreachable` (IK failed);
  - `landed_on_part` (the part moved before the jaws closed);
  - `missed` (never touched);
  - `slipped` (held, but its in-hand offset or tilt broke the task's tolerance);
  - `dropped` (lifted, then lost);
  - `dropped_in_transport`.
- **Sim server:** reads the part's pose at the end of the descent and at the close. That's also the open item on landing capture (risk 5).
- **Mock:** reports `missed` and its geometric `landed_on_part` only.
- **Results:** a breakdown per finger, with the geometry rejections listed separately.
- **Replays:** `POST /api/jobs/{id}/clips` accepts a finger, pose, grasp and offset for evaluation trials. Today it only takes a final design label. The clip worker grips the library finger the same way the evaluation did.
- **Metrics:** `GET /api/metrics` gives the median time from part upload to its first validated qualification, and the share of evaluated parts that never needed a generation job.

## 4. Database (migration 0007)

| Change | Notes |
| --- | --- |
| new `fingers` | `FingerRecord`; `number` unique; pieces, `built_for` and `design` as `PydanticJSON` |
| new `qualifications` | unique `(finger_id, part_id)`; `prediction` and `history` as `PydanticJSON` |
| new `real_sessions` | one row per session, with `qualification_id` |
| `jobs.kind` | default `"design"`; `jobs.batch_id`, nullable |
| `jobs.spec`, `jobs.plan` | the `kind`-tagged unions; existing rows read unchanged |
| `trials.finger_id`, `trials.pose_key`, `trials.grasp_key` | nullable; NULL for design jobs |
| `parts.part_number` | nullable |

Existing jobs, trials and parts are kept: nothing is cleared, unlike 0002 and 0003. `tests/db/test_tables.py` covers the new
tables as it does the others.

## 5. API (the contract for the frontend)

| Method and path | Story | What |
| --- | --- | --- |
| `PUT /api/cell-profiles/{id}` | 9 | now includes `grasp_accuracy` (a new version, as today) |
| `POST /api/parts/batch` | 5 | many files: one row per file, `ready` / `needs_properties` / `file_error` / `skipped` |
| `PATCH /api/parts/{id}` | 1 | plus `name`, `part_number` |
| `GET /api/fingers` | 8 | the library, with filters and qualification summaries |
| `POST /api/fingers` | 7 | upload a finger (form) |
| `GET`, `PATCH /api/fingers/{id}` | 7, 8 | a finger; edit its name, quantity, material, friction, notes, archived |
| `GET /api/fingers/{id}/mesh` | 7 | STL in G, for the 3D preview |
| `POST /api/fingers/preview` | | unchanged (the wizard's design-space sliders) |
| `POST /api/jobs/{id}/designs/{label}/library` | 16 | add a final design to the library |
| `POST /api/jobs/plan`, `POST /api/jobs` | 10 | accept either spec kind |
| `POST /api/jobs/batch` | 10 | an evaluation per part, sharing a `batch_id` |
| `GET /api/jobs?kind=&batch_id=` | 10 | job cards, filtered |
| `GET /api/jobs/{id}/results`, `POST .../rescore` | 12 | a result tagged by `kind` |
| `POST /api/jobs/{id}/generate-spec` | 14 | a prefilled `JobSpec` |
| `GET /api/qualifications`, `GET /api/qualifications/{id}` | 17 | predictions and real results per finger and part |
| `POST`, `PATCH`, `DELETE /api/qualifications/{id}/sessions[/{n}]` | 17 | log real sessions |
| `POST /api/jobs/{id}/clips` (extended), `GET /api/metrics` | 13 | second build |

After the backend changes, regenerate the frontend's typed client (`npm run gen:api`, then `npm run typecheck`), and update
[backend-api.md](backend-api.md) as each workstream lands.

## 6. Workstreams and order

| # | Workstream | Size | Depends on | Tests that matter |
| --- | --- | --- | --- | --- |
| W1 | Grasp accuracy on the cell, copied into specs | S | | old profiles parse; a spec without `error` gets the cell's |
| W2 | Bulk part upload, part number, intake status | S | | a bad file among good ones; folder junk skipped; STL units |
| W3 | Finger library: model, table, stock seeding, upload and placement, `seat()`, add from a job, browse, mesh | M | | `regrip()` onto a *different* part (box onto cylinder, mesh onto box); `seat()` against box, cylinder and mesh parts; `problems()` on library fingers; mock outcomes for uploaded pieces |
| W4 | Evaluation job: spec, plan, worker dispatch, batches, checkpoints, final stage, qualification upserts | L | W1, W3 | resume after a batch; rejected fingers never simulated; scoring = best grasp per pose; one end-to-end run on the mock |
| W5 | Evaluation results, rescore, `generate-spec`, `compare_fingers` in the optimizer's final test | M | W4 | ranking matches the trials; compared fingers on the same grid and grasp |
| W6 | Qualifications and real sessions, library summaries | M | W3, W4 | unique pair; status, Wilson interval and gap flag; commanded sessions use the test-plan prediction |
| W9 | Demo data (`DEMO_DATA=true`): fingers, evaluations, qualifications, made-up real sessions labelled as such | S | W3–W6 | the frontend can build every new screen offline |
| W7 | Second build: failure codes (sim contract, sim server, mock, results), replays for evaluation trials | M | W4 | |
| W8 | Second build: metrics | S | W6 | |

W1, W2 and W3 can run in parallel. W4 starts once W3's `FingerRecord.grip()` is in place. W5, W6 and W9 follow W4.

## 7. Sim cost

An evaluation simulates fingers × (sum over poses of grasps) × search grid, then (top 3 + stock) × poses × refined grid.

| Grid | Search | Refined (final) |
| --- | --- | --- |
| Round from above (no yaw) | 81 | 321 |
| With yaw (boxes, lying cylinders, meshes, the screw) | 243 | 963 |

**Example:** 8 library fingers plus stock, gripping a screw in 1 pose with 3 grasps.
- Search: 9 × 3 × 243 = 6,561 grasps.
- Final: 4 × 963 = 3,852 grasps.
- Total: about 10,400 grasps. That's **about 35 minutes at 5 grasps/s** (CPU copies, the path we report results from), or under 10 minutes on GPU copies once their bias (risk 7) is fixed.

The geometry checks remove fingers that can't fit before any simulation. If that's still too slow for the demo, Q6 is the
lever.

## 8. Open questions

Decided 2026-10-26:

- **Q1, no confidence range** on sim results (L11).
- **Q2, uploaded fingers are auto-placed in G,** then shown on the jaw for the robotics engineer to confirm or flip. A template STEP of the stock blade in G helps anyone authoring one.
- **Q3, uploaded fingers grip with their tips 2.5 mm above the table** (the stock rule), or at the grasp's locked height. Every extra height tried would multiply the cost.

Still open:

| # | Question | Recommendation |
| --- | --- | --- |
| Q4 | Asymmetric finger pairs (left differs from right)? | Not supported: the sim mirrors one finger. Say so on upload. |
| Q5 | Is stock always in every evaluation? | Yes: it's the baseline the judges asked for. |
| Q6 | Grasps per pose: the top 3 proposals, or every non-blocked one? | The top 3 for the demo (the cost table above); every non-blocked one later, since proposals are ranked for flat pads. |
| Q7 | Real sessions: will we log any `natural` ones, or only `commanded` platform runs for now? | Only commanded, for the demo. Keep `natural` in the model for factories using it day to day. |

## 9. What gets validated where

- **Mock sim, offline:** everything in W1–W9 runs end to end on the mock. The mock checks capture geometry only, so **its rankings aren't results.** Every prediction, qualification and export carries the sim badge (mock or Isaac).
- **Isaac on the GB10:** before any ranking is shown as a result, run one evaluation end to end there and log it in [docs/experiments/](../experiments/README.md):
  - a few generated and uploaded fingers, plus stock, on the demo part;
  - the time it took, compared with the estimate;
  - whether the ranking survives a repeat run (about 9% of grid points flip near a finger's capture edge, risk 5).
- **The real arm:** commanded sessions through the organizers' platform ([cell_policy/](../../cell_policy/README.md)), logged against the pair's qualification (story 17).
