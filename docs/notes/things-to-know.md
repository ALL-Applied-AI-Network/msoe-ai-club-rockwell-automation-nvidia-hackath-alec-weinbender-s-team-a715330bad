---
title: Things to know (gotchas, mismatches, warnings)
source: our own notes, collected while setting up the repo and reading the docs
author: Alec Weinbender's Team
received: 2026-10-15
kind: note
---

# Things to know

Short list of things that will bite us if nobody knows them. **Add to it** whenever you hit one. The broader project state is in
[../../CONTEXT.md](../../CONTEXT.md).

*Last updated: 2026-10-20*

## Hardware and the demo part

1. **Gripper mismatch: SMC, not SCHUNK.** Our team plan and the Dataset 3 page say "SCHUNK pneumatic two-finger gripper".
   The twin and the organizers' dashboard FAQ ([06](../06-participant-dashboard.md)) say **SMC MHZL2-16D2** with custom
   aluminium fingers, and SMC's STEP is published ([07](../07-cad-models.md), `cad/`).
2. **The jaw in SMC's STEP isn't what the twin's photo reconstruction assumed.** Each jaw ends in a flat tongue 5 mm thick
   along the travel, 8 mm wide and 15 mm long. It has two Ø3.4 mm holes **along the jaw travel**, 4 and 11 mm below its
   shoulder ([cad/README.md](../../cad/README.md)). The photo mount had holes across the travel at 10 and 23 mm, and the
   23 mm hole is past the end of the tongue. The app now builds the STEP's mount by default (`SMC_FLAT_JAW_MOUNT`).
   **Check it on the real jaw before printing.**
3. **The jaws barely open.** Travel is 6 mm per jaw, so the straight-face gap is **0–12 mm**; at the hooked tips it is about
   4 mm closed and 16 mm open. Tennis balls (~67 mm) and eggs from our plan **cannot be grasped** with this actuator. The
   organizers' feedback ("not all of the existing items will fit in the fingers") is pointing at this. Of the cell's
   objects, the stock fingers can't take the 16 mm cube, the cap's plug (Ø20.8–23.6) or the vial (Ø27.18).
4. **Objects on the real cell** ([07](../07-cad-models.md)): M6 × 30 countersunk screws, 10 and 16 mm cubes, 50 × 50 × 55 mm
   bins, a vial and its cap. **The platform's default scene is 8 screws and the yellow bin.** The table camera can't see
   the screws; finding them takes the wrist camera close up.
5. **Stock fingers:** aluminium blades of about 76 × 12 × 6 mm, with a hooked tip and an AA-sized circular recess. TCP is
   293 mm from the J6 origin (70 mm to the faceplate plus 223 mm UTOOL1). Which way the 12 mm runs, and so where the
   straight faces sit, was inferred by the twin, not measured (CONTEXT.md, risk 8).
6. **The organizers want a specific manufacturing part + task**, a comparison against the **stock fingers**, and the sim
   success rate treated as a prediction to **validate physically**.
7. **The real arm is reached through the organizers' platform** ([06](../06-participant-dashboard.md)): our `policy.py`
   runs on our machine, their operator runs and scores 10 rollouts per run in a booked 30-minute slot, and every rollout
   is recorded. Our version is in [cell_policy/](../../cell_policy/README.md). Its "tcp" targets are the **stock**
   fingertip, and the cell refuses TCP z below −334 mm (the surface is at about −335). Fingers that end lower than the
   stock ones could touch the table inside that limit.

## The app

1. **The backend was restructured (2026-10-19).** It's a uv workspace member at `app/backend/` whose package is
   `app/backend/src/api/`, split into routers, services, clients, models and a `db/` package (SQLAlchemy + Alembic); see
   [the coding-style rule](../../.claude/rules/coding-style.md#application-backend). `adapters.py` was split into
   `clients/` (LLM, sim, CAD) and `models/design.py`; `worker.py`'s optimizer is now `services/optimizer.py`.
   `sim_server/` is now `sim/sim_server/src/sim_server/`, and `app/requirements.txt` is gone. Run the app from the repo root
   with `uv run --package backend uvicorn api.main:app --port 8000`. Old local branches touching the backend need manual
   merging: the code moved and was reformatted.
2. **The default simulator is a mock.** It checks capture geometry only (does a fingertip land on the part, does the part
   end on the pads), with no friction, force or slip, so **never report mock success rates as results.** Its optimum is
   always "most slack, most lead-in, flat pad". The optimizer no longer calls the LLM at all.
3. **Designs are geometry now (2026-10-19).** `models/finger.py` turns a design into convex pieces in the gripper frame (mm,
   jaws closed, fingertips at z = 0); the sim server, the CAD file and the 3D preview all get the same pieces. The stock
   blade's bounding box (x 0..12, y -3..3, z 0..76) is checked against `cell.py` by the sim server's tests. PhysX keeps
   at most 64 vertices per convex hull, so no piece may have more points (the app's tests check this).
4. **Printable CAD comes from CadQuery** (STEP of the pair, STL per side, print sheet) with the cell profile's mount.
   Since 2026-10-20 that's SMC's jaw from its STEP: the root is cut back for the jaw's tongue, with M3 holes along the
   jaw travel. A database whose default profile was the old photo mount, unedited, gets the new default as its next
   version at startup. Jobs keep the version they used. **Measure the real jaw before printing.**
   A failed export check (solid, matches the sim, min wall, finger length) blocks the download with a 409 that says why.
5. **The 3D preview loads three.js from a CDN** (jsDelivr), so it needs internet access.
6. **The app reads the repo-root `.env`**; exported shell variables override it (see `.env.example`). `SIM_URL` is the sim
   server's base URL (the app posts to `/evaluate_batch`).
7. **Migrations 0002 and 0003 deleted every job made before them.** If an old `app.db` looks empty after upgrading,
   that's why.
8. **Runtime data lives in `app/data/`** (SQLite DB, uploads, outputs). It is gitignored and per-machine.
9. **`DEMO_DATA=true` switches the app to demo data** in `app/data/demo` (its own database). Its results are mock and its
   physical trials are made up: never quote them. Unset it for real work.
10. **Mock and Isaac badges are part of the data.** A job keeps the badge of the sim it was created on, and a worker with
    the other sim refuses to resume it.
11. **A finger that lands on the part scores as a miss (since 2026-10-26).**
    - It counts when the part moved more than 1 mm or 3° before the jaws closed. Results and rankings say how many
      holds it turned into misses.
    - Jobs from before have no landing data, keep their old scores, and say it wasn't checked. Don't compare an old
      job's numbers with a new one's.
    - On the M6 screw it drops stock from about 88% to 63%.
12. **The team's results live in the hosted app on the GB10 (since 2026-10-29).**
    - It has the six Isaac experiments and the printable D1 fingers ([app/README.md](../../app/README.md#hosted-on-the-gb10)).
    - Each laptop's `app/data/` is its own database and doesn't sync. Run the jobs we report in the hosted app, or log
      them in `docs/experiments/`.
    - The database stores absolute file paths. A database copied between machines needs its paths rewritten, or its
      downloads break.
13. **After pulling a frontend change, run `npm ci` in `app/frontend/`.** `gb10.sh deploy` only installs packages when
    `node_modules` is missing, so a newly added package fails the build (it happened with the 2026-10-29 redesign's font).

## The digital twin (`sim/fanuc_er4ia_sim/`)

1. **It needs Linux and an NVIDIA GPU.** It was validated on Linux with Isaac Sim 6.0 on an RTX A6000. It won't run on our
   Windows laptops; use Brev (Isaac Sim launchable, RTX PRO 6000 or 4500) or the MSOE GB10. The GB10 is ARM64 and shared
   with other teams. Isaac Sim 6.0.1 is installed there from pip wheels (`ISAAC=~/isaac-sim-6.0.1`), and it needs the
   R580 driver. Other teams can reach its localhost ports (use port 9011). Start Isaac there detached, not in tmux. Its
   password never goes in the repo ([GPU test plan, 0.2](gpu-test-plan.md#02-msoe-gb10-free-shared-set-up)).
2. **It uses three Python interpreters:** host `.venv`, Isaac `python.sh` and the Cosmos env. Using the wrong one fails in
   confusing ways. Our `sim/sim_server` runs under Isaac's `python.sh` too, not under `uv run` (see
   [sim/README.md](../../sim/README.md#sim_server)).
3. **Isaac can exit with code 0 after crashing.** Check `execution_report.json` (`task_complete: true`), not the exit code.
4. **The robot USD and Cosmos weights are not bundled.** First run needs network access to Isaac's asset root (or set
   `FANUC_ROBOT_USD`).
5. **The demo task is cube stacking, not screws.** The Tools and Resources tutorial prompt says "pick up the screws", but
   v0.5 removed the screw task (`SCREWS = []`, `SHOW_BINS = False`), though the real cell's default scene is screws and a
   bin. The twin also scales the vial to Ø17 × 140 mm (real: Ø27.18 × 203). Its table renders white because its mat
   texture isn't in the starter; the real surface's photo is `cad/manipbench-table-surface.png`. Our sim server takes
   parts as meshes, so the screw comes in through the app's part upload (`cad/ISO10642-M6x30-countersunk-screw.step`).
6. **Ground truth is for evaluation only.** Simulator object poses must never feed grasp commands.
7. **Units:** the twin uses metres and degrees, the app uses millimetres. Convert in `sim/sim_server`.
8. **`sim/sim_server` has run GPU test plan stages 0–6, with three known problems** (2026-10-20:
   [Brev](../experiments/2026-10-20-brev-sim-server-bringup.md), [GB10](../experiments/2026-10-20-gb10-sim-server-bringup.md),
   [stages 4–6](../experiments/2026-10-20-gb10-stages-4-6.md)). Finger swaps, mixed designs in a GPU chunk, mesh parts,
   the in-hand readout and transport work. But:
   - a finger landing on the part can count as a grasp, which flatters every design (CONTEXT.md, risk 5);
   - the twin grips at only about 2.5 N per jaw, so heavy parts drop (risk 6);
   - the GPU path with copies holds about 9/81 more than the reference (risk 7). `--envs 64 --device cpu` matches the
     reference.

   Results near a design's capture edge aren't repeatable. Custom-finger friction is *averaged* with the part's by
   default (`--friction-combine`).

   Since 2026-10-26 the landing readout works: stage 4 passes with the landing rule, and an untouched part moves exactly
   0 ([log](../experiments/2026-10-26-gb10-landing-check-and-screw-reruns.md)).
9. **The M6 screw isn't repeatable in the twin** (2026-10-26). Two runs of the same finger agree on only 77–81% of grid
   points, on either path, because the fingers brush the lying screw differently each run. Scores move 1.4–2.3 points.
   Treat gaps smaller than about 3 points between fingers on the screw as noise, and repeat a finalist's test before
   quoting a win.
10. **The stock fingers have more friction in the twin than a printed finger.** The stock tips are 1.5 / 1.3 in the twin.
    A printed finger gets the part's estimated friction against PLA (0.4 / 0.3 for steel), averaged with the part's
    own. Neither number is measured (CONTEXT.md risk 12).
11. **It's vendored upstream code.** Prefer wrappers over edits, and log any edits in `CONTEXT.md` (`MANIFEST.json` has the
    original hashes).

## Rules and process

1. **Never command the physical arm or touch its controller, cameras, PLC or network** without the plant manager and
   mentor. A Claude Code hook blocks driver launches with `robot_ip:=`.
2. **No printed finger goes on the robot before it is reviewed** for clearance and safe operation.
3. **Book robot time early.** The main route is the organizers' platform: `uv run run.py --submit`, then a slot in the
   dashboard's Calendar ([06](../06-participant-dashboard.md)). Printed fingers are declared under `custom_hardware`
   and reviewed with the request. For anything else, post in `#data-and-testbed-requests`, tag Shamar Webster, and
   include the test plan, duration, attendees and dates. Nothing is guaranteed.
4. **Stop Brev instances when you're done**, because credits burn while they run. Stopped instances still incur small storage
   costs. Record the GPU, runtime and credits for each run.
5. **Log every experiment**, including failures, in [../experiments/](../experiments/README.md). Judges want measured
   results against a baseline.
6. **Enable the pre-commit hook once per clone** with `git config core.hooksPath .githooks`. It blocks files over 5 MB,
   `.env` files, weights and keys.
7. **No AI attribution in git history.** Several of us commit here, and each commit belongs to the teammate who makes it.
   No `Co-Authored-By: Claude` (or any AI) trailers and no "Generated with" lines in commit messages or PR descriptions.

## Docs status

- The first batch of pasted docs was **cut off at about 50k characters**; the Isaac Sim ROS 2 joint-control page is partial.
- Still missing: the Compute guide, the Coding agents guide, Isaac Lab on DGX Spark, the Brev getting-started doc, and the
  FANUC Tech Transfer library.
  The live list is in [../README.md](../README.md#not-yet-received).
- The Tools and Resources page was pasted without its hyperlink URLs.

## Deadlines

- **Final submission: Sun Nov 1, 11:59 PM CT.** It needs a ~5 min video, a one-page summary, the repo link and references.
- **Finals: Thu Nov 5, 5–8 PM**, MSOE Diercks Hall.
