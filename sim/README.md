# sim/

| Path | What | Ownership |
| --- | --- | --- |
| [`fanuc_er4ia_sim/`](fanuc_er4ia_sim/) | FANUC ER-4iA Isaac Sim digital twin, **hackathon starter v0.5** (unpacked from the organizers' `fanuc_er4ia_hackathon_starter_v05.zip`, SHA-256 `f5550340…331c2`; the zip itself is no longer in the repo but is in git history at commit `c7014b1`). Calibrated to the real cell's cameras. Demo task: stack six rotated 10 mm cubes. | Upstream (organizers). Edit sparingly and note changes in `../CONTEXT.md`. |
| [`sim_server/`](sim_server/) | Our HTTP service that runs next to Isaac Sim and answers the app's `POST /evaluate_batch` grasp batches in the twin. | Ours. Host-tested only; **not yet run in Isaac** ([GPU test plan](../docs/notes/gpu-test-plan.md)). |

## Twin quick reference

Full instructions: [fanuc_er4ia_sim/README.md](fanuc_er4ia_sim/README.md), [SETUP.md](fanuc_er4ia_sim/SETUP.md),
[AGENTS.md](fanuc_er4ia_sim/AGENTS.md), [docs/CALIBRATION_V05.md](fanuc_er4ia_sim/docs/CALIBRATION_V05.md),
[docs/MODEL_NOTES.md](fanuc_er4ia_sim/docs/MODEL_NOTES.md).

Validated upstream on **Linux + Isaac Sim 6.0 + RTX A6000**. Run it on Brev (Isaac Sim launchable) or the MSOE GB10. Run all
commands from inside `fanuc_er4ia_sim/`:

```bash
./bootstrap.sh                                   # host venv + textures + 33 host tests
export ISAAC=/path/to/isaacsim                   # Isaac's python.sh lives here
"$ISAAC/python.sh" build_scene.py --headless --save runs/scene.usd
export COSMOS=/path/to/cosmos-env/bin/python COSMOS3_NANO_PATH=/path/to/Cosmos3-Nano/snapshot
./run_sort_pipeline.sh runs/stack_01             # capture → perceive → plan → execute → encode
```

On Brev, copy the twin to the instance with `brev copy`, and **stop the instance when you're done**, because credits burn while
it runs. Copy back only the outputs you need (videos, JSON reports) and don't commit them: `runs/` and `*.mp4` are gitignored.

## Finger-related code in the twin

Start here when wiring finger designs into simulation:

- `scene_config.py`: finger dimensions (`FINGER_LENGTH`, `FINGER_WIDTH`, `SCALLOP_*`), stroke (`JAW_STROKE`), `TOOL_LENGTH`, cameras.
- `gripper_geometry.py`: 2-D finger profile + triangulation (Isaac-independent; testable on the host).
- `cell.py`: USD scene, gripper/finger prims, contact physics and friction materials.
- `sort_scene.py`, `ik.py`, `fk.py`: grasp execution and success checks.
- `assets/gripper/`: SMC MHZL2-16D2 actuator mesh and photo-derived finger detail (JSON meshes).

## sim_server

A uv workspace member (`sim/sim_server/pyproject.toml`, code in `src/sim_server/`). It is linted and locked with the rest of
the workspace, but it **runs under Isaac's interpreter**: Isaac Sim only imports from `$ISAAC/python.sh`, not from the uv
venv. So install the package (and with it FastAPI and uvicorn) into Isaac's Python once, then start it from there. From the
repo root on the GPU machine:

```bash
export ISAAC=/path/to/isaacsim
"$ISAAC/python.sh" -m pip install -e sim/sim_server     # once per Isaac install; editable, so code changes need no reinstall
"$ISAAC/python.sh" -m sim_server --port 9000             # reference path: 1 environment, CPU physics
"$ISAAC/python.sh" -m sim_server --port 9000 --envs 64   # vectorised path: 64 copies, GPU physics (cuda:0)
# on the app machine:  SIM_BACKEND=http SIM_URL=http://<host>:9000   (base URL; the app appends /evaluate_batch)
```

Started from the uv venv, it stops at once with an error saying to use `python.sh`. pip installs the newest FastAPI and uvicorn
that `pyproject.toml` allows, not the `uv.lock` pins. Check its output for upgrades or downgrades of packages Isaac
bundles. numpy isn't declared: it comes with Isaac's Python (and the twin needs it anyway). **None of this has run in Isaac
yet;** [docs/notes/gpu-test-plan.md](../docs/notes/gpu-test-plan.md) is the runbook that validates it.

| Flag | Default | What |
| --- | --- | --- |
| `--envs N` | `1` | `1`: the **reference path**, the twin's own robot, one grasp at a time. `N > 1`: the **vectorised path**, N copies of robot + gripper + mat + part stepped together. |
| `--device` | `auto` | `cpu` or `cuda:N`. `auto` is `cpu` for 1 environment (like the twin's `sort_scene.py`), `cuda:0` otherwise. Any combination works, which helps isolate CPU-vs-GPU from 1-vs-N differences. |
| `--env-spacing` | `2.0` | Metres between copies; far enough that copies can't touch. |
| `--friction-combine` | `average` | How PhysX combines a custom finger's friction with the part's (0.9 / 0.8). `max` is the twin's soft-tip convention. |
| `--twin-dir` | `sim/fanuc_er4ia_sim` | Where the twin's modules are imported from. The default is found relative to the package, so it needs the editable install. |
| `--host`, `--port`, `--log-level` | `127.0.0.1`, `9000`, `INFO` | `--host 0.0.0.0` only if a firewall keeps the port private. |

**Contract** (full version in [`routers/evaluations.py`](sim_server/src/sim_server/routers/evaluations.py)'s docstring): `POST /evaluate_batch`
`{part, designs: [{id} | {id, pieces, friction, tip_height_mm, jaw_close_mm}], offsets: [{dx, dy, yaw_deg}]}` →
`{held: [[bool per offset] per design]}`, in millimetres, grams and degrees (converted to the twin's metres in
`services/batches.py`). Every design is tried at every offset. 422 for a request the twin can't run, 503 while shutting down.
The old `POST /evaluate {part, design: {template, params}, offsets}` → `{successes}` still works for template `stock` (it
runs the batch path with one design) and answers 501 for other templates, whose params can't become geometry here.

**What a grasp is.** The part (a dynamic primitive with the twin's part material, 0.9 / 0.8) rests on the mat at the
nominal site **(0.30, 0.0) m** in the robot base frame, straight below the twin's home pose; the jaws close along base Y
there. The robot always plans at that nominal pose with the twin's IK (`robot/motion.py`, a restatement of
`sort_scene.py`'s first five segments): home → approach above the part → descend until the fingertips are `tip_height` above
the surface → close to `jaw_close` → dwell → lift 0.13 m, 30 control frames/s, two 1/60 s physics steps each. Only the
world is set up from the offset (the part's true pose), never the robot's commands. **Held** = the part's centre rose more
than 25 mm (the twin's pickup check). Each grasp starts from rest: robot at home, jaws open, part re-placed; the stage is
only edited when the part or a copy's fingers change (stop, edit, reset, which re-parses physics). Stock fingers follow the
twin's cube rule generalised to the part's width: tips 2.5 mm up, each jaw closed 0.3 mm past where its hook tip meets
the part; a part wider than the 16 mm open tip gap counts as dropped without simulating.

**Gripper frame G** for custom `pieces` (`robot/gripper_frame.py`, checked against the twin's `cell.py` by
`tests/robot/test_gripper_frame.py`):
origin between the two stock fingertips with the jaws closed (on the tool axis, in the fingertip plane, 293 mm from the J6
origin); +z back toward the wrist (up during the grasp); +x along `FINGER_SPREAD_AXIS` toward JawL; +y = z × x. Pieces
describe JawL's finger at jaw = 0; JawR carries the mirror image (x → −x). Each piece is the convex hull of its points
(PhysX `convexHull`, which keeps at most 64 hull vertices); together they replace both stock fingers' contact geometry,
with sub-millimetre contact offsets and a material from `friction`. The jaw bodies, prismatic joints and drives stay. At
jaw = 0 the stock blade's bounding box is x 0..12, y −3..3, z 0..76 mm, as the app assumes, but it isn't a full box: the AA
scallop (r 7.25 mm, centred at x 0, z 6.97) is cut from the inner face below z 14.22, so the hooked tip face at z = 0
spans x 2.0..7.5, and an outer bevel runs from (x 7.5, z 0) to (x 12, z 14). Also on each jaw body, kept for custom
fingers: the carriage collision proxy, x 0.15..15.65, y −4..4, z 58.7..79.85 mm in G (JawL at jaw = 0).

**Testing without the app.** [`sim_server/scripts/send_batch.py`](sim_server/scripts/send_batch.py) (standard library only)
posts a JSON batch and prints what was held; `--grid` swaps in the app's 81-point offset grid and draws a held map,
`--out` saves the run, `--compare a.json b.json` reports where two runs disagree. Example batches are in
[`sim_server/scripts/batches/`](sim_server/scripts/batches/).

```bash
python sim/sim_server/scripts/send_batch.py sim/sim_server/scripts/batches/stock_cube.json --url http://127.0.0.1:9000
uv run pytest sim/sim_server/tests        # host tests: models, frames, units, packing, IK plan, routes, layering (no Isaac)
```

**Code layout** (`src/sim_server/`, the backend's layers: routers -> services -> robot / clients -> models, one direction):

```text
__main__.py      entrypoint: Isaac on the main thread, uvicorn in a thread
app.py           create_app(): the FastAPI app, its routers, Scene + SimQueue on app.state
dependencies.py  SceneDep, SimQueueDep for the routers
routers/         thin HTTP layer; request/response schemas (mm, g, deg) live here
  health.py        GET /health
  evaluations.py   POST /evaluate_batch, legacy POST /evaluate
services/        the work the routers queue; Isaac-free, never imports FastAPI
  evaluations.py   evaluate_batch(cell, batch): bookkeeping against a Cell protocol, the Isaac client handed in
  batches.py       mm -> m conversion into models, the stock grasp rule, design warnings, chunking
robot/           the arm and gripper, Isaac-free
  motion.py        the top-down grasp (the twin's IK); a side grasp would be a sibling module
  gripper_frame.py the gripper frame G <-> flange and jaw bodies
  poses.py         nominal and true part poses
clients/         the external system, Isaac Sim
  isaac.py         GraspCell: stage edits, physics, run_chunk (the only Isaac code besides scene.py)
  env_grid.py      environment layout, view-slot matching (Isaac-free)
models/          frozen pydantic domain objects in the twin's units (m, kg, deg); import no other layer
  part.py  finger.py (Piece, FingerDesign)  offset.py  batch.py (GraspBatch)
  grasp.py (GraspSettings, EnvGrasp, GraspPlanError)  pose.py (PartPose)  gripper.py (GripperGeometry)
scene.py         Isaac app lifecycle (load_scene, Scene)
sim_queue.py     runs jobs on the main thread
twin.py          makes the vendored twin importable
```

Only `clients/isaac.py` and `scene.py` touch Isaac; everything else imports and is tested without it (`tests/test_layers.py`
checks these rules).

**Threading.** Isaac must be driven from a single thread, the one that started it. The server gives Isaac the **main thread**
(`scene.py` starts `SimulationApp` there) and runs uvicorn in a background thread. The routes never call Isaac themselves:
each request becomes one job on a queue (`sim_queue.py`), and the main thread runs jobs one at a time in arrival order
(`services/evaluations.py` is the job; it hands chunks of grasps to `clients/isaac.py`).
`GET /health` reports how many are waiting, plus the environment count and device. The optimizer can send batches
concurrently, so a batch can wait behind others; keep `SIM_TIMEOUT_S` (default 600 s) above that wait.

Reach a Brev instance with `brev port-forward` or a Secure Link. Don't expose the port publicly.
