# sim/

| Path | What | Ownership |
| --- | --- | --- |
| [`fanuc_er4ia_sim/`](fanuc_er4ia_sim/) | FANUC ER-4iA Isaac Sim digital twin, **hackathon starter v0.5** (unpacked from the organizers' `fanuc_er4ia_hackathon_starter_v05.zip`, SHA-256 `f5550340…331c2`; the zip itself is no longer in the repo but is in git history at commit `c7014b1`). Calibrated to the real cell's cameras. Demo task: stack six rotated 10 mm cubes. | Upstream (organizers). Edit sparingly and note changes in `../CONTEXT.md`. |
| [`sim_server/`](sim_server/) | Our HTTP service that runs next to Isaac Sim and answers the app's `POST /evaluate` grasp batches. | Ours. Still a stub. |

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

A uv workspace member (`sim/sim_server/pyproject.toml`, code in `src/sim_server/server.py`). From the repo root:

```bash
uv sync --package sim-server        # on the GPU machine: just this member's dependencies
uv run --package sim-server uvicorn sim_server.server:app --host 0.0.0.0 --port 9000
# on the app machine:  SIM_BACKEND=http SIM_URL=http://<host>:9000/evaluate
```

Contract: `POST {part, design:{template, params}, offsets:[{dx, dy, yaw_deg}, ...]}` → `{successes: [bool, ...]}`.
The app sends **millimetres and degrees**; the twin uses **metres**. Convert at this boundary. Reach a Brev instance with
`brev port-forward` or a Secure Link. Don't expose the port publicly.
