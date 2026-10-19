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

*Last updated: 2026-10-15*

## Hardware and the demo part

1. **Gripper mismatch: SMC, not SCHUNK.** Our team plan and the Dataset 3 page say "SCHUNK pneumatic two-finger gripper".
   The organizers' twin is built from the CAD of an **SMC MHZL2-16D2**. Finger mounts must match the *real* actuator, so
   confirm with Zhen Zeng (zhenzeng@uwm.edu) before designing any mount interface.
2. **The jaws barely open.** Travel is 6 mm per jaw, so the straight-face gap is **0–12 mm**; at the hooked tips it is about
   4 mm closed and 16 mm open. Tennis balls (~67 mm) and eggs from our plan **cannot be grasped** with this actuator. The
   organizers' feedback ("not all of the existing items will fit in the fingers") is pointing at this.
3. **Objects on the real cell:** ~10 mm yellow cubes, yellow vial caps and clear glass tubes (see the
   [dataset photos](../03-dataset-3-grasping-sorting.md)). These are the realistic demo parts unless we redesign the fingers
   for something larger.
4. **Stock fingers:** aluminium blades of about 76 × 12 × 6 mm, with a hooked tip and an AA-sized circular recess. TCP is
   293 mm from the J6 origin (70 mm to the faceplate plus 223 mm UTOOL1).
5. **The organizers want a specific manufacturing part + task**, a comparison against the **stock fingers**, and the sim
   success rate treated as a prediction to **validate physically**.

## The app

1. **The backend was restructured (2026-10-19).** It's a uv workspace member at `app/backend/` whose package is
   `app/backend/src/api/`, split into routers, services, clients, models and a `db/` package (SQLAlchemy + Alembic); see
   [the coding-style rule](../../.claude/rules/coding-style.md#application-backend). `adapters.py` was split into
   `clients/` (LLM, sim, CAD) and `models/design.py`; `worker.py`'s optimizer is now `services/optimizer.py`.
   `sim_server/` is now `sim/sim_server/src/sim_server/`, and `app/requirements.txt` is gone. Run the app from the repo root
   with `uv run --package backend uvicorn api.main:app --port 8000`. Old local branches touching the backend need manual
   merging: the code moved and was reformatted.
2. **Everything you see is mock.** The default LLM and simulator are mocks. The mock grasp model is made up, so **never
   report mock success rates as results.**
3. **The design space is sized for big parts.** The `SPACE` ranges in `app/backend/src/api/models/design.py` (finger length 15–60 mm,
   pad width up to 40 mm…) and the form defaults (tennis ball, 67 mm) don't fit a 12 mm gripper. They need re-ranging.
4. **CAD output is a placeholder** (`make_scad`, OpenSCAD text). The 3D preview in the UI rebuilds the same shapes. Neither is
   a printable, mountable finger yet.
5. **The 3D preview loads three.js from a CDN** (jsDelivr), so it needs internet access.
6. **The app does not read `.env`.** Export the variables in your shell (see `.env.example`).
7. **Runtime data lives in `app/data/`** (SQLite DB, uploads, outputs). It is gitignored and per-machine.

## The digital twin (`sim/fanuc_er4ia_sim/`)

1. **It needs Linux and an NVIDIA GPU.** It was validated on Linux with Isaac Sim 6.0 on an RTX A6000. It won't run on our
   Windows laptops; use Brev (Isaac Sim launchable, RTX PRO 6000 preferred) or the MSOE GB10.
2. **It uses three Python interpreters:** host `.venv`, Isaac `python.sh` and the Cosmos env. Using the wrong one fails in
   confusing ways.
3. **Isaac can exit with code 0 after crashing.** Check `execution_report.json` (`task_complete: true`), not the exit code.
4. **The robot USD and Cosmos weights are not bundled.** First run needs network access to Isaac's asset root (or set
   `FANUC_ROBOT_USD`).
5. **The demo task is cube stacking, not screws.** The Tools and Resources tutorial prompt says "pick up the screws", but
   v0.5 removed the screw task.
6. **Ground truth is for evaluation only.** Simulator object poses must never feed grasp commands.
7. **Units:** the twin uses metres and degrees, the app uses millimetres. Convert in `sim/sim_server`.
8. **`sim/sim_server` is a stub.** `run_grasps` raises `NotImplementedError`, so the real "grasp in the twin" loop doesn't
   exist yet.
9. **It's vendored upstream code.** Prefer wrappers over edits, and log any edits in `CONTEXT.md` (`MANIFEST.json` has the
   original hashes).

## Rules and process

1. **Never command the physical arm or touch its controller, cameras, PLC or network** without the plant manager and
   mentor. A Claude Code hook blocks driver launches with `robot_ip:=`.
2. **No printed finger goes on the robot before it is reviewed** for clearance and safe operation.
3. **Book CSI time early.** Post in `#data-and-testbed-requests`, tag Shamar Webster, and include the test plan, duration,
   attendees and dates. Nothing is guaranteed.
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
- Still missing: the Compute guide, the Coding agents guide, Isaac Lab on DGX Spark, and the FANUC Tech Transfer library.
  The live list is in [../README.md](../README.md#not-yet-received).
- The Tools and Resources page was pasted without its hyperlink URLs.

## Deadlines

- **Final submission: Sun Nov 1, 11:59 PM CT.** It needs a ~5 min video, a one-page summary, the repo link and references.
- **Finals: Thu Nov 5, 5–8 PM**, MSOE Diercks Hall.
