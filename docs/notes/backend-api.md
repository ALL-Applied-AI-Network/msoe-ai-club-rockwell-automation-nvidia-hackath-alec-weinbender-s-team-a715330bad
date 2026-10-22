---
title: Backend API for the input flow and outputs (as built)
source: our own note, written after implementing docs/notes/input-flow-backend-plan.md
author: Alec Weinbender's Team
received: 2026-10-20
kind: note
status: current
---

# Backend API for the input flow and outputs (as built)

**For:** whoever builds the wizard, the job list, the results page and the results tracker.

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
- ten experiments: done, cancelled, interrupted and failed;
- two experiments with print selections, printed fingers and test plans, one validated and one in progress.

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

**Reading parts back:** `GET /api/parts` (newest first) and `GET /api/parts/{id}`.

- **The UWM lab's parts are always there.** At startup the API loads the organizers' CAD of the cell from the repo's
  `cad/` folder into the database, once: the M6 × 30 screw (steel), the bin, the 10 and 16 mm cubes, the vial and its
  cap. They have fixed ids (`lab-m6-screw`, ...), readable names and `lab: true`; uploads have `lab: false`. They're
  ordinary parts otherwise: confirm their material and pose like an upload's. The catalog is
  `app/backend/src/api/models/lab_parts.py`.

- Lists leave out the convex pieces (`measured.pieces` is empty there).
- `measured.extent_mm` is the bounding box. Show it, so a units mistake is caught.
- `measured.material_hint` pre-selects the material.

**Editing:** `PATCH /api/parts/{id}` (JSON). Only the fields sent change. The fields are material, density_g_cm3,
surface, mass_g, mass_unit, fragile, max_grip_force_n, clearance_mm and pose.

- `mass_g: null` means "use the computed mass".
- When the material changes, send `density_g_cm3: null` too, or an earlier density stays.
- Material `"other"` needs a density.

**Computed values in responses:** `computed_mass_g`, `confirmed_mass_g`, `mass_source` (`computed` / `measured`), and
`friction_vs_pad`. The friction comes from the profile when you add `?cell_profile_id=`, else from 0.6 / 0.5.

**Catalogs:** `GET /api/meta` gives materials, surfaces, families with their parameter schemas, error presets, task
kinds with the tolerances each needs, transport speeds, mass units, the sim backend, and `demo_data`.

### Step 2, resting pose

**Poses:** `GET /api/parts/{id}/poses` returns the top 4 stable poses, most likely first, then "as in the CAD file".
Each pose has `index`, `label`, `probability`, `extent_mm`, `rotation` and `chosen`.

**Choosing one:** `PATCH {pose: <index> | "as_authored"}`.

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

### Step 5, grasp

**Proposals:** `POST /api/parts/{id}/grasps {cell_profile_id}` returns `candidates`, `rejected` and `nothing_fits`.

- `candidates`: the top 1–3. Draw each as an arrow: `angle_deg` from +x, at `centre_mm`.
- `rejected`: a short note on why the other directions were rejected.
- `nothing_fits`: when nothing fits, the exact reason and ordered `suggestions`.
- Needs a chosen pose; 409 otherwise.

**Manual choice:** `POST /api/parts/{id}/grasps/check {cell_profile_id, angle_deg?, picks?, grip_height_mm?}`.

- `picks` are one or two `{point, normal}` from a raycast against the table-frame mesh.
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
- Each finger has `pieces`, `closed_gap_mm` and `problems`.

### Step 7, camera error and grid

**Error model:** the spec's `error` is `{preset, sigma_mm, sigma_range_mm?, sigma_deg, bias_mm, bias_direction_deg}`.
The presets are in `/api/meta`; the placeholder ones say so.

**Grid preview:** `POST /api/grids {part, error, final?}`.

- Returns `points`, each with its weight; the 1σ and 2σ circles; the outer ring; the yaw layers; and warnings.
- It takes milliseconds, so call it on every slider move.

### Step 8, review and run

**Plan:** `POST /api/jobs/plan <JobSpec>` always returns 200. The body is the plan:

- `part`, `families`, `searches` (method, budget, batch size);
- `totals`: grasps, designs, rounds;
- `estimate`: seconds, or null while the throughput is unknown;
- `warnings`;
- `blockers: [{step, reason}]`, plus `failed_step`, the step to send the user back to.

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

**Cards:** `GET /api/jobs?part_id=&status=&backend=` returns cards, newest first. A card has:

- `experiment_id`, `name`, `part_name`, `task_kind`, `sim_backend`, `status`;
- `round` / `n_rounds`, `n_done` / `n_total`, and `best_value` (best predicted success so far);
- once done, `winner` and `stock`, each `{label, success, capture_radius_mm}`;
- once failed, `failure` (one line) and `failed_step`;
- `physical_badge`: `none`, `in_progress` or `validated`.

**Live updates:** `GET /api/jobs/{id}/events` is SSE, sending the card on every change and ending when the job finishes.

**Statuses:** queued → running → finalizing → done; also failed, cancelled and interrupted.

**Other calls**

- `PATCH /api/jobs/{id} {name}` renames.
- `POST /{id}/duplicate` returns a JobSpec named "… (copy)" for the wizard to edit and re-submit, with
  `duplicated_from`. It doesn't start a run.
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

**3D preview:** `GET /api/jobs/{id}/finger?design=D1` returns the part, the finger and its mirror (`right`), with
`jaw_open_mm`.

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
