"""Tests for policy.py and make_placement.py, without the client package or a robot. Run from this folder:
python -m unittest test_cell_policy
"""

import json
import math
import tempfile
import unittest
from pathlib import Path

import make_placement
import numpy as np
import policy


def fake_flange_pose(jaw_yaw_deg: float):
    """An FK stand-in: the tool (flange +x) pointing straight down, the jaws (flange +y) at this yaw in the base frame."""

    def flange_pose(joints):
        a = math.radians(jaw_yaw_deg)
        tool, jaw = np.array([0.0, 0.0, -1.0]), np.array([math.cos(a), math.sin(a), 0.0])
        out = np.eye(4)
        out[:3, 0], out[:3, 1], out[:3, 2] = tool, jaw, np.cross(tool, jaw)
        return out

    return flange_pose


def obs(tcp, instruction="", trial_id="t00"):
    return {"tcp_pose": list(tcp), "joints": [0.0] * 7, "trial": {"trial_id": trial_id, "instruction": instruction, "status": "running"}}


HOME = [300.0, 0.0, -20.0, -180.0, 0.0, 0.0]
TAGGED = "Put the screw into the yellow bin. " + make_placement.tag("T0007", 3.0, 0.0, 0.0, (420, -40, 90), (480, 120, 0))
CUBE_TAGGED = "Put the 16 mm cube into the yellow bin. " + make_placement.tag(
    "T0003", -2.0, 0.0, 0.0, (420, -40, 0), (480, 120, 0), kind="cube", tip=2.0
)


class InstructionTest(unittest.TestCase):
    def test_the_tag_make_placement_writes_is_what_the_policy_reads(self):
        rollout = policy.parse_instruction(TAGGED)

        self.assertEqual((rollout.trial, rollout.dx_mm, rollout.dy_mm, rollout.dyaw_deg), ("T0007", 3.0, 0.0, 0.0))
        self.assertEqual((rollout.part, rollout.bin), ((420.0, -40.0, 90.0), (480.0, 120.0, 0.0)))
        self.assertEqual((rollout.kind, rollout.tip_mm), ("screw", policy.GRASP_TIP_HEIGHT_MM))

    def test_a_cube_tag_carries_the_part_and_the_grip_height(self):
        rollout = policy.parse_instruction(CUBE_TAGGED)

        self.assertEqual((rollout.trial, rollout.kind, rollout.dx_mm, rollout.tip_mm), ("T0003", "cube", -2.0, 2.0))
        self.assertEqual(rollout.part, (420.0, -40.0, 0.0))

    def test_no_tag_means_the_default_poses_and_no_offset(self):
        rollout = policy.parse_instruction("pick one countersunk screw and drop it in the yellow bin")

        self.assertEqual((rollout.trial, rollout.dx_mm, rollout.part), (None, 0.0, policy.DEFAULT_SCREW))


class GraspTest(unittest.TestCase):
    def test_the_jaws_close_across_the_screw_at_its_centre_plus_the_offset(self):
        screw_along_y = policy.Rollout("T1", 0.0, 0.0, 0.0, (420.0, -40.0, 90.0), (480.0, 120.0, 0.0))

        x, y, r = policy.grasp_target(screw_along_y, jaw_yaw_at_r0=90.0, near_r=0.0)
        self.assertAlmostEqual(x, 420.0)
        self.assertAlmostEqual(y, -40.0 + policy.GRASP_ALONG_MM)
        self.assertAlmostEqual(math.cos(math.radians(r + 90.0 - 180.0)) ** 2, 1.0, msg="jaws along x, across the screw")

        shifted = policy.Rollout("T2", 3.0, 2.0, 5.0, screw_along_y.part, screw_along_y.bin)
        sx, sy, sr = policy.grasp_target(shifted, jaw_yaw_at_r0=90.0, near_r=0.0)
        self.assertAlmostEqual(abs(sx - x), 3.0, msg="dx along the jaws (base x here)")
        self.assertAlmostEqual(abs(sy - y), 2.0, msg="dy across them")
        self.assertAlmostEqual(policy.nearest_equivalent(sr - r, near=0.0), 5.0, msg="the jaws look the same every 180 deg")

    def test_a_cube_is_gripped_at_its_centre_with_the_jaws_along_its_yaw(self):
        cube = policy.Rollout("T1", 0.0, 0.0, 0.0, (420.0, -40.0, 30.0), (480.0, 120.0, 0.0), kind="cube")

        x, y, r = policy.grasp_target(cube, jaw_yaw_at_r0=90.0, near_r=0.0)
        self.assertAlmostEqual((x, y), (420.0, -40.0))
        self.assertAlmostEqual(policy.nearest_equivalent(90.0 + r - 30.0, near=0.0), 0.0, msg="jaws close along yaw 30")

        shifted = policy.Rollout("T2", 2.0, 0.0, 0.0, cube.part, cube.bin, kind="cube")
        sx, sy, _ = policy.grasp_target(shifted, jaw_yaw_at_r0=90.0, near_r=0.0)
        self.assertAlmostEqual(math.hypot(sx - x, sy - y), 2.0)
        self.assertAlmostEqual(math.degrees(math.atan2(sy - y, sx - x)) % 180.0, 30.0, msg="dx along the jaws")

    def test_r_is_the_nearest_of_the_two_equivalent_jaw_angles(self):
        self.assertEqual(policy.nearest_equivalent(-80.0, near=170.0), 100.0)
        self.assertEqual(policy.nearest_equivalent(100.0, near=-150.0), -80.0)


class PolicyTest(unittest.TestCase):
    def make(self, jaw_yaw_deg: float) -> policy.Policy:
        p = policy.Policy()
        p.flange_pose = fake_flange_pose(jaw_yaw_deg)
        return p

    def setUp(self):
        self.log = Path(tempfile.mkdtemp()) / "rollouts.jsonl"
        self._log_file, policy.LOG_FILE = policy.LOG_FILE, self.log

    def tearDown(self):
        policy.LOG_FILE = self._log_file

    def test_a_rollout_approaches_picks_drops_and_holds_within_the_cells_limits(self):
        p = self.make(jaw_yaw_deg=90.0)  # at home, R = 0: the jaws are at 90 deg at R = 0

        approach = p.act(obs(HOME, TAGGED))
        self.assertTrue(1 <= len(approach) <= policy.MAX_CHUNK and policy.check_rows(approach) == [])
        above = approach[-1]
        self.assertEqual(above[2], policy.tip_z(policy.APPROACH_HEIGHT_MM))

        p.flange_pose = fake_flange_pose(90.0 + above[5])  # the jaws turned with R, as measured above the screw
        rest = []
        while len(rest) == 0 or len(p.queue):
            rest += p.act(obs(above[:6], TAGGED))
        self.assertEqual(policy.check_rows(rest), [])
        grip = [row for row in rest if row[6] == 1.0]
        self.assertAlmostEqual(min(row[2] for row in grip), policy.tip_z(policy.GRASP_TIP_HEIGHT_MM))
        self.assertTrue(all(row[2] >= policy.TCP_BOX_MM[2][0] for row in rest))
        self.assertEqual((rest[-1][0], rest[-1][1], rest[-1][6]), (480.0, 120.0, 0.0), "ends above the bin, open")
        steps = [math.dist(a[:3], b[:3]) for a, b in zip(rest, rest[1:], strict=False)]
        self.assertLessEqual(max(steps), policy.TRAVEL_STEP_MM + 1e-6)

        self.assertEqual(p.act(obs(rest[-1][:6], TAGGED)), [rest[-1][:6] + [0.0]], "then holds still")
        record = json.loads(self.log.read_text().splitlines()[-1])
        self.assertEqual((record["rollout"]["trial"], record["jaws_measured"]), ("T0007", True))

    def test_jaws_measured_off_above_the_screw_are_re_aimed_before_descending(self):
        p = self.make(jaw_yaw_deg=90.0)
        above = p.act(obs(HOME, TAGGED))[-1]

        p.flange_pose = fake_flange_pose(80.0 + above[5])  # 10 deg short of what R was meant to give
        first = p.act(obs(above[:6], TAGGED))
        descend = next(i for i, row in enumerate(first) if row[2] < above[2] - 1e-6)
        self.assertAlmostEqual(policy.wrap180(first[descend - 1][5] - above[5]), 10.0, places=6)

    def test_a_jaw_measurement_far_from_an_earlier_one_is_not_trusted(self):
        p = self.make(jaw_yaw_deg=90.0)
        above = p.act(obs(HOME, TAGGED))[-1]

        p.flange_pose = fake_flange_pose(90.0)  # joints still at home while tcp_pose says R turned: out of step
        p.act(obs(above[:6], TAGGED))
        self.assertAlmostEqual(p.jaw_yaw_at_r0, 90.0)

    def run_from_above(self, instruction: str):
        """The rollout after the approach: the rows from above the part on, and the pose it stopped above it at."""
        p = self.make(jaw_yaw_deg=90.0)
        above = p.act(obs(HOME, instruction))[-1]
        p.flange_pose = fake_flange_pose(90.0 + above[5])
        rest = []
        while len(rest) == 0 or len(p.queue):
            rest += p.act(obs(above[:6], instruction))
        return rest, above

    def test_a_cube_rollout_grips_at_the_tagged_height_within_the_cells_limits(self):
        rest, _ = self.run_from_above(CUBE_TAGGED)

        self.assertEqual(policy.check_rows(rest), [])
        self.assertAlmostEqual(min(row[2] for row in rest if row[6] == 1.0), policy.tip_z(2.0))
        self.assertEqual((rest[-1][0], rest[-1][1], rest[-1][6]), (480.0, 120.0, 0.0))

    def test_a_grip_lower_than_the_cell_allows_is_refused_and_the_arm_holds_above_the_part(self):
        # EXP-0006's D1 grips the cube with its tips 1.0 mm up; the cell refuses the TCP below 1.1 mm.
        too_low = CUBE_TAGGED.replace("tip=2]", "tip=1]")

        rest, above = self.run_from_above(too_low)
        self.assertEqual(rest, [above[:6] + [0.0]])

    def test_a_plan_outside_the_cell_is_refused_and_the_arm_holds(self):
        p = self.make(jaw_yaw_deg=90.0)
        far = "Go. " + make_placement.tag("T9", 0.0, 0.0, 0.0, (600, 300, 0), (480, 120, 0))

        self.assertEqual(p.act(obs(HOME, far)), [HOME + [0.0]])


class PlacementTest(unittest.TestCase):
    def test_the_default_sweep_is_ten_rollouts_with_the_same_objects(self):
        text = make_placement.placement_yaml(
            [(f"R{i:02d}", dx, dy, dyaw) for i, (dx, dy, dyaw) in enumerate(make_placement.DEFAULT_SWEEP, 1)],
            make_placement.DEFAULT_SCREW,
            make_placement.DEFAULT_BIN,
            make_placement.TASK,
        )
        prompts = [line.split("prompt: ", 1)[1].strip('"') for line in text.splitlines() if "prompt:" in line]

        self.assertEqual(len(prompts), 10)
        self.assertEqual(text.count("screw: [420, -40, 90]"), 10)
        self.assertEqual([policy.parse_instruction(p).dx_mm for p in prompts], [dx for dx, _, _ in make_placement.DEFAULT_SWEEP])

    def test_a_test_plans_rows_become_rollouts_in_the_order_asked(self):
        rows = [
            {"trial_id": "T0001", "design_label": "D1", "offset_x_mm": 0, "offset_y_mm": 0, "yaw_deg": 0},
            {"trial_id": "T0002", "design_label": "D1", "offset_x_mm": 3, "offset_y_mm": 0, "yaw_deg": 0},
            {"trial_id": "T0003", "design_label": "STOCK", "offset_x_mm": 3, "offset_y_mm": 0, "yaw_deg": 0},
        ]
        path = Path(tempfile.mkdtemp()) / "plan.json"
        path.write_text(json.dumps({"rows": rows}))

        self.assertEqual([r[0] for r in make_placement.rows_from_plan(path, "D1", None, None)], ["T0001", "T0002"])
        self.assertEqual([r[0] for r in make_placement.rows_from_plan(path, None, None, ["T0003", "T0001"])], ["T0003", "T0001"])

    def test_a_layout_out_of_reach_is_refused(self):
        self.assertIn("past 540 mm", make_placement.check_layout((420, -40, 90), (520, 200, 0))[0])
        self.assertEqual(make_placement.check_layout(make_placement.DEFAULT_SCREW, make_placement.DEFAULT_BIN), [])

    def test_the_cube_sweep_is_ten_cube_rollouts_the_policy_reads(self):
        path = Path(tempfile.mkdtemp()) / "placement.yaml"
        make_placement.main(["--part", "cube", "--tip", "2.5", "--rollouts", "10", "-o", str(path)])
        text = path.read_text()
        prompts = [line.split("prompt: ", 1)[1].strip('"') for line in text.splitlines() if "prompt:" in line]

        self.assertEqual(text.count("cube_16mm: [420, -40, 0]"), 10)
        rollouts = [policy.parse_instruction(p) for p in prompts]
        self.assertEqual({(r.kind, r.tip_mm) for r in rollouts}, {("cube", 2.5)})
        self.assertEqual([(r.dx_mm, r.dy_mm, r.dyaw_deg) for r in rollouts], [tuple(map(float, o)) for o in make_placement.DEFAULT_CUBE_SWEEP])

    def test_a_grip_below_the_cells_limit_or_a_cube_offset_past_the_fingers_slack_is_refused(self):
        self.assertIn("refuses the TCP", make_placement.check_rollouts([("R01", 0.0, 0.0, 0.0)], "cube", 1.0)[0])
        self.assertIn("R02", make_placement.check_rollouts([("R01", 4.5, 0, 0), ("R02", -6.0, 0, 0)], "cube", None)[0])
        self.assertEqual(make_placement.check_rollouts([("R01", 6.0, 0, 0)], "screw", None), [], "a screw is knocked aside")


if __name__ == "__main__":
    unittest.main()
