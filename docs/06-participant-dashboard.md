---
title: "Physical AI Hackathon for the Factory Floor (2026): participant dashboard"
source: https://hackathon.sidclab.org/ (sections #submission, #faq, #calendar, #leaderboard, #resources)
author: SIDC Lab, UW-Milwaukee (platform developer), for UW-Milwaukee CSI and MSOE
received: 2026-10-20
kind: event
---

# Physical AI Hackathon for the Factory Floor (2026): participant dashboard

> **Our notes (not part of the source):**
>
> - **Where this came from:** the team shared the dashboard's CAD Models link (`#resources/cad-models`) in a Claude Code
>   session on 2026-10-20 and pointed out that the rest of the page has more information. Claude downloaded the page
>   with `curl` that day. It is one static HTML file whose `#` sections are views of the same page. The text below is
>   transcribed from that file. The live parts (My results, the leaderboard, runs and calendar slots) load from the
>   site's API and are not included. The scoring rules and example tasks come from data embedded in the page. The CAD
>   Models and AI Plays Robotics pages are stored separately: [07](07-cad-models.md) and
>   [references/ai-plays-robotics.md](references/ai-plays-robotics.md).
> - **This is how we get onto the real arm.** A policy runs on our machine (`act(obs)`). The organizers' operator sets up
>   each rollout and scores it, and every rollout is recorded. A supervised physical test at CSI (CONTEXT.md) now means
>   booking a slot here. **`custom_hardware` in `submission.yaml` is where our 3D-printed fingers are declared.** Client
>   package: [references/physicalai-client-package.md](references/physicalai-client-package.md). Our submission and
>   policy: [../cell_policy/](../cell_policy/README.md).
> - **Default scene: 8 M6 screws and the yellow bin**, the same every rollout ([table plan](images/client-table-plan.png)).
>   Our candidate demo task is one of those screws into the bin.
> - It confirms the **SMC MHZL2-16D2** with custom aluminium fingers 76 × 12 × 6 mm (not SCHUNK; see
>   [03](03-dataset-3-grasping-sorting.md)) and a 12 mm straight-face opening.
> - **The table camera does not see screws.** Finding them needs the wrist camera close up, so position error is large,
>   which is the case our fingers are designed for.
> - The `"tcp"` action targets the **stock** fingertip (UTOOL1, 293 mm). The client's mock rejects z below −334 mm UF0
>   (the surface is at about −335), so a printed finger whose tips don't end where the stock tips do changes how low the
>   real tips go (see [notes/things-to-know.md](notes/things-to-know.md)).

**Track 3 · Act on it: teach the robot**

*Participant dashboard.* An online platform for standardized submission, remote execution, and reproducible evaluation
of robot policies on physical robots.

## My results

Only your team sees its results. Open the link that `uv run run.py --status` prints, or paste it here. This browser
remembers it. Rows marked *example* are our own runs, to show what results look like.

*(Live table: results, runs, compare policies. Not captured.)*

## How a rollout is scored

*(Filled in per task from the site's data. For the organizers' example tasks it reads:)*

| Stage | Name | Rule |
| --- | --- | --- |
| 0 | fail | the task was not done |
| 1 | success | the task was done |

Example tasks shown on the page (the organizers' own runs, 2026-10-19):

| Task | Instruction | Objects | Layout | Example runs |
| --- | --- | --- | --- | --- |
| `stack-10mm-SIDC` | Put the red 10 mm cube on the blue 10 mm cube. | same | different | ACT-D3-p30 (VA): 0/1; GraspAny-v2.2 (VLM + BM): 2/4 |
| `screws-stack-SIDC` | Rollouts 1-2 put the screws into the yellow bin; rollouts 3-4 put the blue 10 mm cube on the red 10 mm cube. | different | different | GraspAny-v2.2 (VLM + BM): 3/4 |

## How we evaluate your policy in the real world

**You choose the task**: any manipulation task on the cell, with its objects or your own.

You develop your policy your own way, for example in Isaac Sim with our starter and your own data. We then evaluate it on
our real robot: our server sends your machine an observation (`obs`), your policy returns the next action, `act(obs)`,
and this repeats until the rollout ends. The figure below shows the framework.

*(Figure: Simulation (Isaac Sim) and Training (your data): demos, train · eval, trained policy. Client (your machine) and
Server (our machine) exchange `obs` and `act(obs)`.)*

## What you prepare

### Get the client package

```bash
git clone https://github.com/SIDCLab/PhysicalAI-Hackathon-2026 && cd PhysicalAI-Hackathon-2026
uv sync
```

### Wrap your sim model

Wrap the model you trained in simulation in `policy.py`. Observation and action formats (below).

### Check formats and connection

Runs your policy against a stand-in for the cell on your machine, with no robot. It ends with ✓ Ready for the real robot,
or tells you what to fix. Its images are synthetic: it checks the formats and the connection, not whether your policy
succeeds.

```bash
uv run run.py --mock
```

### Describe your task and submit

Fill in `submission/submission.yaml`, and `submission/placement.yaml` unless your task uses our default scene (8 screws
and the yellow bin, the same every rollout), then send it:

```bash
uv run run.py --submit
```

Then pick a slot in the Calendar tab with the request id it prints; we approve your request for that slot. We keep adding
available slots.

### Run during your slot

Once we approve your request, your client picks up its token by itself and waits for the operator.

```bash
uv run run.py
```

Every rollout is recorded and appears with its score and videos under My results. Only your team sees them: open the
link that `uv run run.py --status` prints.

### Observation and action formats

*(A pop-up on the page, "Wrap your sim model".)*

Edit `policy.py` and implement `act(obs)`. Your policy receives the robot's observation and returns the next action.
After the action finishes, we call `act(obs)` again.

**What your policy receives**

| | |
| --- | --- |
| `obs["images"]` | RGB images from the cameras you select (table, side and/or wrist) |
| `obs["joints"]` | the robot's joint angles J1–J6 in degrees, and the gripper state (0 = open, 1 = closed) |
| `obs["tcp_pose"]` | the fingertip position and orientation `[x, y, z, w, p, r]`: position in mm, orientation in degrees |
| `obs["trial"]` | the current rollout, including the task instruction (your policy may ignore it) |
| `obs["depth"]` | only with `DEPTH`: depth images in mm from the table and/or wrist camera (see the FAQ) |

**Settings at the top of `policy.py`**

| | |
| --- | --- |
| `CAMERAS` | the cameras you want: any of `"table"`, `"side"`, `"wrist"` |
| `IMAGE_SIZE` | (width, height) of the images you get, 640 × 360 by default: the whole 16:9 camera frame, resized (not cropped), as in the sim and the recorded datasets |
| `IMAGE_FORMAT` | `"png"`, or `"jpeg"`: about 7× smaller, for a slow connection |
| `ACTION` | `"joints"` or `"tcp"`: what `act` returns (below) |
| `DEPTH` | `[]` by default; `"table"` and/or `"wrist"` for depth |
| `PREFETCH` | `True`: plan the next action chunk while this one still plays |

**What your policy returns.** Choose one action format with `ACTION` in `policy.py`:

- `ACTION = "joints"`: `[J1, J2, J3, J4, J5, J6, gripper]`. Move the robot with joint angles, in degrees (the v0.5 twin's
  convention). Recommended for learned robot policies.
- `ACTION = "tcp"`: `[x, y, z, w, p, r, gripper]`. Move the fingertip to a target position and orientation; the robot
  works out the joints. Recommended for planners and AI agents. E.g. fingers pointing straight down: `w, p, r = −180, 0, R`.

## Runs

Running and scoring rollouts stays in the lab: the Operate page, `http://127.0.0.1:9097` in the cell PC's browser (or
`operator_console.py run <run_id>`).

*(Public leaderboard and runs table: Run, Team / policy, Task, Trials, Success. Not captured.)*

## FAQ

### Getting started

**Does the client run on my computer?** Yes, on Linux and macOS, Apple Silicon included: it needs uv and git. Tell us if
anything fails on your machine.

**Where does my policy run?** On your own machine. The cell sends your policy an observation, your `act(obs)` returns the
next action, and the cell plays it on the robot. This repeats until the rollout ends.

### Observations and actions

**What does my policy receive?** `obs["images"]`: the cameras you list in `CAMERAS`, from table, side and wrist, at the
size you set in `IMAGE_SIZE` (default 640 × 360), as PNG or JPEG. Each image is the whole camera frame, resized (not
cropped), and each observation carries each camera's latest frame.

`obs["joints"]`: J1–J6 in degrees and the gripper (0 open, 1 closed). `obs["tcp_pose"]`: the fingertip
`[x, y, z, w, p, r]` in mm and degrees. `obs["trial"]`: the current rollout, with its instruction.

**Do I need the camera calibration?** Usually not. The cameras in the starter's Isaac Sim scene are already placed with
it, so a policy trained there sees the cell as the real cameras do.

The copy under `calibration/` in the client package is optional: it is for code that turns real image pixels or depth
into robot coordinates, such as a planner or a VLM pipeline. `cameras.json` holds each camera's intrinsics and pose,
`FRAMES.md` defines the frames, and `geometry.py` maps a table-image pixel to a point on the table (`pixel_to_base`).

**Can my policy get depth?** Yes, from the table and the wrist cameras. Set `DEPTH = ["table"]`, `["wrist"]` or both in
`policy.py`: `obs["depth"]` then holds a uint16 image per camera, in millimetres along that camera's optical axis
(0 = no depth), refreshed about 10 times a second: 640 × 400 for the table, 848 × 480 for the wrist (the wrist colour
image's view).

`calibration.geometry.depth_to_base(load()["table_depth"], depth)` turns it into points in the robot base frame. The
wrist camera moves with the arm: pass the same observation's joints too,
`depth_to_base(load()["wrist_depth"], depth, joints=obs["joints"])`.

The table camera does not see screws: to find screws or small cubes in depth, use the wrist camera close up (fingertips
within about 8 cm of the table). Depth is not recorded.

**In "tcp" mode, which frame and conventions?** The fingertip (the controller's UTOOL1) in user frame UF0, in mm. x and y
are the robot base's (x forward, y left); z_UF0 = z_base − 330 mm, so the work surface is at about −335 mm. w, p, r are
FANUC's rotations about x, y and z in degrees: −180, 0, R points the fingers straight down, and R turns them about z.

The gripper only opens and closes: 0 open, 1 closed (0.5 or more closes it). It switches once the arm has reached that
row's target.

**When is act called, and how does a rollout end?** After the arm has played the target(s) you returned, with a new
observation. `act` has no time limit: the arm holds still while it runs. `act` may return up to 100 actions at once (an
action chunk). Your policy cannot end a rollout: it ends when the operator scores or stops it, or on a controller fault.
When your policy is done, hold still by returning the current pose.

**My policy was trained on the starter's 10 Hz data. Does the timing match?** Yes. Each target you return plays as one
step of that data (0.1 s).

**What should I know about how the real arm moves?** Keep targets within about 0.55 m of the base axis: beyond the arm's
reach, the controller faults and the rollout ends. The real arm also follows its targets about 0.8 s behind, which the
twin does not do.

**My machine is far from the cell. Anything I should set?** Set `IMAGE_FORMAT = "jpeg"` in `policy.py`: the images become
much smaller. If `act` returns many actions at once, set `PREFETCH = True` so the next actions are planned while these
still play.

### The cell

**Which gripper and fingers?** An SMC MHZL2-16D2 parallel gripper with custom aluminium fingers, not SMC's stock ones:
76 mm long, 12 mm wide and 6 mm thick, with a hook-shaped notch at the tip. Each jaw travels 6 mm: the straight faces are
12 mm apart when open. The gripper's STEP model is under Resources → CAD Models.

**Which objects and bins are there?** M6 × 30 screws, 10 mm and 16 mm cubes, bins (50 × 50 × 55 mm) and a vial. Their
models are under Resources → CAD Models.

**Can I use my own fingers, objects or bins?** Describe them under `custom_hardware` in `submission.yaml` (e.g.
3D-printed fingers) and when you book. We review them with your request.

### Runs, scoring and data

**Who sets up each rollout?** The operator, from your `submission/placement.yaml`: where each object goes in each
rollout, and optionally the instruction your policy gets. If you send none and objects and layout are both same, every
rollout gets our default scene (8 screws and the yellow bin, as in the twin); for any other objects or layout, list them.
The operator sees those positions on the table camera and places the objects there. Anything that changes between
rollouts, your policy has to find in the images.

**How long is a slot?** Half an hour.

**Can I watch my runs?** Come to the lab if you can, to watch your rollouts live. Every rollout is recorded either way:
its videos and data appear under My results, and you can download them (see below).

**How is a rollout scored?** The operator scores each rollout as a whole, success or failure (not per object).
Interventions and controller faults are noted, and a successful rollout records its time from start to success.

**Who can see my results?** Only your team. `uv run run.py --status` prints your results link; open it and My results
shows your scores and videos.

**Can I get the data recorded during my rollouts?** Yes. Every rollout is recorded as a LeRobotDataset episode: three
cameras and the robot state, 10 times a second. Under My results, *dataset viewer* shows it frame by frame, and
*download dataset* (or `uv run run.py --download`) gives you the whole dataset.

## Book a slot on the robot

Each slot is 30 minutes on the real robot, in Milwaukee time (Central). Enter the request id that `uv run run.py --submit`
printed and pick a slot; we approve your request for it. Two teams can share a slot.

*(Calendar: "Open Mon–Fri, 9:00–17:00 this week" when captured. Slots are live data, not captured. The page also shows
organizer controls: click a time to open or close it, approve, reject or cancel bookings.)*

## Resources

- **AI Plays Robotics**: From instructions to physical actions: why a real robot is the test that matters.
  ([stored copy](references/ai-plays-robotics.md))
- **CAD Models**: Models of the cell: the gripper, the objects, the bin and the work surface texture.
  ([stored copy](07-cad-models.md))

## Links on the page

- Track 3 page: <https://uwm.edu/csi/nvidia-rockwell-hackathon-fall-2026/>
- Client package: <https://github.com/SIDCLab/PhysicalAI-Hackathon-2026>
- uv: <https://docs.astral.sh/uv/>

Organizers: UW-Milwaukee Connected Systems Institute, Milwaukee School of Engineering. Partners: NVIDIA, Rockwell
Automation. Platform developer: SIDC Lab, UW-Milwaukee.
