---
title: Backend API for the input flow and outputs (as built)
source: our own note, written after implementing docs/notes/input-flow-backend-plan.md
author: Alec Weinbender's Team
received: 2026-10-20
kind: note
status: current
---

# Backend API for the input flow and outputs (as built)

**For:** whoever builds the wizard, the job list, the results page and the results tracker, and the finger library,
evaluation jobs and qualifications ([the last section](#finger-library-evaluation-jobs-and-qualifications)).

**Two kinds of job.** A job is a run the worker does on the sim. A **generation** job is the optimizer designing new
fingers (the wizard, the results page and the tracker below). An **evaluation** job tries the fingers in the library on
a part and ranks them. Both share the job list, live progress, cancel, resume and experiment IDs; every card, spec and
plan has a `kind`. A spec sent without one is a generation spec, so older clients keep working.

**Where the exact shapes are:**

- the API's own schema, at `/docs` (Swagger) and `/openapi.json`;
- `npm run gen:api` in `app/frontend` turns `/openapi.json` into types.

**What this note covers:** for each screen, which calls to make and the behaviour that isn't obvious from the schema.

**Design:** the plan is [input-flow-backend-plan.md](input-flow-backend-plan.md). Where this note and the plan differ,
this note is what was built.

## Demo data

**To have data to draw:** put `DEMO_DATA=true` in the repo-root `.env` and start the API as usual:

```bash
uv run --package backend uvicorn api.main:app --port 8000
```

**First start:**

- The API then runs on its own demo database in `app/data/demo`, never the real one.
- On the first start it generates the demo in the background. Experiments appear one by one over about two minutes, each
  visibly running first, so live progress shows too.
- `GET /api/meta` returns `demo_data: true`. Show a banner, because demo results come from the mock sim and its physical
  trials are made up.

**What's in it:**

- parts: a vial cap, a 10 mm cube, a lying glass tube, an L-bracket (a mesh part) and a steel plate that nothing fits;
- two cell profiles, one with two versions;
- ten generation experiments: done, cancelled, interrupted and failed;
- two experiments with print selections, printed fingers and test plans, one validated and one in progress;
- a finger library: the UWM cell's stock fingers, two generated designs and two uploaded fingers (one too wide for the
  small parts);
- three evaluation jobs: the vial cap, and a batch of the cube and the L-bracket;
- made-up real-robot sessions on two finger-and-part pairs, one agreeing with the sim and one flagging a gap.

**Back to real data:** unset `DEMO_DATA`.

**To regenerate:** stop the API, then run

```bash
uv run --package backend python app/backend/scripts/demo_data.py --reset
```

or delete `app/data/demo`.

## Conventions

**Units and badge**

- Lengths are in mm, angles in degrees, masses in g.
- Every result carries `sim_backend`: `"mock"` or `"isaac"`. Show it as a badge everywhere. Mock numbers are geometry
  only and never predictions.

**Errors**

| Code | Meaning |
| --- | --- |
| 404 | unknown id |
| 409 | the state is wrong for the request, e.g. no resting pose chosen yet, or the job isn't done |
| 415 | a file type that isn't supported |
| 422 | invalid input; `detail` says why |

**Long work runs in detached worker processes:** a job's optimisation, and a test plan's sim prediction. Poll, or use the
job's SSE stream.

**Frames**

- Part poses and grasp picks are in the table frame: z up, the part resting on z = 0, its footprint centred.
- The part a job simulates (`plan.part`, `job.part`) is in the grasp frame: x is the jaws' closing direction, and the
  origin is under the grasp centre.

## Input steps

### Step 1, part

**Upload:** `POST /api/parts`, multipart with `part_file`.

- An STL also needs `units` (`mm` or `in`).
- A native SolidWorks file gets 415, with the hint "In SolidWorks: File > Save As > STEP." An unreadable file gets 422.

**Many at once:** `POST /api/parts/batch`, multipart with `files` repeated (several picked, or every file of a folder:
`<input type="file" webkitdirectory>` sends them all) and one `units` for every STL. It returns 201 with one row per file,
in the order sent: `{filename, status, part, reason}`.

- `status` is `ready` or `needs_properties` (stored; `part` is the record, without pieces), `file_error` (not stored;
  `reason` says why) or `skipped` (not a STEP or STL, e.g. a readme in the folder).
- A bad file never stops the others. More than 50 CAD files in one request is a 422.

**Intake status:** every part response has `intake_status`: `ready` once it has a mass (a material or a measured mass),
else `needs_properties`. Evaluations and generation jobs need it ready.

**Reading parts back:** `GET /api/parts` (newest first) and `GET /api/parts/{id}`.

- Lists leave out the convex pieces (`measured.pieces` is empty there).
- `measured.extent_mm` is the bounding box. Show it, so a units mistake is caught.
- `measured.material_hint` pre-selects the material.

**Editing:** `PATCH /api/parts/{id}` (JSON). Only the fields sent change. The fields are name, part_number, material,
density_g_cm3, surface, mass_g, mass_unit, fragile, max_grip_force_n, clearance_mm and pose.

- `name` starts as the file's name and can't be blank; `part_number: null` (or blank) clears the number.

- `mass_g: null` means "use the computed mass".
- When the material changes, send `density_g_cm3: null` too, or an earlier density stays.
- Material `"other"` needs a density.

**Computed values in responses:** `computed_mass_g`, `confirmed_mass_g`, `mass_source` (`computed` / `measured`), and
`friction_vs_pad`. The friction comes from the profile when you add `?cell_profile_id=`, else from 0.6 / 0.5.

**Catalogs:** `GET /api/meta` gives materials, surfaces, families with their parameter schemas, error presets, task
kinds with the tolerances each needs, transport speeds, mass units, the sim backend, `demo_data`, and `pose_cutoff`
(0.1: a stable pose at least this likely is "likely").

### Step 2, resting pose

**Poses:** `GET /api/parts/{id}/poses` returns the top 4 stable poses, most likely first, then "as in the CAD file".
Each pose has `index`, `label`, `probability`, `extent_mm`, `rotation`, `chosen` (the part record's chosen pose) and
`likely` (a stable pose with `probability >= pose_cutoff`). The likelihoods are trimesh's quasi-static estimate, not
measured on the cell.

**A job covers one or more poses.** The spec's `poses` is a list of `{pose: <index> | "as_authored", grasp}`, one per
pose, at most 4, no pose twice; "as_authored" has no likelihood, so it can only be the one pose. Tick the likely poses
by default. Every design is simulated in every pose and scored by the poses' likelihoods, renormalised over the ones
ticked: `w_k = p_k / sum(p)`. The likeliest is the primary: the fingers are built for it and its ranges are searched.
The run takes about as many times as long as there are poses. A spec with `grasp` instead of `poses` (exactly one of
the two) is the older form: one grasp on the part record's chosen pose. It still plans and runs the same.

**Choosing the part's own pose:** `PATCH {pose: <index> | "as_authored"}`. The part library and the grasp endpoints use
it when no pose is given; a job with `poses` doesn't need it.

**For the 3D thumbnails:** `GET /api/parts/{id}/mesh?pose=<index|as_authored>` returns a binary STL in that pose's table
frame (three.js STLLoader).

### Step 3, task

The task is part of the job spec; there's no endpoint. Its fields:

- `kind`: `drop`, `place` or `insert`;
- `offset_tolerance_mm`: place and insert;
- `tilt_tolerance_deg`: insert;
- `transport`: `null`, `slow`, `normal` or `fast`.

### Step 4, cell profile

**Endpoints**

- `GET /api/cell-profiles` returns the latest version of each.
- `POST /api/cell-profiles {name, profile}` returns 201.
- `GET /api/cell-profiles/{id}`.
- `PUT /api/cell-profiles/{id} {profile}` saves a new version and returns it; old versions never change.
- `GET /api/cell-profiles/{id}/versions`.

**Responses also carry**

- `twin_mismatches`: where this profile differs from the gripper the sim models. Show them.
- `gripper`: what the finger geometry uses.
- `to_confirm`: fields that are still placeholders. Mark them.

**Grasp accuracy:** `profile.grasp_accuracy` is the cell's error model (same shape as a spec's `error`, step 7): how far a
grasp may land from where it was aimed. It defaults to the "typical" preset. A job spec that leaves `error` out (or
null) gets the cell's, copied in when the job is created; one that sends its own keeps it (a what-if run). Edit it with
the usual `PUT`, which saves a new version. Creating a cell also adds its stock fingers to the finger library.

### Step 5, grasp

One grasp per pose the job covers: ask for each with that pose's index, and draw it on `GET .../mesh?pose=<index>`.

**Proposals:** `POST /api/parts/{id}/grasps {cell_profile_id, pose?}` returns `candidates`, `rejected` and `nothing_fits`
for the part in that pose.

- `candidates`: the top 1–3. Draw each as an arrow: `angle_deg` from +x, at `centre_mm`.
- A candidate with `span_mm` grips a section of the part: a stretch clearly narrower than the whole part, like a screw's
  shank beside its head. `span_mm` is where across the jaws, from `centre_mm`, the pads may sit; `width_mm` is the
  section's. Keep `span_mm` in the `GraspChoice`: the fingers are sized to the section, and the stock fingers close on
  it. When a part has sections, they're ranked with the whole-part directions: ok before warn, then the narrower width.
- `rejected`: a short note on why the other directions were rejected.
- `nothing_fits`: when nothing fits, the exact reason and ordered `suggestions`.
- Without `pose`, needs the part's chosen pose; 409 otherwise. An unknown pose index is a 422.

**Manual choice:** `POST /api/parts/{id}/grasps/check {cell_profile_id, pose?, angle_deg?, picks?, grip_height_mm?,
centre_mm?, span_mm?}`.

- `picks` are one or two `{point, normal}` from a raycast against the table-frame mesh. A pick on a section grips that
  section (`span_mm` in the response and its `choice`).
- `centre_mm` and `span_mm` (with `angle_deg`) re-check a section grasp chosen before, on that same section.
- The response has `verdict` (`ok` / `warn` / `blocked`), warnings and `choice`, a ready `GraspChoice` for the spec.
- Block the Next button on `blocked`.

### Step 6, finger families

**Parameter table, budget and time:** use `POST /api/jobs/plan` (below). Each `plan.families[].params[]` entry gives:

- `default_range`: what's searched if the user leaves it alone;
- `limits`: what's buildable;
- `effective_range`;
- `locked`;
- `applies` (false where a parameter doesn't apply to this part);
- `note`, when a range was clipped.

**Choosing families:** the spec's `families` is a list of `{family, ranges: {name: {lo, hi}}, locks: {name: value}}`.

- Lock every parameter for "test my own design".
- Only V-pad is built. A planned family is refused when the spec is parsed: a 422 at `body.families`. Map it to step 6.

**Ghost previews:** `POST /api/fingers/preview {part, cell_profile_id, choice, vary}`.

- Returns the "min" and "max" fingers for one parameter, with the others mid-range.
- `designs` instead of `vary` previews explicit designs.
- `others`: the plan's other poses' parts (`plan.poses[1:]`). The pad face is shared by every pose, so they bound the
  slack: the open pads must clear the widest and the jaws must still reach the narrowest. A pose that can't be gripped
  together with the likelier ones is left out of those bounds and scores 0; the plan warns about it.
- Each finger has `pieces`, `closed_gap_mm` and `problems`.

### Step 7, camera error and grid

**Error model:** the spec's `error` is `{preset, sigma_mm, sigma_range_mm?, sigma_deg, bias_mm, bias_direction_deg}`.
The presets are in `/api/meta`; the placeholder ones say so. Left out, it's the cell profile's `grasp_accuracy` (step 4):
pre-fill the step from the profile, and only send `error` when the user changes it.

**Grid preview:** `POST /api/grids {part, parts?, error, final?}`. For a job over several poses send every pose's part
(`plan.poses[].part`) as `parts`: they share one grid, with yaw layers unless every pose is round from above.

- Returns `points`, each with its weight; the 1σ and 2σ circles; the outer ring; the yaw layers; and warnings.
- It takes milliseconds, so call it on every slider move.

### Step 8, review and run

**Plan:** `POST /api/jobs/plan <JobSpec>` always returns 200. The body is the plan:

- `part` (the primary pose's), `families`, `searches` (method, budget, batch size);
- `poses`: the poses covered, primary first, each `{key ("p0", "p1", ...), label, choice, probability, weight, resting,
  grasp, part}`;
- `totals`: grasps (every pose's), designs, rounds, and `poses`;
- `estimate`: seconds, or null while the throughput is unknown;
- `warnings`;
- `blockers: [{step, reason}]`, plus `failed_step`, the step to send the user back to. With several poses a grasp's
  blockers name its pose ("grasp (standing): ..."), and a pose index that doesn't exist blocks step 2.

Nothing is stored.

**Run:** `POST /api/jobs <JobSpec>` returns 201 `{id, experiment_id, name}`.

- A blocked plan → 422 with `detail: {message, reasons, failed_step, blockers}`.
- A blank name defaults to "<file stem>_<date>".
- The experiment ID (`EXP-0001`, …) never changes.

## GPU panel

**What it's for:** connecting the sim to a GPU target. The rest of the API never sees which one: jobs talk to
`SIM_URL`, and the connected target is forwarded there. Targets come from `COMPUTE_BACKENDS`:

- **Brev** instances (created in the Brev console) are started and stopped, and stop by themselves when idle.
- The **MSOE GB10** (`always_on`) is shared with other teams: it's connected and disconnected, and its sim server keeps
  running after a disconnect. Label its buttons "Connect" and "Disconnect".

One target is connected at a time.

**Calls**

- `GET /api/compute` is cheap (no provider call): `backends` (each enabled one's `name`, `label` and `always_on`),
  `managed`, `auto_stop_minutes` (Brev), `session` (the one starting, ready or stopping, else null), `last` (the latest
  session, ended ones included) and `not_ready_reason`. Poll it every few seconds while a session starts or stops.
- `GET /api/compute/instances` asks every enabled backend (a few seconds: the Brev CLI, ssh to the GB10) and returns
  `{instances, errors}`. Each instance has `backend`, `name`, `status` (the provider's word; the GB10's is `AVAILABLE`
  or `BUSY`), `state` (`running`, `starting`, `stopping`, `stopped`, `other`), `gpu`, `instance_type`, `always_on` and,
  for the GB10, `other_gpu_processes`: the GPU processes besides our sim server (another team's, or a teammate's run),
  which the panel shows in the target list and, refreshed every minute, while connected. A backend that can't be asked
  (no VPN, CLI not logged in) is in `errors` as `{backend, message}`, and the others are still listed.
- `POST /api/compute/start {backend, instance}` is 202 with the session (`status: "starting"`). 422 for a backend that
  isn't enabled, 404 for an unknown target, 409 while another target's session is active (the message says to stop the
  Brev instance or disconnect the GB10 first), 502 when the provider fails. Asking again for the same target returns its
  session.
- `POST /api/compute/stop` is 202 (`stop_requested: 1`): stops the Brev instance, or disconnects the GB10. 409 when
  nothing is connected.
- `GET /api/compute/sessions?limit=` lists sessions, latest first: which target was connected when, and why it ended
  (`stop_reason`: `user`, `idle`, `external`, `failed`). A log of GPU time.

**A session's life:** `starting` (its `message` says which step: starting the instance, waiting for the Isaac
container, starting the sim server, connecting) → `ready` → `stopping` → `stopped`; or `failed`, with the reason in
`message`. A failed Brev session stops its instance too; a failed GB10 session stops nothing. If the sim server dies
while connected, the session starts it again.

**Auto-stop (Brev only):** a ready session stops after `auto_stop_minutes` without a job worker running or a test-plan
prediction waiting. Starting a job, a resume or a prediction restarts the clock.

**Jobs wait for it:** when `managed` is true, `POST /api/jobs` and `POST /api/jobs/{id}/resume` answer 409 with
`not_ready_reason` until a session is ready; a test plan is still created, with its prediction failed and the reason in
`prediction_error` (predict again once the GPU is up). With only the mock enabled nothing waits.

## Job list

**Cards:** `GET /api/jobs?part_id=&status=&backend=&kind=&batch_id=` returns cards of both kinds, newest first. A card
has:

- `experiment_id`, `name`, `kind` (`generation` / `evaluation`), `batch_id`, `part_name`, `task_kind`, `sim_backend`,
  `status`;
- `round` / `n_rounds`, `n_done` / `n_total`, and `best_value` (best predicted success so far);
- once done, `winner` and `stock`, each `{label, success, capture_radius_mm}`. For an evaluation job, `winner` is its
  best finger (`label` is the finger code, `FNG-0003`) and `stock` the stock fingers; `n_done` counts fingers
  simulated at a grasp, and `round` / `n_rounds` sim requests;
- once failed, `failure` (one line) and `failed_step`;
- `physical_badge`: `none`, `in_progress` or `validated`.

**Live updates:** `GET /api/jobs/{id}/events` is SSE, sending the card on every change and ending when the job finishes.

**Statuses:** queued → running → finalizing → done; also failed, cancelled and interrupted.

**Other calls**

- `PATCH /api/jobs/{id} {name}` renames.
- `POST /{id}/duplicate` returns the job's spec (a JobSpec or an EvaluationSpec, by `kind`) named "… (copy)" for the
  wizard to edit and re-submit, with `duplicated_from`. It doesn't start a run. An evaluation that tried every
  compatible finger copies as one that does again, so fingers added since are included. An older spec with one `grasp` comes back as `poses` with that grasp on its
  pose, when the pose is still one of the part's.
- `POST /{id}/cancel` and `POST /{id}/resume`. Interrupted, cancelled and failed jobs resume from their last round.

## Results page

**The view:** `GET /api/jobs/{id}/results`. Its sections:

- `header`: name, ID, badge, cell profile and version, status, task and error used;
- `summary`: D1, stock and imprint at the target, the gains, designs evaluated, the task metric;
- `curves`: success vs σ for every final design, with the target marked;
- `held_maps`: D1 and STOCK on the final grid; each point has `dx`, `dy`, `yaw_deg`, `weight`, `held` and `success`;
- `in_hand`: offsets and tilts against the tolerances (place and insert);
- `failures`: misses by direction and by distance, plus caveats;
- `best_finger`: params, grasp pose as JSON and text, files, checks, `download_blocked`;
- `final_table`: label, success, capture radius, task metric, print-selected;
- `physical`: the tracker's validation, below;
- `run`: per-search progress (best so far vs designs evaluated), stop reasons, budget, batch size, versions, GPU, seed,
  warnings.

Sections that need the final test are null before it.

**Landing (since 2026-10-26):** a grasp whose finger landed on the part scores as a miss (moved more than 1 mm or 3°
before the jaws closed). On an Isaac run, `failures.caveats` and the ranking's `warnings` say how many held grasps that
turned into misses. They say it wasn't checked when the sim server predates it.

**A job over several poses:** every success is weighted over the poses and every capture radius is the smallest over
them. `summary.best` / `stock` / `imprint` and each `final_table` row add `poses: [{key, label, weight, success,
capture_radius_mm}]` (null for one pose). `held_maps` come per design and pose, each with `pose` and `pose_label`
(null for one pose). Curves are weighted; `in_hand` and `failures` pool every pose's grasps, each weighted by its pose.
The grasp pose keeps the primary's settings at the top level and adds `poses`: each pose's grasp angle and centre,
fingertip height and jaw position, with its weight. Clips, test plans and physical validation use the primary pose only.

**Re-score bar:** `POST /api/jobs/{id}/rescore {error?, task?}` returns the same view under other inputs. Nothing is
stored.

**Downloads, for any final label (D1, D2, …, IMP; not STOCK)**

- `GET /api/jobs/{id}/designs/{label}/cad?format=step|stl&side=L|R`;
- `.../print-sheet.pdf`;
- `.../grasp-pose?format=json|text`;
- `.../checks`: why a download is blocked;
- `GET /api/jobs/{id}/run-metadata.json` and `GET /api/export/trials.jsonl?job_id=`.

**Download rules**

- File names start with the experiment name and ID, and carry `_MOCK` on mock runs.
- A failed export check → 409 with the failed checks.
- Labels are case-insensitive.

**3D preview:** `GET /api/jobs/{id}/finger?design=D1&pose=p1` returns the part, the finger and its mirror (`right`),
with `jaw_open_mm`, in the primary pose or the one with that key (`pose`, `pose_label`; 404 for an unknown key). The
finger is the same in every pose; its fingertips and jaws move to where that pose needs them.

**Trials export:** with several poses each row of `trials.jsonl` keeps `part`, `held` and `in_hand` the primary's, and
adds `poses` (the plan's poses without `resting`) and `pose_outcomes` (every other pose's raw outcomes, in order).

**Review gate:** `POST /api/jobs/{id}/review` is unchanged. No finger goes on the robot without approval.

## Isaac Sim clips

**What they are:** real Isaac Sim footage of one grasp. A final design (D1, D2, ..., STOCK, IMP) is filmed at one grid
point, with the same finger, part, offset, grip force and transport the experiment simulated. The sim server runs the
grasp with the cameras on and returns an mp4 per view:

- `closeup`: the fingers and the part at the grasp site, across the jaws' closing direction;
- `side`: the cell's side camera, with the arm.

A clip is about 5 s (the 3.9 s grasp, then a second holding the lift).

**Status (2026-10-20): working on the GB10.** A real experiment was run and filmed through these calls
([log](../experiments/2026-10-20-gb10-app-end-to-end-and-clips.md)). Real clips need an experiment run on the Isaac sim
and a connected GPU.

**Ask for a clip:** `POST /api/jobs/{id}/clips`.

```json
{"design": "D1", "offset": {"dx": 4.0, "dy": 0.0, "yaw_deg": 0.0}}
```

- `design` is a final label, in any case.
- `offset` is in mm and degrees, like the results' `held_maps` points. Take it from a held-map point, so the clip can
  be compared with the stored result. `yaw_deg` defaults to 0. Each value must be within ±50 mm or ±180°.
- The answer is **202** with the clip, queued:

  ```json
  {
    "id": 7,
    "job_id": "be4cdfe542",
    "design": "D1",
    "offset": {"dx": 4.0, "dy": 0.0, "yaw_deg": 0.0},
    "status": "queued",
    "views": ["closeup", "side"],
    "outcome": null,
    "result": null,
    "matches_result": null,
    "duration_s": null,
    "error": null,
    "created": 1792534800.0,
    "recorded": null
  }
  ```

- **Asking again** for the same design and offset returns the existing clip, unless it failed. Then a new one is made.

**The clip's life:** `queued`, then `recording`, then `ready`, or `failed` with `error`.

- **Poll** `GET /api/jobs/{id}/clips` (newest first) every few seconds while any clip is queued or recording.
- **A ready clip:**

  ```json
  {"id": 7, "status": "ready", "outcome": "held", "result": "held", "matches_result": true, "duration_s": 4.9,
   "recorded": 1792534870.2, "views": ["closeup", "side"], "...": "the other fields as above"}
  ```

- **`outcome`** is what happened in this recording: `held` or `missed`.
- **`result`** is the experiment's stored outcome at that offset. It's null when the offset isn't a point of the final
  grid.
- **`matches_result`** says whether they agree. False is expected now and then near a design's capture edge, where a
  grasp isn't repeatable. Show both, and say when they differ.
- **A failed clip:** `"status": "failed", "error": "can't reach the sim server at http://127.0.0.1:9000: ..."`. The
  error is a one-line reason, to show as it is.

**Play it:** `GET /api/jobs/{id}/clips/{clip_id}.mp4?view=closeup|side`.

- The default view is `closeup`.
- It's H.264 video, which plays in a `<video>` element straight from that URL.
- It answers 409 until the clip is ready, or when the clip lacks that view.

**Errors**

| Code | When |
| --- | --- |
| 404 | Unknown job, design label or clip. An unknown label's message lists the experiment's labels. |
| 409 | The experiment hasn't run its final test; it ran on the mock sim ("... clips need an experiment run on the Isaac sim"); no GPU is ready (the `not_ready_reason` text, as for jobs); or the video isn't ready. |
| 422 | A bad body: no design, or an offset out of range. |

**Timing**

- A clip takes about 7 s on the GB10, and about 12 s from the request until it's ready, including its worker's
  start. Four clips asked for together were all ready in 50 s.
- Clips queue behind a running job's batches, and behind each other, since the sim server does one thing at a time.
- A Brev GPU doesn't idle-stop while a clip is being recorded.

**Demo data:** demo experiments ran on the mock sim, so they answer 409. To build the UI without a GPU, stand in for
these three calls with the payloads above and any short mp4.

## Results tracker

**Print selection:** `GET` / `PUT /api/jobs/{id}/print-selection {designs: [labels]}`. STOCK and IMP are always tested
as baselines.

**Printed fingers:** `POST /api/jobs/{id}/printed-fingers {design_label, side: L|R|pair, material, print_date?, notes?}`
returns `finger_id` (e.g. `EXP-0001-D1-L`), the ID engraved on the finger.

**Test plans:** `POST /api/jobs/{id}/test-plans {pointwise_repeats=3, random_per_design=30, seed?}` returns 201.

- Each design gets 25 point-wise offsets, repeated, plus seeded random offsets drawn from the job's error model.
- The sim's prediction runs in a worker. Poll `GET /api/jobs/{id}/test-plans/{plan_id}` until `prediction_status` is
  `done` (or `failed`, then `POST .../predict` retries).

**Spreadsheets out:** `GET .../{plan_id}.xlsx` (dropdowns; the prediction column is hidden) and `.../{plan_id}.csv`.

**Spreadsheets in:** `POST .../{plan_id}/upload` (multipart, field `file`) returns
`{accepted, extras, unchanged, pending, errors: [{row, trial_id, reason}]}`.

- Valid rows are applied even when others have errors.
- A blank outcome stays pending.
- A re-upload keeps history.
- Rows without a trial ID become extra trials.

**Quick log:** `POST /api/jobs/{id}/physical` logs one trial; `GET` lists them.

**Validation:** `GET /api/jobs/{id}/validation` returns `{badge, sim_backend, designs, mismatches, curve_points}`.

- Per design: predicted vs measured success, the 95% Wilson interval, and agreement ("sim matched reality on 22 of 25
  offsets").
- `mismatches`: per offset, `agreed`, `sim_only`, `real_only`, `mixed` or `pending`.
- `curve_points`: measured success to overlay on the results curves.

**Exports:** `GET /api/export/physical.jsonl?job_id=` and `.csv`.

## Finger library, evaluation jobs and qualifications

The plan is [library-evaluation-backend-plan.md](library-evaluation-backend-plan.md); the user stories are
[Auto-Grasp User Stories](<../Auto-Grasp User Stories.md>). Two libraries, each its own tab: parts (`/api/parts`, above)
and fingers (`/api/fingers`).

### Finger library (stories 7, 8, 16)

**A library finger** is a physical finger, with a fixed code (`FNG-0001`) and a name that can change. `source` is:

- `stock`: a cell's own fingers. One per cell profile, added by the app (at startup and when a cell is created). No
  geometry: the sim uses its own model.
- `generated`: a generation job's final design, added from its results (below). `origin_job_id`, `origin_label` and
  `origin_sim_backend` say where it came from: a design from the mock sim is geometry only.
- `uploaded`: a finger the factory owns, from its CAD.

**Browse:** `GET /api/fingers?cell_profile=&family=&source=&archived=&part_id=&min_success=`, by code.

- `archived` defaults to `false` (archived fingers left out); `true` lists only them; leave it empty for both.
- `part_id`: fingers evaluated on that part; `min_success`: fingers whose best prediction reaches it.
- Each has `parts_evaluated`, `best_success` and `validated_parts`, from its qualifications. Lists leave out the geometry
  (`pieces`, `built_for` are null); `GET /api/fingers/{id}` has it.

**Register (story 7):** `POST /api/fingers`, multipart: `finger_file` (one finger, STEP or STL; the sim mirrors it for the
other jaw), `cell_profile_id`, and optionally `units` (STL), `name`, `family` (`flat`, `vpad`, `imprint`, `other`),
`material`, `pad_friction_static` with `pad_friction_dynamic` (both or neither; neither: the cell's printed pad),
`quantity_on_hand`, `notes`, `mirror` and `upside_down`. 201 with the finger; 415 / 422 / 404 as for parts.

- **It's placed automatically:** the fingertips (lowest point) at z = 0, the face nearest the other finger at x = 0,
  centred across. `mirror` flips it first when its gripping face points +x in the file; `upside_down` when its
  fingertips point up. `warnings` always asks to check the placement on the preview, and says when the finger reaches
  past the free space beside the gripper or past the maximum finger length.

**Preview:** `GET /api/fingers/{id}/geometry` returns `{finger, geometry}`: `geometry.pieces` in the gripper frame with
the jaws closed (as the design previews). A generated finger is shown as built for its own part; the stock fingers are
the twin's model of the real blades (there is no CAD of them), built for no part.

**Edit:** `PATCH /api/fingers/{id}` with any of name, family, material, pad_friction, quantity_on_hand, notes,
archived. The geometry and the cell never change. Archiving leaves it out of new evaluations; old results keep it. The
stock fingers can't be archived: every cell has them, added at startup and when a profile is created.

**Add a generated design (story 16):** `POST /api/jobs/{id}/designs/{label}/library` (optional body `{name}`), for D1,
D2, ... or IMP of a finished generation job. 201 with the finger; 409 for STOCK (already in the library) or a design
added before. It doesn't touch the review gate: printing and mounting still need `/review`.

### Evaluation jobs (stories 9, 10, 12)

**Spec** (`kind: "evaluation"`):

- `part_id`, `cell_profile_id`, `task`, optional `name`;
- `poses`: `[{pose, grasp?}]`. Leave it empty for the part's likely poses (the likeliest if none is). A `grasp` locks
  that pose to one grasp (story 4: the cell can only grip it that way); otherwise its top 3 grasp proposals that aren't
  blocked are tried;
- `finger_ids`: leave null for every unarchived finger for the cell. The cell's stock fingers are always included;
- `error`: leave null for the cell's grasp accuracy.

**Plan:** `POST /api/jobs/plan` with the spec, always 200, `kind: "evaluation"`:

- `poses`: each `{key, label, choice, probability, weight, resting, grasps}`, each grasp `{key ("g0", ...), grasp, part,
  warnings}`;
- `fingers`: `{finger_id, code, name, source, family}`, stock first;
- `rejections`: `{finger_id, pose_key, grasp_key, reasons}` for each finger that can't grip at a grasp (from the geometry
  checks): it's never simulated there and scores 0 at it;
- `totals`: fingers, combinations, simulated, the grids' sizes, search / final / total grasps, and sim requests
  (`batches`, at most);
- `estimate`, `warnings` (the placeholder accuracy, a finger that can't grip anywhere, the mock badge, ...);
- `blockers` and `failed_step`: steps are 1 part, 2 poses, 3 fingers, 4 cell, 5 grasps. A cell with no fingers besides
  its stock ones blocks at step 3.

**Run:** `POST /api/jobs` with the spec: 201 `{id, experiment_id, name, kind}`, then the job list, events, cancel and
resume work as for any job. For several parts at once: `POST /api/jobs/batch` with the spec and `part_ids` (its
`part_id` is ignored): one job per part, sharing a `batch_id`. Every part is checked first; if any is blocked, none is
created (422, each reason prefixed with the part's name).

**How it scores:**

- Every finger is simulated at every grasp of every pose on the search grid.
- A finger's score is the sum over poses of the pose's weight times its best grasp's expected success there.
- The top 3 fingers and stock are then re-tested at their best grasp per pose on the dense grid. The others keep their
  search-grid score.
- It assumes the cell recognises the part's pose and runs that finger's grasp for it. There's no pass bar: the
  manufacturing engineer decides.

**Ranking (story 12):** `GET /api/jobs/{id}/ranking` (409 for a generation job, whose results are `/results`; and
`/results` is 409 for an evaluation job). Partial while the job runs.

- Top level: `status`, `sim_backend`, `part_name`, `error`, `task`, `rescored`, `final` (the dense test has run), `poses`
  (with their grasps), `warnings` (the caveats: flat table, top-down, no height error).
- `fingers`, best first, each with:
  - `rank`, `code`, `name`, `source`, `family`;
  - `success`, `capture_radius_mm`, and `n_grasps` (the simulated grasps the score is based on);
  - `stage` (`final` once re-tested on the dense grid);
  - `best`: per pose it grips, `{pose_key, grasp_key, angle_deg, centre_mm, span_mm, tip_height_mm, jaw_close_mm,
    success, capture_radius_mm, stage}`. That's where the cell has to grip with it (tip height and jaw close are null
    for stock: the sim's own rule);
  - `grasps`: every grasp's search-grid success, or null with `reasons` where it can't grip;
  - `curve`: success at 0.5 to 5 mm of error, for the success-vs-accuracy plot;
  - `qualification_id`, `measured_success`, `real_trials`: real-robot results on this part, if any.

**Re-score:** `POST /api/jobs/{id}/ranking/rescore {error?, task?}`, from the stored outcomes; nothing is simulated or
stored.

**Not good enough? (story 14):** `POST /api/jobs/{id}/generate-spec?finger_id=` returns a generation JobSpec for the same
part, cell, task, accuracy and poses, each pose with `finger_id`'s best grasp, or the pose's best proposal without one.
Open the wizard with it; nothing is stored. To compare the new finger with the library on the same grid and grasps, add
it to the library once it's done, then run the evaluation again (`/duplicate`).

### Qualifications: one finger on one part (story 17)

**A qualification** is unique per finger and part. It holds the latest sim `prediction` (`{job_id, experiment_id,
success, stage, n_grasps, error, task, grasps, sim_backend, created}`; earlier ones in `history`) and the real-robot
`sessions`. Every finished evaluation job updates the predictions of the pairs it covered.

- `GET /api/qualifications?finger_id=&part_id=` (most recently updated first) and `GET /api/qualifications/{id}`.
- `POST /api/qualifications {finger_id, part_id}` creates one (no prediction) for a pair no evaluation has covered, or
  returns the existing one.
- `POST /api/qualifications/{id}/sessions {trials, successes, kind?, predicted_success?, notes?, operator?, date?}` logs a
  session (201). `PATCH` and `DELETE /api/qualifications/{id}/sessions/{session_id}` correct or remove one. 422 for more
  successes than trials.

**Each response also has:**

- `status`: `simulated`, or `validated` once a session is logged;
- `measured_success` and `real_trials`, every session pooled;
- `comparisons`: each `{kind, session_ids, trials, successes, measured_success, wilson_low, wilson_high,
  predicted_success, gap_flagged}`:
  - `natural` sessions (the cell running as usual) are pooled and compared with the prediction;
  - each `commanded` session (deliberate offsets, as our platform runs command them) is compared with its own
    `predicted_success`, the sim's rate at those offsets (a generation job's test plan predicts it);
- `gap_flagged`: a prediction outside the 95% Wilson interval of what was measured;
- `finger_code`, `finger_name`, `part_name`.
