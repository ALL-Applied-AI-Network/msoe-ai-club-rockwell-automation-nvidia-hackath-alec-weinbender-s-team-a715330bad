---
title: "Frontend plan: screens and user flows"
source: our own plan, from the backend as built (2026-10-20) and the 2026-10-19 input flow, pipeline and outputs specs
author: Alec Weinbender's Team
received: 2026-10-20
kind: note
status: current
---

# Frontend plan: screens and user flows

**For:** the developer building the new UI in `app/frontend`.

**What it covers:** which screens the app needs, what the user does on each, what each one must show and warn about, and
which API calls back it. How to build them (state, component code) is up to you, within the repo's rules.

**Read with:**

| Doc | For |
| --- | --- |
| [backend-api.md](backend-api.md) | Every call a screen makes, and the behaviour the schema doesn't show. This plan links to it instead of repeating it. |
| `/docs` (Swagger) and `src/backend/schema.d.ts` | Exact request and response shapes. Regenerate the types with `npm run gen:api`. |
| [`.claude/rules/coding-style.md`](../../.claude/rules/coding-style.md), "Frontend" | Component reuse, design tokens, text style, no emojis, no arrow glyphs. |
| [SETUP.md, "GPU from the web app"](../../SETUP.md#gpu-from-the-web-app) | What each user sets up for Brev and the GB10. The GPU help in this plan points there. |
| [CONTEXT.md](../../CONTEXT.md), "Key risks" 5–7 | Why real-twin scores need caveats (section 10). |
| [app/README.md](../../app/README.md) | How a job runs, GPU sessions, the sim contract. |

**The 2026-10-19 specs** (input flow, pipeline, outputs) were written before the backend was built. Their screens and
order still hold, and this plan follows them. Where they differ from what was built, this plan follows the backend;
section 14 lists the differences.

## Contents

1. [Where the frontend stands](#1-where-the-frontend-stands)
2. [Rules for every screen](#2-rules-for-every-screen)
3. [App map and journeys](#3-app-map-and-journeys)
4. [GPU: choosing compute, and help when it won't connect](#4-gpu-choosing-compute-and-help-when-it-wont-connect)
5. [New experiment wizard](#5-new-experiment-wizard)
6. [Experiments list and progress](#6-experiments-list-and-progress)
7. [Results page](#7-results-page)
8. [Physical validation: simulated vs real trials](#8-physical-validation-simulated-vs-real-trials)
9. [Settings](#9-settings)
10. [Caveats the UI shows](#10-caveats-the-ui-shows)
11. [Shared components to build](#11-shared-components-to-build)
12. [Priorities and build order](#12-priorities-and-build-order)
13. [Backend gaps you'll meet](#13-backend-gaps-youll-meet)
14. [Where this differs from the 2026-10-19 specs](#14-where-this-differs-from-the-2026-10-19-specs)

## 1. Where the frontend stands

**Stack** (pinned in `package.json`): Vite, React 19, TypeScript, TanStack Query for server data, React Router with
hash routes (`#/jobs/...`), `openapi-fetch` as the typed API client, CSS modules on design tokens (NVIDIA Brev's look,
dark only), three.js for 3D, and Recharts for every chart.

**Built (2026-10-22), on the `frontend-shell` branch:** every screen in sections 3 to 9, against the demo data.

| Area | Where | Notes |
| --- | --- | --- |
| Shell: top bar, sim badge, GPU chip, demo banner | `components/Page.tsx`, `GpuChip.tsx` | The app is called Auto-Grasp. Nav: Experiments (home), Parts, Validation, Settings. |
| Experiments list with live cards | `pages/experiments/` | SSE per running card on screen; polls past 6 running. |
| Wizard, all eight steps | `pages/wizard/` | `draft.tsx` holds the draft (localStorage too) and the debounced plan; each step reports its gate. |
| Experiment page: progress, then results | `pages/job/` | Re-score bar, curves, held maps (click a dot to pick a clip), in-hand, failures, best finger and downloads, clips, final test with print boxes, review gate, run details. |
| GPU page and help cards | `pages/gpu/`, `gpuHelp.ts`, `components/HelpCard.tsx` | Starting steps, retries as "Retrying", switch-target flow, session log, setup checklist. |
| Validation, per experiment and across them | `pages/validation/` | The five stages, the spreadsheet round trip, predicted vs measured, the mismatch map, the sim-vs-real scatter. |
| Quick logger | `pages/log/` | Phone layout; no Undo yet (no API to delete a trial). |
| Parts library | `pages/parts/` | The UWM lab's parts (always loaded by the backend) first, then uploads; upload, size check, 3D view, material and mass. |
| Settings | `pages/settings/` | Cell-profile editor with placeholders and version history; GPU targets and About, read-only. |

**Not built:** the design-space cloud (Later), the 3D robot and cell render (no model endpoint), and richer provisional
results and several grasp axes (both need the backend changes in section 13). The old `index.html` is still served at
`/` until the switch-over steps in [app/README.md, "Frontend"](../../app/README.md#frontend).

**The rules for adding to it:** [coding-style.md](../../.claude/rules/coding-style.md#frontend) lists the shared
components. Reuse them, keep API types generated (`npm run gen:api`), and use `unwrapAs` in `src/backend/client.ts`
when a response holds tuples.

**Running it:**

1. Start the backend.
2. Run `npm run dev` in `app/frontend`.
3. Open <http://localhost:5173/app.html>.

**Data to build against:** put `DEMO_DATA=true` in `.env`. You get ten experiments in every state, including runs still
in progress, plus parts, cell profiles, printed fingers and test plans
([backend-api.md, "Demo data"](backend-api.md#demo-data)). Demo results come from the mock sim and its physical trials
are made up, so show a banner whenever `GET /api/meta` says `demo_data: true`.

## 2. Rules for every screen

These hold on every page. Most of the design work is applying them consistently.

1. **Show which simulator made a result.** Every job, card, chart and export carries `sim_backend`: `mock` or `isaac`.
   Show it as a badge everywhere a result appears. A mock result checks capture geometry only, so it is never a
   prediction. Say so wherever its numbers appear, not only in the badge. Downloads from mock runs already carry
   `_MOCK` in their file names.
2. **Show the sim path on real-twin results.** The Isaac sim server runs in one of three ways, which differ in speed
   and trust ([CONTEXT.md](../../CONTEXT.md) risk 7). The results' `run.sim` block reports `envs` and `device`:

   | `envs`, `device` | Label | Treatment |
   | --- | --- | --- |
   | 1, `cpu` | Reference | The baseline. No flag. |
   | more than 1, `cpu` | CPU copies | Matches the reference. No flag. |
   | more than 1, `cuda...` | GPU copies | Flag as **exploratory**: it holds about 9 of 81 more grasps than the reference, repeatably. |

3. **Put the caveats next to the numbers they qualify** (section 10), not on a separate page.
4. **Every number has a unit**: mm, degrees, g (or the user's mass unit), %, s. All formatting goes through `format.ts`.
5. **Long work runs in the background.** A job's optimisation and a test plan's prediction run in detached processes on
   the machine running the backend. Closing the page, or restarting the API, ends nothing. Never make the user wait on
   a spinner for them: show progress, let them leave, and pick it up again when they come back.
6. **Turn errors into next steps.** A 409 with `not_ready_reason` means no GPU is ready, so offer to connect one (4.6).
   A 422 or a failed job with a `failed_step` means an input is wrong, so link to that wizard step. A GPU error gets a
   help card (4.5). Show the backend's `detail` text, which is written to be shown.
7. **The experiment name is the headline.** Show the name and ID together, for example "Vial cap, lying (EXP-0042)".
   The ID never changes, and it's what printed fingers and logged trials refer to.
8. **One look across the app** ([coding-style.md](../../.claude/rules/coding-style.md#frontend)):
   - Shared components only; section 11 lists the ones still to build.
   - Tokens only. Dark only, in the style of NVIDIA Brev (decided 2026-10-22).
   - Sentence-case text that says what happens.
   - No emojis, and no arrow or check glyphs in place of words.
9. **Nothing the app can't undo happens without asking.** Stopping a Brev instance, cancelling a job and approving a
   finger for the robot each take a confirmation that names what will happen.

## 3. App map and journeys

### Pages

| Route | Page | Section |
| --- | --- | --- |
| `#/` | Experiments: the job list (home) | 6.1 |
| `#/new/<step>` | New experiment wizard, steps `part`, `pose`, `task`, `cell`, `grasp`, `families`, `error`, `review` | 5 |
| `#/new/<step>?from=<job id>` | The wizard, prefilled from a duplicated or failed experiment | 5.0 |
| `#/jobs/<id>` | One experiment: live progress while it runs, results once done | 6.2, 7 |
| `#/jobs/<id>/validation` | Physical validation for one experiment: print, plan, log, compare | 8 |
| `#/jobs/<id>/log` | Quick logger for phone or tablet at the robot (later) | 8.4 |
| `#/validation` | Sim vs real across experiments (later) | 8.5 |
| `#/parts` | Parts library: every uploaded part, reusable in a new experiment | 5, step 1 |
| `#/gpu` | GPU: targets, the current session, the session log, help | 4 |
| `#/settings/cells`, `#/settings/cells/<id>` | Cell profiles: list, edit, versions | 9.1 |
| `#/settings` | Settings home: cell profiles, the enabled GPU targets, about | 9 |

**The header** (part of `Page`, on every page) carries:

- the app name, Auto-Grasp, which links home, and the navigation: Experiments (home), Parts, Validation, Settings.
  New experiment is the main button on the Experiments page, not a nav item;
- the sim badge from `GET /api/meta` (`sim.badge`): Mock or Isaac;
- the GPU chip (4.2), which opens the GPU page or a drawer;
- the demo-data banner, when it applies.

### Journeys the app must support

**A. First experiment**

1. The GPU chip says no GPU is connected.
2. The user connects the GB10, or starts Brev, from the chip.
3. New experiment, eight steps (5).
4. Run. The experiment page shows live progress (6.2).
5. Results (7).

**B. Coming back later**

1. The Experiments page shows every card, with progress still updating live.
2. The user opens a finished one and reads the results.

Nothing was lost while the page was closed.

**C. Print and validate**

1. On the results page, mark designs to print.
2. Record the printed fingers. The app gives each one its engraved ID.
3. Create a test plan, and wait for its sim prediction.
4. Download the spreadsheet and fill it in at the cell, or use the quick logger.
5. Upload it.
6. The sim-vs-real views fill in (8).

**D. Explore without simulating again**

- Re-score the results at another camera error or task (7.2).
- Duplicate the experiment to start from the same inputs for a similar part (6.3).

**E. Something goes wrong**

- **The GPU won't connect:** a help card says what to do (4.5).
- **A job fails:** its card says why in one line and links to the step that fixes it, and Resume continues it (6.3).
- **The VPN drops mid-run:** the job waits, and the chip says why (4.7).

## 4. GPU: choosing compute, and help when it won't connect

### 4.1 What the user is choosing

The Isaac sim runs on one GPU target at a time. The backend forwards the connected target to the app's `SIM_URL`, so
nothing else in the app knows or cares which machine it is. Which targets appear comes from the backend's `.env`
(`COMPUTE_BACKENDS`); the UI only lists and drives them.

| | MSOE GB10 (`spark1`) | Brev |
| --- | --- | --- |
| Role | The team's default: free, always on | Paid backup |
| Shared | With other teams | Team only |
| Buttons | **Connect** / **Disconnect** | **Start the GPU** / **Stop the GPU** |
| Disconnect or stop | Closes only this laptop's connection. The sim server keeps running for teammates. | Stops the instance. |
| Ends by itself | Never | After `auto_stop_minutes` (default 20) with no job or prediction running |
| Time to ready | Seconds if the team's sim server is already running. About 10–25 s to start it. A first start after a reboot can take minutes (the shader cache). | About 3 minutes to boot a stopped instance, plus about a minute for Isaac Sim |
| Cost | Free | Team credits ($3.07/hr for the current instance). The API doesn't report credit balance (section 13): link to the Brev console's Billing tab. |
| Needs | The MSOE VPN, and the user's SSH key on the team account | The Brev CLI logged in |
| Load | `other_gpu_processes`: another team's or a teammate's work on the GPU. Show it; don't block on it. | |

**What the UI never does:**

- create a Brev instance (that's the Brev console);
- stop the GB10 or its server;
- connect a second target while one is active.

To switch targets, the user stops or disconnects the current one first. The start call answers 409 with a message that
says exactly that; offer a button that does it.

**Mock targets:** with `COMPUTE_BACKENDS=mock` (the default) the list shows two made-up targets, and sessions run
against them. That's for working on the UI offline. With only the mock enabled, `managed` is false and jobs never wait
for a GPU.

### 4.2 The GPU chip (header, every page)

One compact status that's always visible, from `GET /api/compute`. Poll it every 3 s while a session is active and every
15 s otherwise.

| State (from the API) | Chip text | Tone |
| --- | --- | --- |
| `managed` false | Mock sim: results aren't predictions | warn |
| No session, `managed` | No GPU connected | warn |
| `session.status` starting | Starting: `<instance>` | active |
| ready, Brev | Ready: `<instance>` | ok |
| ready, GB10 | Connected: spark1 | ok |
| ready, but the message says the sim isn't answering | Reconnecting: `<instance>` | warn |
| stopping | Stopping: `<instance>` | warn |
| No session, `last` failed | GPU failed: open for details | bad |

Clicking it opens the GPU page, or a drawer holding the same panel.

### 4.3 The GPU page

The GPU page has four parts:

1. **Current session:**
   - the target, its backend, the status badge and the session's `message`;
   - how long it has been up or connected;
   - for the GB10, "On spark1 right now: N other GPU processes";
   - the Stop or Disconnect button.
2. **Choose a target** (when nothing is active):
   - one card per target from `GET /api/compute/instances`, each with its name, GPU, the provider's status, and for
     the GB10 the other GPU processes;
   - the right button for each: **Start the GPU** or **Connect**;
   - a Refresh button. The list call takes a few seconds (it asks Brev's CLI and ssh's into the GB10), so show a
     loading state on the list, not the page.
   - A backend that couldn't be asked comes back in `errors`. Show its help card (4.5) where its targets would be;
     the other backends still list.
3. **Session log:** `GET /api/compute/sessions`, a table of which target was connected when, for how long, and why it
   ended (`stop_reason`: ended from the app, idle, stopped outside the app, failed). This is the record of GPU time and
   credits.
4. **Help:** the setup checklist per target, short, linking to SETUP.md: the VPN and SSH key for the GB10, WSL and the
   Brev CLI for Brev. Show it open when nothing has ever connected.

### 4.4 Starting: show the steps, and treat retries as normal

While a session starts, its `message` names the current step. Show the steps as a list, mark the current one, and show
the time elapsed, so a 4-minute Brev boot doesn't look stuck. The backend's messages:

| Message (prefix) | Step |
| --- | --- |
| `Starting <name> (a few minutes)` | Brev: booting the instance |
| `Waiting for the instance's Isaac container` | Brev: the container is coming up |
| `Starting the sim server (Isaac Sim takes about a minute)` | Starting Isaac and the sim server |
| `Isaac Sim hung while starting, as it sometimes does; trying again (2 of 3)` | GB10: an automatic retry |
| `Isaac Sim exited while starting, as it sometimes does; trying again (3 of 3)` | GB10: an automatic retry |
| `Connecting to the sim server` | Opening the port forward |
| `Connected; ...` or `Ready; ...` | Done |

Isaac Sim fails about one start in four on the GB10 (it hangs, or crashes in the graphics driver). The backend kills
and retries it, up to 3 starts. **A retry is not an error:** show it in the neutral or warn tone, as "Retrying", never
red. Only `status: failed` is a failure.

### 4.5 Help when it won't connect

Errors reach the UI as text, in three places:

- `GET /api/compute/instances` `errors[].message`: the backend couldn't be asked;
- a failed session's `message`;
- the `detail` of a 409 or 502 from `POST /api/compute/start`.

Put a **help card** beside each one, with:

- what it means;
- the fix, in one or two steps;
- a link to the SETUP section;
- a **Try again** button, which refreshes the list or connects again.

Map the messages in one module, by substring, until the backend sends error codes (section 13). The messages and their
help:

| The message contains | Means | The help card says |
| --- | --- | --- |
| `can't reach the GB10` ... `connect the MSOE VPN` | No VPN, or off campus without it | Connect GlobalProtect, then Try again. SETUP "MSOE VPN". |
| `the GB10 refused the login` ... `add your SSH key` | This user's key isn't on the team account | Add your SSH key, once, with the steps in SETUP "Your SSH key on the GB10". Then check it with the command there. |
| `the GB10's host key changed` | The GB10's identity changed | Don't work around it: ask in `#compute-questions`. It can mean you're not talking to the real GB10. |
| `GB10 not set up` | The repo or Isaac is missing there | Whoever maintains the GB10 sets it up again (GPU test plan). Not fixable from the app. |
| `port 9011 on the GB10 is held by another account` | Another team took the team's port | Agree a new port with the team; everyone sets `COMPUTE_GB10_SIM_PORT`. |
| `a teammate is starting the GB10's sim server` | A teammate's Connect is starting it right now | Wait a minute, then Connect again. |
| `Isaac Sim didn't start on spark1 in 3 tries` | Three failed starts in a row (rare) | Connect again. If it repeats, read `runs/sim_server.log` on the GB10 and ask the team. |
| `brev ls failed` or `can't run the Brev CLI` | The Brev CLI isn't installed, logged in, or reachable through WSL | Run `brev login` in Ubuntu. On Windows, set `COMPUTE_BREV_WSL=Ubuntu`. SETUP "Brev CLI". |
| `is FAILURE on Brev after the start request` | Brev couldn't start it | Check the Brev console for a service notice first (on 2026-10-20 Brev had AWS disabled), then the instance's Activity Logs. If no GPU of that type is free, try later, or use the GB10. |
| `the port forward` ... `exited` | The local tunnel died | Often something else is using local port 9000. See `compute_forward.log`. |
| `The sim server isn't answering` ... `running jobs wait up to` | The connection dropped mid-session, usually the VPN | Reconnect the VPN. The panel reconnects by itself, and running jobs carry on (4.7). |
| 409 `disconnect it before starting another target` or `stop it before starting another target` | Another target is active | Offer **Disconnect the GB10** or **Stop `<instance>`**, then start the chosen one. |
| The API itself doesn't answer | The backend isn't running | A full-page "Can't reach the app's backend" state, with how to start it (SETUP "Day to day"). |

The help cards double as the app's setup guide. A new user who has never connected sees the checklist (4.3) first,
then whichever card their first error needs.

### 4.6 Jobs wait for a ready GPU

When `managed` is true, the API refuses to start sim work without a ready session:

- **A new job** (`POST /api/jobs`) and **a resume** answer 409 with `not_ready_reason`.
- **A test plan** is still created, but its prediction fails, with the reason in `prediction_error`.

In the UI:

- **Disable Run and Resume** while `not_ready_reason` is set. Show the reason under the button, with a **Connect a GPU**
  button that opens the GPU drawer. Enable them as soon as the session is ready; poll `/api/compute` while the user
  waits on that screen.
- **Predict again:** show a **Predict again** button on the test plan once the GPU is ready.

### 4.7 A dropped connection during a run

Jobs survive a dropped VPN or port forward:

- A round whose connection drops waits up to `SIM_RECONNECT_MINUTES` (default 120) for the sim to answer again.
- The session reconnects by itself as soon as the target is reachable.
- The round then carries on from the sim server's own result, without being run again.
- Past the limit, the job fails with "... reconnect the GPU in the GPU panel, then resume the job". Resume carries on
  after its last finished round.

**What the UI shows:**

- The chip turns to Reconnecting.
- Every running card and the running experiment page show the GPU message, "Waiting for the GPU connection", so a
  stalled progress bar has a reason.
- Nothing asks the user to restart anything.

**Backend gap:** the API has no structured "reconnecting" flag yet, only the session's message text (section 13).

## 5. New experiment wizard

### 5.0 How the wizard works

**Layout:** one shared step layout for all eight steps.

- A step list down the side, each step marked done, current, needs attention or blocked.
- The step's content in the middle.
- A summary rail on the right: a part thumbnail, the key choices so far, and the live run estimate from step 4 on.
- Back and Next at the bottom.

Each step is a route (`#/new/part`, ...), so the browser's Back works and a failure can link to its step.

**The draft:**

- **Parts** are stored on the server as soon as they're uploaded (step 1), and they're edited with `PATCH`.
- **Cell profiles** are stored in Settings.
- **The job spec itself** isn't stored until Run. Keep it in client state, and also in `localStorage` (a per-browser
  convenience) so a reload doesn't lose a half-filled wizard.

**Validation:**

- Each step checks its own fields as the user types.
- From step 4 on, `POST /api/jobs/plan` with the draft spec is the single source of truth. It's cheap, never stores
  anything, and always answers 200.
- Call it, debounced, whenever the spec changes. Its `blockers[].step` mark steps as blocked in the step list, its
  `warnings` show on the review step, and its `estimate` feeds the summary rail.

**Prefilled runs:**

- **Duplicate:** `POST /api/jobs/<id>/duplicate` returns a spec named "... (copy)". Open the wizard on it at step 1.
- **Failed experiment:** opening the wizard from a failed experiment's "Fix in step N" lands on that step with the
  spec prefilled.
- **Part library:** "New experiment with this part" from the parts library starts at step 2 with the part set.

**What each step is for:**

| Step | The user decides | Backed by |
| --- | --- | --- |
| 1 Part | the name, the CAD file, material and mass | `POST /api/parts`, `PATCH /api/parts/<id>`, `/api/meta` |
| 2 Resting pose | how the part sits on the table | `GET /api/parts/<id>/poses`, `/mesh` |
| 3 Task | what counts as success | spec only; `/api/meta` task kinds |
| 4 Cell profile | which saved robot, gripper and cell | `/api/cell-profiles` |
| 5 Grasp | the closing direction | `POST /api/parts/<id>/grasps`, `/grasps/check` |
| 6 Finger families | what's searched, and over which ranges | `POST /api/jobs/plan`, `POST /api/fingers/preview` |
| 7 Camera error | the error level, and the offsets tested | `POST /api/grids` |
| 8 Review and run | check everything and start | `POST /api/jobs/plan`, `POST /api/jobs` |

The calls' details are in [backend-api.md, "Input steps"](backend-api.md#input-steps). Each step below says what the
user sees and what to warn about.

### Step 1: Part

**Name the experiment**

- A text field, first on the page.
- Left blank, the backend names it "<CAD file stem>_<date>". Show that as the field's placeholder, so the user knows
  what they'll get.

**Choose the part:** either upload a new one, or pick one from the parts library (`GET /api/parts`).

**Upload a CAD file**

- STEP is preferred: exact geometry and units.
- STL is accepted, but has no units, so ask mm or inches before uploading.
- A SolidWorks file is refused (415) with the hint "In SolidWorks: File > Save As > STEP". Show that hint near the drop
  zone before anyone tries.
- The hackathon's own CAD files are in the repo's `cad/` folder ([docs/07-cad-models.md](../07-cad-models.md)): the
  vial, the cap, the cubes and the screws. Another teammate is adding CAD context there now, so check that doc when you
  build this step. Offering a few as one-click samples helps both demos and testing.

**Check the size**

- Show the bounding box (`measured.extent_mm`) large, in mm, right after the upload. It's how a units mistake gets
  caught: a 10 mm cube showing as 254 mm.
- Show a 3D view of the part (`GET /api/parts/<id>/mesh`).

**Material and mass**

- **Material:** a dropdown from `/api/meta` materials, preselected from `measured.material_hint` when the file names
  one. "Other" needs a density.
- **Surface** (optional): from the meta surfaces. It scales the friction.
- **Mass:**
  - Show the computed mass, in the user's unit (g, kg, oz, lb from `mass_units`).
  - Let the user confirm it, or type a measured value instead.
  - Show which one is used (`mass_source`).
- **Fragile**, with an optional max grip force; and **clearance to neighbours** in mm (both optional).

**Weak-grip warning:** if the confirmed mass is over about 100 g, or the friction is low, warn here:

> The real twin grips with only about 2.5 N per jaw today. Parts over about 100 g, or slippery ones, will score as
> dropped for every design.

That's CONTEXT.md risk 6. It's a warning, not a block.

### Step 2: Resting pose

- **Thumbnails:** show the top 4 stable poses as small 3D thumbnails, most likely first, each with its label
  ("standing", "on its side") and likelihood. Add "As in the CAD file". One click chooses.
- **Box and cylinder:** for these the answer is obvious, so the step is one click. Preselect the most likely pose, and
  let Next accept it.
- **A note under the thumbnails:** "In a real cell, parts usually arrive in a tray or fixture, so you already know the
  pose. One pose per experiment: if parts arrive both ways, run two."

### Step 3: Task

**The kind of task:** pick and drop, pick and place, or pick and insert (`/api/meta` task kinds). A small table helps:

| Task | Counts as success | Tends to favour |
| --- | --- | --- |
| Pick and drop | Held through the lift (and the transport, if on) | Most slack, widest capture |
| Pick and place | Held, and the part sits within the offset tolerance | Centring features: V-groove, lead-in |
| Pick and insert | Held, within the offset and tilt tolerances | Strong centring, a grip that holds the part's shape |

**An example video of each task, from Isaac Sim.** Clicking a task (or focusing it with the keyboard) shows a short
video of it next to the choices, so the user sees what they're picking before they read the table.

- **What they show:** the twin's FANUC arm and stock fingers pick a 10 mm cube, lift it, carry it 10 cm, and then:
  - **drop:** open over a bin, and the cube falls in;
  - **place:** set it down on a marked square;
  - **insert:** lower it into a square socket 0.75 mm wider than the cube on each side, and let go.
- **They're the same for everyone.** It's one default example per task, not the user's part or fingers. Caption it:
  "Example in Isaac Sim: the robot's stock fingers and a 10 mm cube. Your part and fingers will differ."
- **What the sim actually scores:** the grasp, the lift, any transport move, and how the part sits in the hand. It
  doesn't simulate the drop, the place or the insert themselves; a place or insert counts as a success when the part
  sits in the hand within the tolerances. Put that under the video in one line, so the video doesn't overpromise.
- **The files** are in `app/frontend/public/task-examples/`, served at `/task-examples/<task>.mp4`. Each has a still of
  its result at `/task-examples/<task>.jpg`, for the video's poster. `<task>` is the task kind's `name` from
  `/api/meta`: `drop`, `place` or `insert`.

  | File | Length | Size |
  | --- | --- | --- |
  | `drop.mp4` | 7.5 s | 337 KB |
  | `place.mp4` | 8.4 s | 404 KB |
  | `insert.mp4` | 8.4 s | 408 KB |

  All are H.264, 1280 × 720, 30 fps, with no sound.
- **How to play them:**
  - Autoplay, muted, looping and inline (`autoplay muted loop playsinline`), with the still as the poster.
  - If the user prefers reduced motion (`prefers-reduced-motion`), show the still with a Play button instead.
  - Give the video a text alternative that describes the task in words.
  - Use the same video component as the Isaac Sim clips (7.5).
- **To make them again** (for example after a change to the twin, or for another object): run
  `sim/sim_server/scripts/record_task_examples.py` with Isaac's Python on a GPU machine, then re-encode for the web
  (`-c:v libx264 -crf 24 -preset slow -pix_fmt yuv420p -movflags +faststart -an`). The script says how.

**The fields:**

- **Tolerances:** show only the fields the kind needs. `task_kinds[].tolerances` lists them: an offset tolerance in mm
  for place and insert, plus a tilt tolerance in degrees for insert.
- **Transport** (optional): slow, normal or fast, with each one's move time from the meta. It adds a quick move after
  the lift to test how secure the grip is.

**A note:** the task changes which finger wins, not how the search runs, and it can be changed afterwards on the
results page without simulating again (7.2).

### Step 4: Cell profile

**Choose and confirm:** pick a saved profile (`GET /api/cell-profiles`), then Confirm. A job records the exact profile
version it ran with.

**Show the fields that matter** to this run:

- the robot and gripper model;
- the stroke per jaw;
- the stock fingers;
- the free space beside the gripper;
- the pad friction;
- the finger mount.

**Two kinds of warning:**

- **`to_confirm` fields** are placeholders until measured at the cell. Mark each one "placeholder".
- **`twin_mismatches`** are where this profile differs from the gripper the sim actually models (the twin's SMC
  MHZL2-16D2). Show them as warnings: results for such a profile simulate the twin's gripper, not this one.

**Edit in Settings:** a link that opens the profile in Settings (9.1). Saving there makes a new version, and the wizard
picks it up.

**Later:** a 3D render of the robot, gripper and stock fingers. The API serves no robot model yet. Until then, show the
gripper's numbers and the stock finger from the finger preview.

**Why this step comes before the grasp:** which grasps fit depends on the gripper's stroke, so confirming the cell
first means the grasp step's proposal is right the first time.

### Step 5: Grasp

**Auto proposal:** call `POST /api/parts/<id>/grasps`.

- Draw the top 1–3 candidates as arrows on a top-down or 3D view of the part in its pose.
- Show `rejected` as a short note on why the other directions don't work.
- The first candidate is preselected.

**When nothing fits:**

- Show `nothing_fits` prominently: the exact reason (for example "narrowest width 31.7 mm; stock fingers open at most
  12 mm") and the ordered suggestions.
- Disable Next. Never let a run start that can't work.

**Manual choice:** the user clicks two faces on the 3D view (raycast picks), or types an angle.

- `POST /api/parts/<id>/grasps/check` returns a verdict: ok, warn (show the warnings, allow Next) or blocked (show why,
  disable Next).
- **Grip height:** by default the optimizer chooses it. A lock lets the user fix it.

**Several axes** (wanted; the backend doesn't support it yet, see section 13):

- A **Try several grasp axes** option lets the user tick two or three of the candidates, or add a manual one.
- Each ticked axis gets its own search per family, and the final test picks the winner across all of them.
- Show what it costs: run time multiplies by the number of axes. The plan's totals show it once the backend plans it.
- The results then name each design's axis (7.1).
- Until then, the spec takes one axis: build the option behind a flag, or leave it out.

### Step 6: Finger families and ranges

**Families**

- One tick box per family from `/api/meta`.
- Only V-pad is built. Show the planned families (imprint with clearance, curved cradle) disabled, labelled
  "planned", with their one-line description.

**Parameters**

For each ticked family, one row per parameter from the plan's `families[].params[]`. Each row has:

- a range slider over the buildable `limits`, starting at `default_range`;
- a lock toggle, which turns the range into a single value;
- the parameter's description (from `params_schema`) and unit;
- the `note` when the range was clipped to what's buildable;
- a greyed-out row, with the reason, where `applies` is false (for example the groove angle on a box).

The V-pad's six parameters are pad width, groove angle, groove depth, slack, tip height and lead-in.

**Closed gap:** where the pads meet with the jaws fully closed. It isn't a seventh parameter, because it's set by the
slack: closed gap = part width + 2 × slack − 2 × stroke per jaw (the jaws always open the full stroke before closing).

- Show it beside the slack slider, in mm, for both ends of the range: "pads meet at 0.4 to 3.6 mm when fully closed".
- Each finger preview also reports it (`closed_gap_mm`).
- A user who thinks in closed gap rather than slack is setting the same thing. If that comes up, let the slider show
  either one; don't add a second control.

**Test my own design:** locking every parameter makes a single-design evaluation. Label that state clearly ("Testing
one design: every parameter is fixed"); it's how an engineer checks a finger they already have.

**Previews**

- **Start with this:** while a slider is focused, draw the finger at that parameter's min and max as two ghosts, with
  the others mid-range (`POST /api/fingers/preview` with `vary`). Each preview also returns `closed_gap_mm` and any
  `problems`.
- **Later:** a design-space cloud, about 30 sampled designs drawn as translucent overlays.

**Budget**

- An optional "designs per search" field. Left unset, it's 128 for the Bayesian search, and 16 or 32 for a sweep.
- Show the plan's method, budget and batch size per search, and the time estimate, all updating live.
- More free parameters need more designs, so the estimate visibly grows as ranges open up.

### Step 7: Camera error and test grid

The screen that explains the method at a glance.

**Error level**

- **Presets** come from `/api/meta`. Mark the placeholder ones "placeholder until measured on the cell", with each
  preset's note.
- **Custom:** sigma in mm, plus yaw sigma in degrees (yaw only matters for boxes and lying cylinders).
- **"Design for a range"** of sigmas costs nothing extra; say so.
- **Bias** (optional): a systematic offset in mm and its direction. The grid preview warns when bias plus 2σ reaches
  past the outer ring.

**The grid view** (`POST /api/grids`, fast enough to call on every slider move):

- a top-down view of the part outline, with a dot for every offset tested;
- each dot's opacity is its weight under the chosen sigma;
- the 1σ and 2σ circles and the outer ring drawn on it;
- for parts where yaw matters, the yaw layers;
- a line under it: "Changing sigma never needs new simulations: results re-score at any sigma."

**The size of the run:** show the grid's point count, and the plan's total grasps. Testing yaw triples them.

### Step 8: Review and run

**One summary screen**, a section per step, each with an Edit link back to its step:

- the part (thumbnail, size, material and mass) and its pose;
- the task, with its example still (`/task-examples/<task>.jpg`, step 3);
- the cell profile and its version;
- the grasp;
- the families and their ranges;
- the error model and grid.

**The plan:**

- **Searches:** for each, its method (single evaluation, sweep or Bayesian), its budget and its batch size.
- **Totals:** designs, grasps and rounds.
- **Estimate:** `estimate.seconds`, or "unknown until runs on this sim have measured it" while it's null.
- **The sim path:** the estimate depends heavily on how the sim server runs, so show it next to the time. A typical
  job is about 12,100 grasps:

  | Path | Rate | A typical job |
  | --- | --- | --- |
  | Reference | 2.75 grasps/s | About 75 min |
  | CPU copies | About 5 grasps/s | About 40 min |
  | GPU copies | 16–28 grasps/s | 8–12 min, but exploratory (rule 2) |

**Warnings and blockers:**

- Show the plan's `warnings`.
- Show its `blockers`, each linking to its step. Run stays disabled while any remain.

**What it runs on:**

- the sim badge (Mock or Isaac);
- the connected GPU from the chip;
- for Mock, the line "Results from the mock sim check geometry only; they are not predictions";
- under "Advanced": the seed.

**Run**

- Run is disabled while there are blockers, or while no GPU is ready (4.6).
- On 201, go straight to `#/jobs/<id>`, where the progress shows.
- A 422 here carries `failed_step`: go back to that step with the message shown.

## 6. Experiments list and progress

### 6.1 Experiments page (home)

**One card per experiment** (`GET /api/jobs`), newest first. A card shows:

- the name and ID;
- the part name, and a thumbnail when one exists;
- the task;
- the sim badge, plus the sim path once results exist;
- a status badge;
- while running: "round 3 of 9", "designs 40 of 133", and the best predicted success so far;
- once done: the winner against stock at the target sigma, for example "D1 92% vs stock 61%, capture radius 5.0 vs
  2.0 mm";
- once failed: the one-line failure, and "Fix in step N" when `failed_step` is set;
- a physical-results badge: none yet, in progress, or validated.

**Filters and actions:**

- Filter by part, status and sim backend; sort by date.
- Each card has Open, Duplicate, and Cancel or Resume.

**Status badges** (the same everywhere: cards, the experiment page, lists):

| Status | Badge | Notes |
| --- | --- | --- |
| queued | Queued (neutral) | The worker is starting. |
| running | Running (active) | |
| finalizing | Final test (active) | The top designs and the baselines, re-tested on the dense grid. |
| done | Done (ok) | |
| failed | Failed (bad) | Show `failure`; offer Resume, and the step link if any. |
| cancelled | Cancelled (neutral) | Resume continues from its last round. |
| interrupted | Interrupted (warn) | The worker stopped, for example the laptop slept or restarted. Resume continues. |

**Live updates:** `GET /api/jobs/<id>/events` is a Server-Sent Events stream. It sends the card on every change and ends
when the job finishes. Open one stream per active card in view, and close it when the card leaves the screen or the job
finishes. With many running jobs, poll the list every few seconds instead.

### 6.2 An experiment that's running

`#/jobs/<id>` shows progress until the job is done, then becomes the results page (7) at the same address. While it
runs:

- **Header:** the name and ID (renamable in place: `PATCH /api/jobs/<id>`), the sim badge, the status, and the cell
  profile.
- **Progress:**
  - the round, the designs evaluated out of the total, and the best predicted success so far;
  - the time elapsed, and roughly how long is left (from the plan's estimate and the rate so far);
  - the GPU it runs on (the chip's target).
- **Search progress:** a chart of best-so-far against designs evaluated, one line per search, with round 0's baselines
  marked. `GET /api/jobs/<id>/results` answers during the run (the final-test sections are null until then), and its
  `run` section has each search's progress. Refresh it whenever the SSE card changes round.
- **Actions:**
  - **Cancel:** confirm first. It takes effect between rounds, so the current round finishes; say so.
  - **Duplicate.**

**Provisional results while it runs.** A job runs for 10 to 75 minutes, so show what it has found so far, not just a
bar. Every finished round is already scored and stored, so the data exists.

- **Available today:**
  - the best predicted success so far (card `best_value`);
  - each search's best-so-far curve (`run.searches[].best_so_far`).
- **Needs a small backend addition** (section 13), computed from the search-grid trials stored so far:
  - the top designs so far, with their parameters, search-grid success and capture radius;
  - the current best design's held map on the search grid, beside stock's;
  - its success-vs-error curve against stock;
  - its 3D preview (7.3).
- **Label it as provisional, everywhere:** "So far, from the 81-point search grid. The final test re-checks the top
  designs on 321 points and can change their order."
- **Same views as the final results:** use the same components, so the page fills in rather than changing layout when
  the job finishes. When the final test is done, the provisional sections give way to the final ones.

### 6.3 Failed, cancelled and interrupted experiments

- **The reason:** show `failure` in full. When `failed_step` is set, add a button that opens the wizard on that step,
  with the spec prefilled through duplicate.
- **Resume** continues after the last finished round, so nothing done is lost. It needs a ready GPU (4.6).
- **Interrupted** means the job's process is gone: the laptop slept, shut down, or restarted. The API marks such jobs
  at its next start. Say that plainly, and offer Resume.

### 6.4 Waiting on the connection

Covered in 4.7: show the GPU's reconnecting message on running jobs.

## 7. Results page

One scrolling page per experiment, ordered so the answer comes first and the evidence follows. Everything comes from
`GET /api/jobs/<id>/results` ([backend-api.md, "Results page"](backend-api.md#results-page)).

### 7.1 Sections, top to bottom

| Section | Shows | From | Notes |
| --- | --- | --- | --- |
| Header | name and ID, status, sim badge and path, cell profile and version, task, finish time; actions: download CAD, validate, duplicate | `header`, `run.sim` | The path label follows rule 2. |
| Banners | Mock: "Geometry only; not a prediction". Isaac: the caveats (section 10). | `sim_backend`, `run.sim` | Above the fold. |
| Summary | D1 against stock and imprint at the target sigma: predicted success, capture radius, the task metric, designs evaluated, and the gains | `summary` | The one-glance answer. |
| Re-score bar | sigma (or range), bias and direction, task and tolerances | `POST .../rescore` | 7.2 |
| Success vs error | success over σ from 0.5 to 5 mm for every final design, stock and imprint; target σ marked; measured points with 95% intervals once logged | `curves`, `physical.curve_points` | The core claim, and where prediction meets reality. |
| Held maps | every offset of the final grid, held or missed, D1 and stock side by side; yaw layers as tabs | `held_maps` | Makes error tolerance visible. Missed in the bad tone, held in the ok tone, size or opacity by weight. |
| In-hand pose | offset and tilt against the tolerance (place and insert only) | `in_hand` | Hide for drop. |
| Where it fails | misses by direction and by distance; standing caveats | `failures` | The judges asked for failure cases. |
| Best finger | 3D view of the mirrored pair on the part; parameter values; grasp pose as copyable text and JSON; downloads | `best_finger`, `GET .../finger` | 7.3 |
| Watch it in Isaac Sim | recorded Isaac Sim clips of the best finger and stock at a few grasps: one held, one at the edge, one missed | `GET`/`POST .../clips`, `.../clips/<id>.mp4` | 7.5 |
| Final test table | each final design and baseline: success, capture radius, task metric, a "print this" box | `final_table` | Ticking saves the print selection (8.1). |
| Physical validation | the tracker's summary for this experiment; a link to validation | `physical` | Empty state: "No physical trials yet: choose designs to print". |
| Review | approved, rejected or pending, by whom, with notes; approve or reject | `GET /api/jobs/<id>` `review`, `POST .../review` | 7.4 |
| Run details (collapsed) | per-search progress, stop reasons, budget, batch size, rounds; error model; sim path, GPU, versions, seed; warnings | `run` | Reproducibility. Include the warnings where the sim server ran other settings than the profile asked for. |

Sections that need the final test are null before it runs. Hide them, with one line: "Available after the final test".

### 7.2 Re-score bar

`POST /api/jobs/<id>/rescore {error?, task?}` returns the whole results view under other inputs, from the stored raw
outcomes. Nothing is simulated or stored.

- **What it changes:** the error model (sigma, sigma range, bias) and the task (kind and tolerances).
- **Show that it's a what-if:** a "Re-scored at σ 2 mm, place 1.5 mm" banner with a Reset button, so it's never
  mistaken for the run's own result.
- **Charts update in place.** Debounce slider moves.

### 7.3 Best finger and downloads

**3D view:** both fingers (left and its mirrored right) on the part, jaws closed (`GET /api/jobs/<id>/finger?design=D1`),
with orbit controls. The same viewer component serves step 6's previews.

**Grasp pose:** as copyable text for the robot program, and as JSON (`.../grasp-pose?format=text|json`).

**Downloads, per final design** (D1, D2, ..., IMP; not STOCK):

- STEP of the pair;
- STL of the left finger and of the right;
- the print sheet (PDF).

**Blocked downloads:** a failed export check answers 409. Show `.../checks` beside the download button: which check
failed, and why. Don't hide the button.

**Data exports** (in Run details):

- `run-metadata.json`;
- `trials.jsonl` (every simulated design with its raw grid outcomes).

### 7.4 Review gate

Plant rule: no printed finger goes on the real arm until a named reviewer approves it.

- **Show the status** (`review` on `GET /api/jobs/<id>`) on the results page, and again on the validation page.
- **Approve or reject:** a form with the reviewer's name (required to approve), the decision and notes
  (`POST /api/jobs/<id>/review`, form fields).
- **Make it visible:** until approved, the validation page shows "Not approved for the robot yet" above the logging
  tools.

### 7.5 Watch it in Isaac Sim

Real footage of the grasp: Isaac Sim's own rendering of the arm, the fingers and the part, with real contact. Seeing the
winning fingers close on the part makes the result real for people who don't read held maps.

**No browser animation.** A three.js replay was considered and dropped (2026-10-20): it wouldn't look right, and it
couldn't show what actually happens during the grasp.

**How it works:**

1. **Pick the grasps.** On the results page, choose the best design and stock, at a few grid points: the centre, the
   edge of what it catches, and one it misses. Or click any dot on the held map. Then press **Record**.
2. **The backend records them.** It starts a worker (like a test-plan prediction), which asks the sim server to run
   each grasp with a camera on. The request goes through the same GPU connection as jobs.
3. **The GPU machine films and encodes.**
   - The sim server runs the grasp on the reference path, and captures it at 30 fps from two views: a close-up of the
     fingers on the part, and the cell's side camera with the arm.
   - It encodes an mp4 on the GPU machine and sends it back: about 6 s, a few MB.
4. **Clips are kept.** The backend stores each clip with the experiment, so a grasp is filmed once.
5. **The page plays them** side by side, best design against stock, with play, pause, loop and slow motion. Each is
   labelled with its grasp (the offset) and its outcome.

**What the UI must handle:**

- **Recording takes time, and a GPU.** Show each clip as queued, recording, ready or failed, and gate Record on a
  ready GPU (4.6). A clip is ready about 12 s after it's asked for, longer behind a running job.
- **A clip's outcome can differ from the results.** Near the capture edge, about 9% of grid points flip between runs
  (CONTEXT.md risk 5). Label each clip with its own outcome, and say when it differs from the stored result.
- **Mock results have no clips.** Say "Needs the Isaac sim", and show the experiment's task example from step 3
  (`/task-examples/<task>.mp4`) instead, captioned as an example, not this experiment. Do the same before an Isaac
  experiment has any clips.
- **Clips wait behind jobs.** The sim server runs one thing at a time, so a clip queues behind a running job's batches.
  Suggest recording after the job finishes.

**Status: built, and working on the GB10** (2026-10-20,
[log](../experiments/2026-10-20-gb10-app-end-to-end-and-clips.md)).

- **What works:** the app's three clip calls, the worker and the sim server's recording call. Their types are in
  `schema.d.ts`.
- **Speed:** a clip is ready about 12 s after it's asked for.
- **Without a GPU:** the demo data ran on the mock sim, so it has no clips. To build the UI, stand in for the calls
  with the payloads in backend-api.md and any short mp4.

**The calls.** Full request and response payloads, errors and timing are in
[backend-api.md, "Isaac Sim clips"](backend-api.md#isaac-sim-clips).

| Call | Does |
| --- | --- |
| `POST /api/jobs/<id>/clips {design, offset: {dx, dy, yaw_deg}}` | Asks for one clip of a final design (`D1`, ..., `STOCK`, `IMP`) at one offset, ideally a held-map point. 202 with the clip, queued. The same design and offset again returns the existing clip, unless it failed. 409 before the final test, for a mock experiment, or with `not_ready_reason` when no GPU is ready. |
| `GET /api/jobs/<id>/clips` | The experiment's clips, newest first. Poll it while any is queued or recording. |
| `GET /api/jobs/<id>/clips/<clip id>.mp4?view=closeup` (or `side`) | One view's video, H.264, playable in a `<video>` element from that URL. 409 until ready. |

**A clip's fields:**

- `id`, `job_id`, `design`, and `offset` `{dx, dy, yaw_deg}`;
- `status`: `queued`, `recording`, `ready` or `failed`;
- `views`: `closeup` and `side`;
- `outcome`: `held` or `missed`, from this recording;
- `result`: the experiment's stored outcome at that offset, or null off the final grid;
- `matches_result`: whether `outcome` and `result` agree. False is expected now and then near the capture edge;
- `duration_s`, about 5 s;
- `error`: a one-line reason, when it failed;
- `created` and `recorded`: Unix times.

## 8. Physical validation: simulated vs real trials

Sim success is a prediction. The real FANUC arm checks it against the stock fingers and the imprint. The tracker
compares the two on exactly the same offsets, so any gap is sim-to-real error, not a different test
([backend-api.md, "Results tracker"](backend-api.md#results-tracker)).

### 8.1 The flow, one page

`#/jobs/<id>/validation` takes the user through five stages in order, each a section that shows its state:

1. **Choose designs to print.**
   - The final-test table's print boxes, from either page (`GET` / `PUT .../print-selection`).
   - Stock and imprint are always tested as baselines; say so.
2. **Record printed fingers.**
   - For each printed finger: its design, the side (L, R or pair), the material, the print date and notes
     (`POST .../printed-fingers`).
   - The response's `finger_id` (for example `EXP-0042-D1-L`) is engraved on the finger. Show it large, with a copy
     button.
3. **Create a test plan.**
   - Settings: repeats for the point-wise offsets (default 3), random offsets per design (default 30), and the seed
     (`POST .../test-plans`).
   - Each design gets 25 point-wise offsets, repeated, plus seeded random offsets drawn from the job's error model.
   - Show the trial count and a rough time at the robot (about 20 s per grasp).
4. **Wait for the sim's prediction.**
   - The prediction runs in a worker and needs a ready GPU. Poll the plan until `prediction_status` is done.
   - Failed: show `prediction_error`, and offer **Predict again** once the GPU is ready (4.6).
5. **Log the trials and compare.** Sections 8.2 to 8.4.

### 8.2 Logging: the spreadsheet round trip (build first)

It works offline at the cell, and everyone knows spreadsheets.

**Out:**

- **Download the plan** as `.xlsx` or `.csv`. The xlsx has outcome dropdowns, and its prediction column is hidden, so
  the operator tests blind. Say so next to the download.
- **Instructions on the page,** for the operator: offsets are commanded on the robot, not by moving the part; fill
  `outcome` with held, missed or skipped; fill `in_tolerance` for place and insert; notes and a video link are
  optional.

**In:**

- **Upload it back** (`POST .../upload`).
- **Show the report:** accepted, extras, unchanged and still pending counts, and an error table with each row number,
  trial ID and reason.
- **Valid rows are applied even when others fail.** Say so, so nobody re-uploads in a panic.
- **Re-uploading is safe:** it keeps history.

### 8.3 Results: predicted vs measured

**Per design** (`GET /api/jobs/<id>/validation`):

- predicted success against measured success;
- the measured 95% Wilson interval, drawn as an error bar;
- the agreement sentence, for example "sim matched reality on 22 of 25 offsets".

**Mismatch map:** the held-map layout, with each tested offset marked one of:

- agreed;
- sim-only success (the sim is too optimistic there);
- real-only success (the sim is too cautious there);
- mixed (repeats disagreed);
- pending.

The legend states what each means.

**Curve overlay:** the measured points also appear on the results page's success-vs-error chart.

**The physical badge on cards:** none yet, in progress, or validated.

**Exports:** `physical.jsonl` and `.csv` for this job.

### 8.4 Quick logger (later)

`#/jobs/<id>/log`: a page for a phone or tablet at the robot.

- **One trial at a time:** the trial number, the design and finger ID, and the offset to command, in large text.
- **The controls:**
  - big **Held** and **Missed** buttons;
  - a Skipped link;
  - an in-tolerance toggle for place and insert;
  - an optional note.
- **It moves on by itself** after each entry, and has an Undo for the last one.
- **One call per trial:** `POST /api/jobs/<id>/physical`. Extras outside the plan take the design and offset instead
  of a trial ID.
- **It hides the prediction,** like the spreadsheet does.

### 8.5 Across experiments (later)

One scatter plot of predicted against measured success for every validated design, across all experiments. Points near
the diagonal mean the sim can be trusted. It grows more convincing with each experiment, and it backs the business case.

There's no endpoint for it yet. Build it from each validated job's `/validation` (section 13).

## 9. Settings

### 9.1 Cell profiles

A cell profile describes one robot, gripper and cell ("workcell"). Switching profiles in the demo shows the tool isn't
tied to one cell.

**The list:**

- each profile's latest version (`GET /api/cell-profiles`), with its name and version number;
- the robot and gripper;
- the count of placeholder fields;
- any twin mismatch.

**The editor** (`GET`, then `PUT` to save):

- **Groups:**
  - Robot: model, TCP offset, approach, lift.
  - Gripper: model, stroke per jaw, grip force, air pressure, stock fingers and their size, stock tip gap, max finger
    length, free space beside the gripper.
  - Finger mount: holes, locating features, hole clearance.
  - Friction: pad material and its friction, table mat friction.
  - Cameras.
  - Advanced sim settings: physics time step, solver iterations, contact and rest offsets, environments. Collapsed by
    default.
- **Placeholders:** mark every field in `to_confirm` as a placeholder. Let the user clear the mark once a value is
  measured, which removes it from `to_confirm`.
- **Twin mismatches:** show `twin_mismatches` at the top, since results simulate the twin's gripper whatever the
  profile says.
- **Saving makes a new version.** Old versions never change, and every job records the version it used. Say so beside
  the Save button.
- **Errors:** a 422's `detail` names the problem (for example a mount that doesn't fit the blade). Show it at the right
  group.

**The version history:** `GET .../versions`, read-only, with what changed between each pair.

**The environments setting:** the profile's sim environments set the job's batch size (64 environments gives about 8
designs per round). The sim server is started with its own flags, though, and a job warns when they differ. Explain
that next to the field.

### 9.2 GPU targets

Read-only.

- **What's shown:** which backends are enabled (`GET /api/compute` `backends`), each one's label, and whether it's
  always on.
- **Changing them** is done in the backend's `.env` (`COMPUTE_BACKENDS` and the `COMPUTE_*` settings) and needs an API
  restart. Show that, and link to SETUP.

The UI can't change compute settings, by design: they hold machine paths and must match each user's own setup.

### 9.3 About

From `/api/meta`:

- the sim backend and its URL;
- whether demo data is on;
- the number of CPUs.

Add the app's version, once there is one.

## 10. Caveats the UI shows

The real twin's scores have known biases. Show these next to the results they affect, worded plainly. Keep the wording
in one place in the code, so every screen says the same thing.

| Caveat | Where | Text | Source |
| --- | --- | --- | --- |
| Mock results | every mock result, card, chart and export | "Mock sim: geometry only. Not a prediction." | Always |
| GPU-copies path | results where `run.sim` has envs > 1 on a CUDA device | "Exploratory: the GPU path with copies holds about 9 of 81 more grasps than the reference sim. Re-run on the reference or CPU-copies path for results you report." | CONTEXT risk 7 |
| Landing capture | every Isaac result | "A finger that lands on the part can push it into the gap, and the sim counts that as held. Real-twin scores are optimistic, and tight and loose pads can score alike." | CONTEXT risk 5 |
| Weak grip | step 1 when mass > ~100 g or friction is low; results for such parts | "The twin grips with only about 2.5 N per jaw. Parts over about 100 g, or slippery ones, score as dropped for every design." | CONTEXT risk 6 |
| Capture-edge noise | held maps; small differences between designs | "Grasps beyond about 5 mm along the jaws aren't repeatable, so small differences there mean little." | CONTEXT risk 5 |
| Placeholder error level | step 7; results header when the preset is a placeholder | "This camera error is a placeholder until it's measured on the cell." | `/api/meta` presets |
| Placeholder cell values | step 4; the profile editor | "Placeholder: not yet measured at the cell." | `to_confirm` |
| Twin mismatch | step 4; results header | "The sim models the twin's SMC MHZL2-16D2 gripper; this profile differs in: ..." | `twin_mismatches` |
| Estimated friction | results "Where it fails" | "Friction values are estimates until measured." | The failures caveats |

These come from open problems. When one is fixed, drop its caveat; CONTEXT.md's risks list is the record.

## 11. Shared components to build

Expect to build these, each once, in `src/components/`, and use them on every page that needs them
([coding-style.md](../../.claude/rules/coding-style.md#frontend): give a close component a prop rather than copying it).
None of them has to start from the current placeholder components (section 1).

**Page structure**

- **Step layout and step list** (5.0): every wizard step uses it.
- **Tabs, drawer, modal.**

**Feedback**

- **Banner and callout,** in info, warn and error tones. Demo data, mock, the caveats and the re-scored view all use
  it.
- **Help card** (4.5): a message, what it means, the fix, a link and an action.
- **Empty, error and loading states,** one set for every list and section.
- **Confirm dialog:** names what will happen (rule 9).

**Forms**

- **Text, number-with-unit, select, checkbox, toggle, radio cards** (the task kinds, the presets) and a
  **file drop zone** (CAD upload, spreadsheet upload).
- **Range slider with a lock,** and a **single-value slider.**

**Data**

- **Table:** sortable, with an optional checkbox column (the final-test table, the session log, upload errors).
- **Progress bar,** and the **status, sim, path and physical badges:** one badge component with tones, not four.
- **Copy button** and **download button.** The download button turns a 409 into the checks message.

**Charts:** a line chart with intervals (curves, search progress), a dot-grid map (held, mismatch, test grid), a
histogram (in-hand), and a scatter (sim vs real).

- Pick one charting approach and use it for all of them.
- Every chart has axis units, a legend in words, and a text alternative.

**3D viewer** (three.js): parts from STL (`/api/parts/<id>/mesh`), fingers from convex pieces, grasp arrows, raycast
picking for the manual grasp, and ghosts for the previews. One viewer, configured per use.

**Video player** for the Isaac Sim clips (7.5): two clips side by side, played together, with pause, loop and slow
motion, and each clip's label and outcome under it. The task step's example videos (step 3) use it too, one at a time,
muted and looping.

**Icon:** inline SVG, for the rare control that needs one.

## 12. Priorities and build order

Final submission is **Sun 2026-11-01** (a 5-minute video and a one-page summary); finals are 2026-11-05. Build what the
video shows first, and against demo data, so nothing waits on the GPU or the robot.

| Item | Priority |
| --- | --- |
| Shell: header, navigation, GPU chip, sim badge, demo banner | Must |
| Experiments list with live cards and status badges | Must |
| Results: summary, success-vs-error curves, held maps, best finger with downloads, caveat banners, sim path | Must |
| Wizard steps 1 (STEP upload, size, material, mass), 3 (task), 4 (confirm the cell), 7 (error presets and grid), 8 (review and run) | Must |
| Wizard step 5 with the auto proposal, and step 6 with sliders and per-parameter ghosts | Must |
| Step 3's example video of each task (the files are ready in `public/task-examples/`) | Should |
| GPU page: targets, starting steps, help cards, readiness gating on Run and Resume | Must |
| Validation: print selection, printed fingers, test plan download and upload, predicted vs measured per design | Must |
| Mock badge everywhere | Must |
| Step 2 resting-pose thumbnails | Should |
| Re-score bar | Should |
| Mismatch map, curve overlay | Should |
| Settings: cell profile editor with versions and placeholders | Should |
| Running-experiment page with the search-progress chart | Should |
| Provisional results while a job runs (needs the backend addition in section 13) | Should |
| Isaac Sim clips of the best finger and stock (7.5; the calls exist, first GPU recording still to verify) | Should |
| Several grasp axes in step 5 (needs the backend change in section 13) | Should |
| Review gate on the results page | Should |
| Manual grasp by clicking faces | Should |
| Parts library | Should |
| Quick logger | Later |
| Across-experiments plot | Later |
| Design-space cloud | Later |
| 3D robot and cell render in step 4 | Later |

**A sensible order:**

1. **The shell and the list:** header, chip, Experiments page with SSE cards, against demo data.
2. **The results page:** the screen judges look at longest.
3. **The wizard:** steps 1, 3, 4, 7 and 8 first, with steps 2, 5 and 6 taking their defaults (the most likely pose,
   the first grasp candidate, V-pad with default ranges). Then build 2, 5 and 6 out.
4. **The GPU page and its help cards,** then gating Run on a ready GPU.
5. **Validation:** the spreadsheet round trip and the per-design comparison.
6. **The Shoulds,** in the table's order.

## 13. Backend gaps you'll meet

None blocks the Must list. Raise them with whoever owns the backend.

| Gap | Effect on the UI | Suggested backend change |
| --- | --- | --- |
| No provisional results during a run | The running page shows only best-so-far numbers and curves (6.2) | A `provisional` section in the results view during the run, from the search-grid trials stored so far: the top designs with their parameters, the current best's held map and curve, and stock's |
| One grasp axis per experiment | Step 5 can't offer several axes (5, step 5) | A list of grasp choices in the spec; one search per (family, axis); the final test across axes; each design's axis carried through results, CAD, test plans and trials |
| No structured "reconnecting" state | Running jobs can't say they're waiting on the GPU, except by reading the session's message text (4.7) | A `connection` field on the session, or a `waiting_for_sim` flag on the job card |
| Compute errors are text only | The help cards (4.5) match on substrings, which breaks if the wording changes | A stable `code` with each compute error (`vpn`, `ssh_key`, `port_taken`, ...) |
| No Brev cost or credit balance | The GPU page can only link to Brev's Billing tab | Brev's CLI doesn't report it; probably stays a link |
| No across-experiments validation endpoint | 8.5 has to fetch every validated job's validation | `GET /api/validation` with one row per validated design |
| The estimate doesn't know the sim path | The review step's time can be off by 5 times or more until runs have measured the rate | Report the path's measured rate per path, or `SIM_GRASPS_PER_S` per path |
| No robot or cell model to render | Step 4 shows numbers, not a 3D cell | A mesh endpoint for the profile's gripper and stock fingers |

## 14. Where this differs from the 2026-10-19 specs

| The spec said | As built |
| --- | --- |
| Several finger families: V-pad, imprint with clearance, curved cradle | Only V-pad is built; the others are listed as planned and refused if chosen. |
| A "closed gap" parameter for parts wider than the stroke | Not a parameter, and it shouldn't become one: it's set by the slack, the part's width and the stroke, so a second control would set the same thing twice. Show it beside slack (step 6). |
| "Find the best grasp axis" across candidates | Still wanted, but not built: one axis per experiment for now (section 13). |
| Results only once the job is done | Wanted: provisional results while it runs (6.2), once the backend adds them. |
| 3D render of the robot and gripper on the cell step | No model endpoint yet (section 13). |
| A Settings page holding everything | Cell profiles are in Settings. GPU targets are set in the backend's `.env`, not the UI. |
| Results open from a finished card | One address per experiment: progress while running, results when done. The results view answers during the run, so search progress can show live. |
| GPU choice not covered | A whole part of the app: section 4. |
| Physical logging: spreadsheet first, quick logger later | Unchanged; both endpoints exist (spreadsheet upload, and one trial per call). |
