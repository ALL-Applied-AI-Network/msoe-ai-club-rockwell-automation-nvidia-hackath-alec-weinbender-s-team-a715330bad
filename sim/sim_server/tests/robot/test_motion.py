"""The grasp motion, solved with the twin's own IK/FK on the host (numpy only, no Isaac)."""

import sys
import types

import pytest

np = pytest.importorskip("numpy")  # numpy comes with Isaac's python and the twin; sim-server doesn't declare it

import fk  # noqa: E402  (the twin's modules need numpy)
import scene_config as C  # noqa: E402

from sim_server.models.grasp import GraspPlanError  # noqa: E402
from sim_server.robot.motion import (  # noqa: E402
    FPS,
    HOME_TIP,
    LIFT_HEIGHT,
    SEGMENT_SECONDS,
    SETTLE_SECONDS,
    TRANSPORT_MOVE,
    TRANSPORT_SECONDS,
    GraspPlanner,
    ease,
    turn,
)

MM = 1e-3


@pytest.fixture(scope="module")
def planner(geo):
    return GraspPlanner(geo)


def tool_pose(planner, q):
    return fk.tool_pose(q, (planner._geo.tip_offset, 0.0, 0.0))


def test_home_is_the_twin_home(planner):
    r, tip = tool_pose(planner, planner.q_home)
    assert tip == pytest.approx(HOME_TIP, abs=1e-3)
    assert r @ np.array(C.TOOL_AXIS) == pytest.approx([0, 0, -1], abs=1e-2)  # pointing down
    assert abs(planner.spread[1]) == pytest.approx(1.0) and planner.spread[2] == 0  # jaws close along base Y


def test_stock_cube_plan(planner, geo):
    plan = planner.plan(C.CUBE_TIP_CLEARANCE, C.CUBE_JAW_HALF_TARGET)
    ends = plan.segment_end
    assert list(ends.values()) == [36, 60, 78, 93, 117] and plan.frames == 117  # 1.2, 0.8, 0.6, 0.5, 0.8 s at 30 fps
    assert plan.arm.shape == (117, 6)

    r, tip = tool_pose(planner, plan.arm[ends["descend"] - 1])
    assert tip == pytest.approx([*planner.site_xy, geo.surface_dz + C.CUBE_TIP_CLEARANCE], abs=1e-3)  # tips 2.5 mm up
    # G at the grasp: +z (= -TOOL_AXIS) points up, +x (FINGER_SPREAD_AXIS, toward JawL) along the planner's spread.
    assert -(r @ np.array(C.TOOL_AXIS)) == pytest.approx([0, 0, 1], abs=1e-2)
    assert r @ np.array(C.FINGER_SPREAD_AXIS) == pytest.approx(planner.spread, abs=1e-2)

    _, top = tool_pose(planner, plan.arm[-1])
    assert top == pytest.approx(tip + [0, 0, LIFT_HEIGHT], abs=1e-3)

    assert plan.jaw[: ends["descend"]] == pytest.approx(geo.jaw_open)  # open until the close segment
    assert plan.jaw[ends["close"] - 1 :] == pytest.approx(C.CUBE_JAW_HALF_TARGET)
    assert np.all(np.diff(plan.jaw[ends["descend"] : ends["close"]]) <= 0)


def test_plans_are_cached_and_follow_the_tip_height(planner):
    a = planner.plan(0.004, 0.0012)
    assert planner.plan(0.004, 0.0012) is a
    b = planner.plan(0.006, 0.0012)
    grasp = a.segment_end["descend"] - 1
    (_, tip_a), (_, tip_b) = tool_pose(planner, a.arm[grasp]), tool_pose(planner, b.arm[grasp])
    assert tip_b - tip_a == pytest.approx([0, 0, 0.002], abs=1e-4)


def test_lift_tip_is_where_the_lift_ends(planner, geo):
    plan = planner.plan(0.004, 0.0012)
    _, top = tool_pose(planner, plan.arm[plan.segment_end["lift"] - 1])
    assert planner.lift_tip(0.004) == pytest.approx((*planner.site_xy, geo.surface_dz + 0.004 + LIFT_HEIGHT))
    assert top == pytest.approx(planner.lift_tip(0.004), abs=1e-3)


@pytest.mark.parametrize("transport", ["slow", "normal", "fast"])
def test_transport_carries_the_part_across_the_jaws_then_settles(planner, geo, transport):
    plan = planner.plan(C.CUBE_TIP_CLEARANCE, C.CUBE_JAW_HALF_TARGET, transport)
    ends = plan.segment_end
    move_frames, settle_frames = round(TRANSPORT_SECONDS[transport] * FPS), round(SETTLE_SECONDS * FPS)
    assert list(ends) == ["approach", "descend", "close", "dwell", "lift", "transport", "settle"]
    assert ends["transport"] - ends["lift"] == move_frames and ends["settle"] - ends["transport"] == settle_frames == 15
    assert plan.frames == ends["settle"] == 117 + move_frames + 15
    without = planner.plan(C.CUBE_TIP_CLEARANCE, C.CUBE_JAW_HALF_TARGET)
    assert np.array_equal(plan.arm[: ends["lift"]], without.arm) and np.array_equal(plan.jaw[: ends["lift"]], without.jaw)

    _, top = tool_pose(planner, plan.arm[ends["lift"] - 1])
    r, end = tool_pose(planner, plan.arm[ends["transport"] - 1])
    assert end == pytest.approx(top + np.array(TRANSPORT_MOVE), abs=1e-3)  # 0.12 m along base +X, same height
    assert end[0] == pytest.approx(0.42, abs=1e-3)
    assert -(r @ np.array(C.TOOL_AXIS)) == pytest.approx([0, 0, 1], abs=1e-2)  # still pointing down
    assert r @ np.array(C.FINGER_SPREAD_AXIS) == pytest.approx(planner.spread, abs=1e-2)  # jaws still along the spread
    for frame in range(ends["transport"], ends["settle"]):  # settle: hold still
        assert tool_pose(planner, plan.arm[frame])[1] == pytest.approx(end, abs=1e-6)
    assert plan.jaw[ends["lift"] :] == pytest.approx(C.CUBE_JAW_HALF_TARGET)  # the jaws stay closed throughout
    middle = tool_pose(planner, plan.arm[ends["lift"] + move_frames // 2 - 1])[1]
    assert top[0] < middle[0] < end[0]  # eased, not a jump


@pytest.mark.parametrize("tip_height", [0.0, 0.0025, 0.03, 0.08])
def test_transport_is_reachable_across_tip_heights(planner, tip_height):
    """The move ends at x = 0.42 m, inside the twin's pick span (x 0.24..0.46), at every plausible grasp height."""
    for transport in TRANSPORT_SECONDS:
        planner.plan(tip_height, 0.002, transport)  # raises GraspPlanError if any frame fails the IK checks


def test_plans_are_keyed_by_transport(planner):
    a = planner.plan(0.005, 0.002, "fast")
    assert planner.plan(0.005, 0.002, "fast") is a
    assert planner.plan(0.005, 0.002, "slow") is not a and planner.plan(0.005, 0.002) is not a
    assert "transport" not in planner.plan(0.005, 0.002).segment_end
    with pytest.raises(ValueError, match="transport"):
        planner.plan(0.005, 0.002, "warp")


def test_a_task_plan_is_the_grasp_then_its_own_moves(planner, geo):
    """The example videos' moves (scripts/record_task_examples.py): carry 0.10 m along base -Y, lower to the table, open,
    rise. The twin places vials at (0.30, +-0.08) on the table, so this is within its reach."""
    tip, jaw = C.CUBE_TIP_CLEARANCE, C.CUBE_JAW_HALF_TARGET
    up = (0.30, -0.10, geo.surface_dz + tip + LIFT_HEIGHT)
    down = (0.30, -0.10, geo.surface_dz + tip + 0.0015)
    moves = [("carry", up, jaw, 1.2), ("lower", down, jaw, 0.9), ("release", None, geo.jaw_open, 0.5), ("rise", up, geo.jaw_open, 0.8)]

    plan = planner.plan_task(tip, jaw, moves)

    grasp = planner.plan(tip, jaw)
    ends = plan.segment_end
    assert list(ends) == ["approach", "descend", "close", "dwell", "lift", "carry", "lower", "release", "rise"]
    assert np.array_equal(plan.arm[: ends["lift"]], grasp.arm)  # the grasp is the batch's own
    assert plan.frames == grasp.frames + round((1.2 + 0.9 + 0.5 + 0.8) * FPS)
    assert tool_pose(planner, plan.arm[ends["lower"] - 1])[1] == pytest.approx(down, abs=1e-3)
    released = tool_pose(planner, plan.arm[ends["release"] - 1])[1]
    assert released == pytest.approx(down, abs=1e-3)  # None: it stays put while the jaws open (within the IK's 1 mm)
    assert plan.jaw[ends["lower"] - 1] == pytest.approx(jaw) and plan.jaw[-1] == pytest.approx(geo.jaw_open)


def test_unreachable_grasp_is_refused(planner):
    with pytest.raises(GraspPlanError):
        planner.plan(0.6, 0.001)  # fingertips 0.6 m up: the wrist can't get there pointing down


def test_segments_match_the_twin(monkeypatch, planner):
    """sort_scene.py imports OpenCV through cube_pose; stub that module to import the real segments(), ease() and turn()."""
    monkeypatch.setitem(sys.modules, "cube_pose", types.SimpleNamespace(square_yaw=lambda deg: deg))
    monkeypatch.delitem(sys.modules, "sort_scene", raising=False)
    import sort_scene

    pick = {"xy": list(planner.site_xy), "pick_z": -0.0026, "place_xy": [0.28, 0.10], "place_z": 0.0, "category": "cube"}
    home = np.array(HOME_TIP)
    twin = sort_scene.segments(pick, home)[: len(SEGMENT_SECONDS)]  # (name, from, to, seconds, jaw from, jaw to, spread)
    assert [(s[0], s[3]) for s in twin] == list(SEGMENT_SECONDS)
    p = np.array([*pick["xy"], pick["pick_z"]])
    up = p + [0, 0, LIFT_HEIGHT]
    expected_moves = [(home, up), (up, p), (p, p), (p, p), (p, up)]
    for s, (start, end) in zip(twin, expected_moves, strict=True):
        assert s[1] == pytest.approx(start) and s[2] == pytest.approx(end)
    assert [s[4] for s in twin] == pytest.approx([C.JAW_OPEN] * 3 + [C.CUBE_JAW_HALF_TARGET] * 2)
    assert [s[5] for s in twin] == pytest.approx([C.JAW_OPEN] * 2 + [C.CUBE_JAW_HALF_TARGET] * 3)
    for t in (0.0, 0.25, 0.5, 1.0):
        assert ease(t) == pytest.approx(sort_scene.ease(t))
        assert turn([1, 0, 0], [0, 1, 0], t) == pytest.approx(sort_scene.turn([1, 0, 0], [0, 1, 0], t))
    assert FPS == 30
