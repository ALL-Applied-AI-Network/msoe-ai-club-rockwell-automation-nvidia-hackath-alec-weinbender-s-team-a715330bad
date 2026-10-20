"""services/evaluations.py: the batch bookkeeping, driven with a fake cell (no Isaac, no IK)."""

import logging

import pytest

from sim_server.models.batch import GraspBatch
from sim_server.models.grasp import GraspPlanError
from sim_server.robot.poses import NOMINAL_SITE_XY
from sim_server.services.batches import design_from_mm, offset_from_mm, part_from_mm
from sim_server.services.evaluations import evaluate_batch

SPREAD = (0.0, 1.0)  # jaws close along base Y; dx moves the part along +Y


class FakePlanner:
    site_xy = NOMINAL_SITE_XY
    spread_xy = SPREAD

    def __init__(self, unreachable_tip: float | None = None):
        self.unreachable_tip = unreachable_tip
        self.calls: list[tuple[float, float]] = []

    def plan(self, tip_height: float, jaw_close: float):
        if self.unreachable_tip is not None and tip_height == pytest.approx(self.unreachable_tip):
            raise GraspPlanError("IK failed during descend")
        self.calls.append((tip_height, jaw_close))
        return ("plan", round(tip_height, 7), round(jaw_close, 7))


class FakeCell:
    """Holds the part when it ended up less than 2 mm off the nominal site along the closing direction."""

    def __init__(self, geometry, env_count: int, planner: FakePlanner | None = None):
        self.geometry, self.env_count, self.planner = geometry, env_count, planner or FakePlanner()
        self.chunks = []

    def run_chunk(self, part, grasps):
        assert len(grasps) <= self.env_count
        self.chunks.append((part, grasps))
        return [abs(grasp.pose.position[1] - NOMINAL_SITE_XY[1]) < 0.002 for grasp in grasps]


def cube_batch(box_piece, offsets_mm=(0, 1, 3), part=None) -> GraspBatch:
    points, triangles = box_piece(2, 12, -3, 3, 0, 76)
    custom = design_from_mm("pad", pieces_mm=[(points, triangles)], friction=[0.6, 0.5], tip_height_mm=2.5, jaw_close_mm=2.7)
    return GraspBatch(
        part=part or part_from_mm("box", box_mm=[10, 10, 10], mass_g=4),
        designs=(design_from_mm("stock"), custom),
        offsets=tuple(offset_from_mm(dx, 0, 0) for dx in offsets_mm),
    )


def test_rows_follow_designs_and_offsets(geo, box_piece):
    cell = FakeCell(geo, env_count=4)
    batch = cube_batch(box_piece)
    assert evaluate_batch(cell, batch) == [[True, True, False], [True, True, False]]
    assert [len(grasps) for _, grasps in cell.chunks] == [4, 2]  # 6 grasps on 4 environments
    grasps = [grasp for _, chunk in cell.chunks for grasp in chunk]
    assert [grasp.design.id for grasp in grasps] == ["stock"] * 3 + ["pad"] * 3  # design-major, contiguous
    # true poses: the nominal pose moved dx along the jaws' closing direction (toward JawL)
    assert [grasp.pose.position[1] - NOMINAL_SITE_XY[1] for grasp in grasps[:3]] == pytest.approx([0.0, 0.001, 0.003])
    assert grasps[0].pose.position[2] == pytest.approx(geo.surface_dz + 0.005, abs=2e-4)  # resting on the surface
    assert grasps[0].plan == grasps[1].plan  # copies of a design share its plan
    assert grasps[3].plan == ("plan", 0.0025, 0.0027)  # the custom design's own settings


def test_reference_path_runs_one_grasp_per_chunk(geo, box_piece):
    cell = FakeCell(geo, env_count=1)
    evaluate_batch(cell, cube_batch(box_piece))
    assert [len(grasps) for _, grasps in cell.chunks] == [1] * 6


def test_a_part_too_wide_for_stock_fingers_isnt_simulated(geo, box_piece, caplog):
    cap = part_from_mm("cylinder", diameter_mm=31.75, length_mm=15.7, mass_g=5)
    cell = FakeCell(geo, env_count=8)
    with caplog.at_level(logging.WARNING):
        held = evaluate_batch(cell, cube_batch(box_piece, part=cap))
    assert held[0] == [False, False, False]  # stock: dropped without simulating
    assert held[1] == [True, True, False]
    assert {grasp.design.id for _, grasps in cell.chunks for grasp in grasps} == {"pad"}
    assert "open stock tips" in caplog.text


def test_an_unplannable_design_fails_before_anything_runs(geo, box_piece):
    cell = FakeCell(geo, env_count=4, planner=FakePlanner(unreachable_tip=0.0025))
    with pytest.raises(GraspPlanError):
        evaluate_batch(cell, cube_batch(box_piece))
    assert cell.chunks == []


def test_no_offsets_gives_empty_rows(geo, box_piece):
    cell = FakeCell(geo, env_count=4)
    assert evaluate_batch(cell, cube_batch(box_piece, offsets_mm=())) == [[], []]
    assert cell.chunks == []
