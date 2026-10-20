# cell_policy/

Our policy and submission for the organizers' real-robot platform (the participant dashboard,
[docs/06](../docs/06-participant-dashboard.md); the client package,
[docs/references/physicalai-client-package.md](../docs/references/physicalai-client-package.md)). The test: **pick one
M6 countersunk screw off the table and drop it in the yellow bin**, once with the stock fingers and once with our printed
fingers. Each rollout's grasp is aimed at a known offset, so the robot measures success at the same offsets the sim
predicted.

This folder is not a uv workspace member. Its files run inside a clone of the organizers' client package, under that
package's own environment (numpy, OpenCV, PyYAML, requests), the same way the vendored twin keeps its own interpreters.

| File | What |
| --- | --- |
| `policy.py` | The policy (`ACTION = "tcp"`): approach, measure which way the jaws point, descend, close, carry, drop, hold |
| `make_placement.py` | Writes `submission/placement.yaml`: the same screw and bin every rollout, each prompt tagged with its offset |
| `submission/submission.yaml` | Our submission, set for the stock-finger baseline run |
| `submission/placement.yaml` | The default 10-rollout sweep across the jaws: dx = 0, ±1.5, ±3, ±4.5, ±6, 0 mm |
| `test_cell_policy.py` | Unit tests (no client package or robot needed) |

## How the test works

- **The operator places the screw and the bin the same way every rollout.** The default is the screw's head at
  (420, −40) mm, pointing +y, and the bin at (480, 120) mm, near the default scene ([table plan](../docs/images/client-table-plan.png)).
- **Each rollout's prompt carries a tag**, for example
  `[c2f trial=T0007 dx=+3.00 dy=+0.00 dyaw=+0.0 screw=420,-40,90 bin=480,120,0]`. The policy grasps at the screw's centre
  plus that offset.
- The offset uses the app's test-plan frame (`api/models/test_plan.py`): dx along the jaws' closing direction, dy across
  it, dyaw about z.
- The operator's placement error adds to every rollout alike, so it is the same for both finger sets.
- The tag is part of the recorded instruction, so each recorded episode says which offset it was.
- **Why blind?** The screw's pose is fixed, so the policy doesn't need to see it. The commanded offset stands in for
  the camera and calibration error our fingers are designed to absorb. That's the comparison the judges asked for:
  measured success against a baseline, at known errors. The FAQ says the table camera can't see screws anyway. Finding
  them in the images would mean wrist-camera depth close up, which is future work.
- **Which way the jaws close at a given R isn't documented.** The policy measures it twice: at the first observation,
  and again once it is above the screw. Each time it combines `obs["joints"]` through the client's FK
  (`calibration/geometry.py`, jaws along the flange's +y as in the twin) with the R in `obs["tcp_pose"]`. If the jaws
  are more than 2° off before descending, it re-aims them.
- Each rollout appends a line to `cad2fingers_rollouts.jsonl`, next to `policy.py` in the clone: the trial, the
  offset, the jaw measurements and the commanded grasp.

Heights: the fingertips close 2.5 mm above the surface (below a lying screw's shank axis), carry at 120 mm, and open
25 mm above the bin's rim with the screw along the pocket's diagonal (35 mm pocket, 30.7 mm screw). Speeds: 100 mm/s
in free space and 30 mm/s near the table. All of these are constants at the top of `policy.py`.

## Running it

```bash
git clone https://github.com/SIDCLab/PhysicalAI-Hackathon-2026 && cd PhysicalAI-Hackathon-2026
uv sync
cp <repo>/cell_policy/policy.py policy.py
cp <repo>/cell_policy/submission/*.yaml submission/

# Formats and limits only (the mock has no kinematics). On Windows, set PYTHONUTF8=1 first, or the verdict's
# check mark fails to print.
uv run run.py --mock --trials 2 --trial-s 30 --instruction "Put the screw into the yellow bin. [c2f trial=T1 dx=+3.00 dy=+0.00 dyaw=+0.0 screw=420,-40,90 bin=480,120,0]"

uv run run.py --submit     # sends submission/*.yaml; then book a slot in the dashboard's Calendar with the request id
uv run run.py --status     # approved? and our private results link
uv run run.py              # during the slot: leave it running
uv run run.py --download   # the recorded LeRobotDataset
```

**Offsets from the app's test plan.** A test plan has about 100 rows per design, and a run is 10 rollouts, so choose
which rows go in a run. Save the plan as JSON from `GET /api/jobs/{job_id}/test-plans/{plan_id}`, then:

```bash
python make_placement.py --test-plan plan.json --design D1 --trials T0001,T0004,T0005,... --rollouts 10 -o submission/placement.yaml
```

Use the same offsets for the stock run and the printed run. Enter the operator's scores into the app's tracker against
those trial IDs.

## Before a real run

- **Real-arm runs only go through the organizers' platform**, in an approved slot with their operator; nothing here
  talks to the arm any other way (AGENTS.md hard rules). **Printed fingers go on only after the app's review gate
  approves the design**, and they're declared under `custom_hardware`.
- **The finger mount follows SMC's STEP** of the jaw ([cad/README.md](../cad/README.md)). Check it on the real jaw
  before printing: the tongue, the two holes 4 and 11 mm below the shoulder, and which way the screws go.
- `TIP_BELOW_TCP_MM` must be 0, which means our fingertips end where the stock ones do. That holds when the printed
  root butts against the jaw's shoulder as the stock finger's does. The cell's limit is TCP z ≥ −334 mm with the
  surface at about −335, so fingers that end lower could touch the table inside that limit.
- Nothing here has run on the real arm. What was run, on 2026-10-20: the unit tests, and two rollouts against the
  client's `--mock` ("Ready for the real robot", 0 of 461 actions rejected), which checks formats and limits only. The
  first real rollouts should confirm that the jaw measurements in `cad2fingers_rollouts.jsonl` agree (home and above
  the screw) and that the jaws close across the screw.

## Tests

```bash
cd cell_policy && ../.venv/Scripts/python -m unittest test_cell_policy     # Linux/macOS: ../.venv/bin/python
```
