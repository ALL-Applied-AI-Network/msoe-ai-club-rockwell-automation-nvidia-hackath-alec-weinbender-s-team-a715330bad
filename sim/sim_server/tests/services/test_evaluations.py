"""services/evaluations.py: the batch bookkeeping, driven with a fake cell (no Isaac, no IK)."""

import logging

import pytest

from sim_server.models.batch import GraspBatch
from sim_server.models.grasp import GraspPlanError
from sim_server.models.outcome import GraspOutcome
from sim_server.models.pose import BodyPose
from sim_server.robot.poses import DROP_GAP, NOMINAL_SITE_XY, yaw_quaternion
from sim_server.services.batches import design_from_mm, offset_from_mm, part_from_mm
from sim_server.services.evaluations import evaluate_batch

SPREAD = (0.0, 1.0)  # jaws close along base Y; dx moves the part along +Y
LIFT = 0.13


class FakePlanner:
    site_xy = NOMINAL_SITE_XY
    spread_xy = SPREAD

    def __init__(self, surface_dz: float, unreachable_tip: float | None = None):
        self.surface_dz, self.unreachable_tip = surface_dz, unreachable_tip
        self.calls: list[tuple[float, float, str | None]] = []

    def plan(self, tip_height: float, jaw_close: float, transport=None):
        if self.unreachable_tip is not None and tip_height == pytest.approx(self.unreachable_tip):
            raise GraspPlanError("IK failed during descend")
        self.calls.append((tip_height, jaw_close, transport))
        return ("plan", round(tip_height, 7), round(jaw_close, 7), transport)

    def lift_tip(self, tip_height: float):
        return (*self.site_xy, self.surface_dz + tip_height + LIFT)


class FakeCell:
    """Holds the part when it ended up less than 2 mm off the nominal site along the closing direction, and lifts it
    straight up by the lift height, exactly as it was placed (so its in-hand pose is its offset). Under a transport it
    keeps it only when that's less than 0.5 mm. Its landing reports that offset as the shift, and no turn. blow_up makes
    every held grasp report no pose."""

    def __init__(self, geometry, env_count: int, planner: FakePlanner | None = None, blow_up: bool = False):
        self.geometry, self.env_count = geometry, env_count
        self.planner = planner or FakePlanner(geometry.surface_dz)
        self.blow_up = blow_up
        self.chunks = []

    def run_chunk(self, part, grasps, grip_force):
        assert len(grasps) <= self.env_count
        self.chunks.append((part, grasps, grip_force))
        outcomes = []
        for grasp in grasps:
            off = abs(grasp.pose.position[1] - NOMINAL_SITE_XY[1])
            x, y, z = grasp.pose.position
            lifted = BodyPose(position=(x, y, z + LIFT), orientation=yaw_quaternion(grasp.pose.yaw_deg))
            transport = grasp.plan[3]
            outcomes.append(
                GraspOutcome(
                    held=off < 0.002,
                    lift_pose=None if self.blow_up else lifted,
                    held_after_transport=None if transport is None else off < 0.0005,
                    landing=(off, 0.0),
                )
            )
        return outcomes


def cube_batch(box_piece, offsets_mm=(0, 1, 3), part=None, **settings) -> GraspBatch:
    points, triangles = box_piece(2, 12, -3, 3, 0, 76)
    custom = design_from_mm("pad", pieces_mm=[(points, triangles)], friction=[0.6, 0.5], tip_height_mm=2.5, jaw_close_mm=2.7)
    return GraspBatch(
        part=part or part_from_mm("box", box_mm=[10, 10, 10], mass_g=4),
        designs=(design_from_mm("stock"), custom),
        offsets=tuple(offset_from_mm(dx, 0, 0) for dx in offsets_mm),
        **settings,
    )


def test_rows_follow_designs_and_offsets(geo, box_piece):
    cell = FakeCell(geo, env_count=4)
    batch = cube_batch(box_piece)
    outcome = evaluate_batch(cell, batch)
    assert outcome.held == ((True, True, False), (True, True, False))
    assert [len(grasps) for _, grasps, _ in cell.chunks] == [4, 2]  # 6 grasps on 4 environments
    grasps = [grasp for _, chunk, _ in cell.chunks for grasp in chunk]
    assert [grasp.design.id for grasp in grasps] == ["stock"] * 3 + ["pad"] * 3  # design-major, contiguous
    # true poses: the nominal pose moved dx along the jaws' closing direction (toward JawL)
    assert [grasp.pose.position[1] - NOMINAL_SITE_XY[1] for grasp in grasps[:3]] == pytest.approx([0.0, 0.001, 0.003])
    assert grasps[0].pose.position[2] == pytest.approx(geo.surface_dz + 0.005, abs=2e-4)  # resting on the surface
    assert grasps[0].plan == grasps[1].plan  # copies of a design share its plan
    assert grasps[3].plan == ("plan", 0.0025, 0.0027, None)  # the custom design's own settings, no transport


def test_in_hand_is_the_part_pose_in_the_commanded_gripper_frame(geo, box_piece):
    """The fake lifts the part exactly as placed, so its in-hand pose is its offset (dz: the spawn gap)."""
    batch = GraspBatch(
        part=part_from_mm("box", box_mm=[10, 10, 10], mass_g=4),
        designs=(design_from_mm("stock"),),
        offsets=(offset_from_mm(0, 0, 0), offset_from_mm(1.0, -0.5, 12.0), offset_from_mm(3, 0, 0)),
    )
    outcome = evaluate_batch(FakeCell(geo, env_count=8), batch)
    centred, moved, dropped = outcome.in_hand[0]
    assert (centred.dx, centred.dy, centred.dz, centred.tilt_deg, centred.yaw_deg) == pytest.approx((0, 0, DROP_GAP, 0, 0), abs=1e-12)
    assert (moved.dx, moved.dy, moved.yaw_deg) == pytest.approx((0.001, -0.0005, 12.0))
    assert moved.tilt_deg == pytest.approx(0.0, abs=1e-9)
    assert dropped is None  # not held: no in-hand pose
    assert outcome.held_after_transport is None  # no transport in the batch


def test_in_hand_accounts_for_each_designs_tip_height(geo, box_piece):
    """The custom design stops its tips at 2.5 mm like stock here; a taller tip height moves G up, and the expected
    centre down with it, so a part lifted the same way still reads dz = the spawn gap."""
    points, triangles = box_piece(2, 12, -3, 3, 0, 76)
    high = design_from_mm("high", pieces_mm=[(points, triangles)], friction=[0.6, 0.5], tip_height_mm=6.0, jaw_close_mm=2.7)
    batch = GraspBatch(part=part_from_mm("box", box_mm=[10, 10, 10], mass_g=4), designs=(high,), offsets=(offset_from_mm(0, 0, 0),))
    (pose,) = evaluate_batch(FakeCell(geo, env_count=2), batch).in_hand[0]
    assert pose.dz == pytest.approx(DROP_GAP, abs=1e-12)


def test_transport_and_grip_force_reach_the_plans_and_the_cell(geo, box_piece):
    planner = FakePlanner(geo.surface_dz)
    cell = FakeCell(geo, env_count=4, planner=planner)
    outcome = evaluate_batch(cell, cube_batch(box_piece, offsets_mm=(0, 1, 3), transport="fast", grip_force=12.5))
    assert {call[2] for call in planner.calls} == {"fast"}
    assert all(grasp.plan[3] == "fast" for _, chunk, _ in cell.chunks for grasp in chunk)
    assert {grip_force for _, _, grip_force in cell.chunks} == {12.5}
    assert outcome.held_after_transport == ((True, False, False), (True, False, False))
    assert outcome.held == ((True, True, False), (True, True, False))


def test_no_grip_force_means_the_twins_drive(geo, box_piece):
    cell = FakeCell(geo, env_count=8)
    evaluate_batch(cell, cube_batch(box_piece))
    assert {grip_force for _, _, grip_force in cell.chunks} == {None}


def test_a_held_part_without_a_pose_has_no_in_hand_pose(geo, box_piece):
    outcome = evaluate_batch(FakeCell(geo, env_count=8, blow_up=True), cube_batch(box_piece))
    assert outcome.held[0] == (True, True, False)
    assert outcome.in_hand[0] == (None, None, None)


def test_reference_path_runs_one_grasp_per_chunk(geo, box_piece):
    cell = FakeCell(geo, env_count=1)
    evaluate_batch(cell, cube_batch(box_piece))
    assert [len(grasps) for _, grasps, _ in cell.chunks] == [1] * 6


def test_a_part_too_wide_for_stock_fingers_isnt_simulated(geo, box_piece, caplog):
    cap = part_from_mm("cylinder", diameter_mm=31.75, length_mm=15.7, mass_g=5)
    cell = FakeCell(geo, env_count=8)
    with caplog.at_level(logging.WARNING):
        outcome = evaluate_batch(cell, cube_batch(box_piece, part=cap, transport="slow"))
    assert outcome.held[0] == (False, False, False)  # stock: dropped without simulating
    assert outcome.in_hand[0] == (None, None, None)
    assert outcome.held_after_transport[0] == (False, False, False)
    assert outcome.landing[0] == (None, None, None)  # not simulated: nothing measured
    assert outcome.held[1] == (True, True, False)
    assert {grasp.design.id for _, grasps, _ in cell.chunks for grasp in grasps} == {"pad"}
    assert "open stock tips" in caplog.text


def test_landing_is_reported_per_design_and_offset(geo, box_piece):
    """What the cell measured while the gripper came down, passed through as it is (the fake: the offset, no turn)."""
    outcome = evaluate_batch(FakeCell(geo, env_count=4), cube_batch(box_piece))
    for row in outcome.landing:
        assert [shift for shift, _ in row] == pytest.approx([0.0, 0.001, 0.003])
        assert [turn for _, turn in row] == [0.0, 0.0, 0.0]


def test_a_mesh_part_is_judged_by_its_width_and_centred_at_mid_height(geo, box_piece):
    """An L-bracket 10 mm wide (fits the stock tips), 24 mm tall: it rests with its origin 12 mm up."""
    leg, foot = box_piece(-5, 5, -2, 2, 0, 24), box_piece(-5, 5, -18, -2, 0, 4)
    bracket = part_from_mm("mesh", pieces_mm=[leg, foot], mass_g=4.3)
    cell = FakeCell(geo, env_count=8)
    outcome = evaluate_batch(cell, cube_batch(box_piece, part=bracket))
    assert outcome.held[0] == (True, True, False)  # simulated with stock fingers
    grasp = cell.chunks[0][1][0]
    assert grasp.pose.position[2] == pytest.approx(geo.surface_dz + 0.012 + DROP_GAP)
    assert outcome.in_hand[0][0].dz == pytest.approx(DROP_GAP, abs=1e-12)


def test_an_unplannable_design_fails_before_anything_runs(geo, box_piece):
    cell = FakeCell(geo, env_count=4, planner=FakePlanner(geo.surface_dz, unreachable_tip=0.0025))
    with pytest.raises(GraspPlanError):
        evaluate_batch(cell, cube_batch(box_piece))
    assert cell.chunks == []


def test_no_offsets_gives_empty_rows(geo, box_piece):
    cell = FakeCell(geo, env_count=4)
    outcome = evaluate_batch(cell, cube_batch(box_piece, offsets_mm=(), transport="normal"))
    assert outcome.held == ((), ()) and outcome.in_hand == ((), ()) and outcome.held_after_transport == ((), ())
    assert cell.chunks == []
