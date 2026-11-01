import math

import cadquery as cq
import numpy as np
import pytest

from api.clients.sim import MockSim, SimSettings
from api.models.cell_profile import Gripper
from api.models.finger import SQUEEZE_MM, build_finger, problems
from api.models.grasp import (
    LAST_RESORT,
    ROUND_NOTE,
    GraspChoice,
    GraspPick,
    check_grasp,
    posed_part,
    propose_grasps,
    reach_mm,
    table_mesh,
)
from api.models.part_record import PartRecord
from api.models.resting_pose import resting_poses
from api.models.search_space import SearchSpace

GRIPPER = Gripper()  # the UWM CSI cell: reaches around 83 mm, stock tips open 16 mm
MU = 0.5  # PLA against the pad
STOCK = "the stock fingers open at most 16 mm, so the stock baseline will score 0"


@pytest.fixture(scope="module")
def read(cad, shapes, tmp_path_factory):
    """read(name or shape) -> (PartCad, PartMesh), each test part read once through the real STEP path."""
    cache = {}

    def read_part(shape):
        key = shape if isinstance(shape, str) else id(shape)
        if key not in cache:
            path = tmp_path_factory.mktemp("parts") / "part.step"
            cq.exporters.export(shapes[shape] if isinstance(shape, str) else shape, str(path))
            cache[key] = cad.read_part(path.name, path.read_bytes())
        return cache[key]

    return read_part


@pytest.fixture(scope="module")
def posed(read):
    """posed(name or shape, label) -> (record, table-frame mesh, centre of mass) in the first stable pose with that label
    (or as authored, for label None). The record is PLA, so it has a mass."""

    def pose(shape, label=None):
        measured, mesh = read(shape)
        poses = resting_poses(mesh, measured.centre_of_mass_mm)
        chosen = next(p for p in poses if p.label == label) if label else poses[-1]
        record = PartRecord(
            id="p", created=0, name="part.step", file_path="part.step", source="step", units="mm", measured=measured, material="pla"
        )
        record.pose = chosen
        return (record, *table_mesh(record, mesh))

    return pose


def test_custom_fingers_reach_around_83_mm_on_the_default_cell():
    assert reach_mm(GRIPPER) == pytest.approx(83.0)


def test_the_cube_gives_two_axes_with_parallel_faces(posed):
    _, mesh, com = posed("cube", "standing")

    proposals = propose_grasps(mesh, com, MU, GRIPPER)

    assert [c.angle_deg for c in proposals.candidates] == [0, 90]
    for candidate in proposals.candidates:
        assert candidate.parallel_faces and candidate.opposition_deg == pytest.approx(0, abs=0.1)
        assert candidate.width_mm == pytest.approx(10) and candidate.centre_mm == pytest.approx((0, 0), abs=1e-6)
        assert (candidate.fits, candidate.stock_fits, candidate.verdict, candidate.warnings) == (True, True, "ok", [])
        assert candidate.contact_area_mm2 == pytest.approx(10 * 7.5)  # a 10 x 10 face, above the 2.5 mm the fingertips clear
    assert proposals.nothing_fits is None
    assert any("friction cone" in line for line in proposals.rejected)


def test_the_vial_cap_standing_is_one_candidate_in_any_direction(posed):
    _, mesh, com = posed("vial_cap", "standing on an end")

    proposals = propose_grasps(mesh, com, MU, GRIPPER)

    (candidate,) = proposals.candidates
    assert candidate.note == ROUND_NOTE
    assert candidate.width_mm == pytest.approx(31.75, abs=0.05)
    assert not candidate.parallel_faces and candidate.opposition_deg < 1
    assert (candidate.fits, candidate.stock_fits, candidate.verdict) == (True, False, "ok")
    assert candidate.warnings == [STOCK]


def test_the_vial_cap_lying_is_best_gripped_across_its_flat_ends(posed):
    _, mesh, com = posed("vial_cap", "lying on its side")

    candidates = propose_grasps(mesh, com, MU, GRIPPER).candidates

    ends, side = candidates[0], candidates[1]
    assert (ends.angle_deg, ends.parallel_faces, ends.stock_fits) == (90, True, True)
    assert ends.width_mm == pytest.approx(15.7, abs=0.01)
    assert (side.angle_deg, side.parallel_faces) == (0, False)
    assert side.width_mm == pytest.approx(31.75, abs=0.05)
    assert side.com_offset_mm == pytest.approx(0, abs=1e-6)  # the grip moved along the axis to the centre of mass


def test_the_glass_tube_fits_across_its_axis_and_not_along_it(posed, read):
    record, mesh, com = posed("glass_tube", "lying on its side")

    proposals = propose_grasps(mesh, com, MU, GRIPPER)
    along = check_grasp(mesh, com, MU, GRIPPER, angle_deg=0)

    (across,) = proposals.candidates
    assert across.angle_deg == 90 and across.width_mm == pytest.approx(17, abs=0.05)
    assert across.verdict == "ok" and STOCK in across.warnings
    assert any(line.endswith("these fingers reach around at most 83.0 mm)") for line in proposals.rejected)
    assert along.verdict == "blocked" and not along.fits
    assert along.blocked_reasons == ["140.0 mm across at 0°; these fingers reach around at most 83.0 mm"]
    part = posed_part(record, GraspChoice(angle_deg=across.angle_deg, centre_mm=across.centre_mm), (0.6, 0.5), read("glass_tube")[1])
    assert (part.shape, part.axis) == ("cylinder", "y")
    assert (part.diameter_mm, part.length_mm) == pytest.approx((17, 140), abs=0.05)


def test_the_cup_shaped_cap_is_a_standing_cylinder_with_the_records_mass_and_friction(posed, read):
    record, mesh, com = posed("vial_cap", "standing on an end")
    (candidate,) = propose_grasps(mesh, com, MU, GRIPPER).candidates

    part = posed_part(record, GraspChoice(angle_deg=candidate.angle_deg, centre_mm=candidate.centre_mm), (0.6, 0.5), read("vial_cap")[1])

    assert (part.shape, part.axis, part.round_from_above) == ("cylinder", "z", True)
    assert (part.diameter_mm, part.length_mm) == pytest.approx((31.75, 15.7), abs=0.05)
    assert part.mass_g == pytest.approx(record.measured.volume_mm3 / 1000 * 1.24)
    assert part.friction == (0.5, 0.4)  # PLA against the pad, smooth


def test_a_lying_cap_gripped_by_its_ends_is_a_cylinder_along_the_jaws(posed, read):
    record, mesh, com = posed("vial_cap", "lying on its side")

    part = posed_part(record, GraspChoice(angle_deg=90), (0.6, 0.5), read("vial_cap")[1])

    assert (part.shape, part.axis) == ("cylinder", "x")
    assert part.extent_mm == pytest.approx((15.7, 31.75, 31.75), abs=0.05)


def test_the_cube_is_a_box_and_the_l_bracket_a_mesh_in_the_grasp_frame(posed, read):
    cube = posed_part(posed("cube", "standing")[0], GraspChoice(angle_deg=90), (0.6, 0.5))
    record, mesh, com = posed("l_bracket", "lying flat")
    candidate = next(c for c in propose_grasps(mesh, com, MU, GRIPPER).candidates if c.span_mm is None)  # the whole part

    bracket = posed_part(
        record, GraspChoice(angle_deg=candidate.angle_deg, centre_mm=candidate.centre_mm), (0.6, 0.5), read("l_bracket")[1]
    )

    assert (cube.shape, cube.extent_mm) == ("box", pytest.approx((10, 10, 10)))
    assert bracket.shape == "mesh" and len(bracket.pieces) > 1
    points = np.array([p for piece in bracket.pieces for p in piece.points])
    assert points[:, 2].min() == pytest.approx(0, abs=1e-6)  # resting on the table
    across = np.array([-math.sin(math.radians(candidate.angle_deg)), math.cos(math.radians(candidate.angle_deg))])
    centre = np.array(candidate.centre_mm)
    assert bracket.extent_mm == pytest.approx((candidate.width_mm, candidate.depth_mm, 12), abs=0.01)
    # the grasp centre is the origin: the piece points sit where the table-frame mesh does, relative to it
    assert points[:, 1].min() == pytest.approx((mesh.vertices[:, :2] - centre).dot(across).min(), abs=0.05)


def test_posed_pieces_sit_where_the_table_mesh_puts_the_part(posed, read):
    record, mesh, com = posed("vial_cap", "lying on its side")
    side = next(c for c in propose_grasps(mesh, com, MU, GRIPPER).candidates if c.angle_deg == 0)  # gripped at the CoM, off its middle
    choice = GraspChoice(angle_deg=side.angle_deg, centre_mm=side.centre_mm)

    exact = posed_part(record, choice, (0.6, 0.5), read("vial_cap")[1])
    approximate = posed_part(record, choice, (0.6, 0.5))

    assert exact.shape == "mesh"  # a primitive would be centred on the grasp, and this grip isn't at the cap's middle
    points = np.array([p for piece in exact.pieces for p in piece.points])
    expected = mesh.vertices - [*side.centre_mm, 0]  # angle 0: the grasp frame is the table frame moved to the grasp centre
    assert points.min(axis=0) == pytest.approx(expected.min(axis=0), abs=0.01)
    assert points.max(axis=0) == pytest.approx(expected.max(axis=0), abs=0.01)
    assert points[:, 2].min() >= 0  # never below the table: the sim server rejects a mesh part that is
    rough = np.array([p for piece in approximate.pieces for p in piece.points])
    assert rough.min(axis=0) == pytest.approx(points.min(axis=0), abs=0.3)  # from the pieces' own bounds: close, not exact


def test_posing_needs_a_mass(posed):
    record = posed("cube", "standing")[0].model_copy(update={"material": None})

    with pytest.raises(ValueError, match="no mass"):
        posed_part(record, GraspChoice(angle_deg=0), (0.6, 0.5))


def test_the_wide_plate_lying_flat_fits_nowhere_and_names_its_edge_pose(posed):
    _, mesh, com = posed("wide_plate", "lying flat")

    proposals = propose_grasps(mesh, com, MU, GRIPPER)

    assert proposals.candidates == []
    assert proposals.rejected == ["180 directions too wide (narrowest 120.0 mm at 0°; these fingers reach around at most 83.0 mm)"]
    assert proposals.nothing_fits.reason == "narrowest width 120.0 mm (at 0°); these fingers reach around at most 83.0 mm"
    offset, pose = proposals.nothing_fits.suggestions
    assert offset.startswith("offset fingers: at 0° the part is 120.0 mm across") and "63.5 mm of free space" in offset
    assert pose.startswith('another resting pose: "on its side"') and "4.0 mm across" in pose


def test_a_flanged_post_points_at_the_post_but_gripping_above_the_flange_is_refused(posed):
    part = cq.Workplane("XY").box(100, 100, 3, centered=(True, True, False)).faces(">Z").workplane().rect(20, 20).extrude(30)
    _, mesh, com = posed(part)

    suggestions = propose_grasps(mesh, com, MU, GRIPPER).nothing_fits.suggestions

    feature = next(s for s in suggestions if s.startswith("a narrower feature"))
    assert "z 3-33 mm is 20.0 mm wide" in feature and "doesn't do yet" in feature
    # The V-pad sizes its pads to the whole part, so a grip above the flange would be built around the flange: refused.
    above = check_grasp(mesh, com, MU, GRIPPER, angle_deg=0, grip_height_mm=3.1)
    assert above.verdict == "blocked" and above.width_mm == pytest.approx(20)
    assert any("wider base" in reason for reason in above.blocked_reasons)


def test_a_wide_hollow_cup_suggests_an_internal_grip(posed):
    _, mesh, com = posed(cq.Workplane("XY").circle(50).extrude(30).faces(">Z").workplane().hole(96, 28))

    suggestions = propose_grasps(mesh, com, MU, GRIPPER).nothing_fits.suggestions

    assert [s.split(":")[0] for s in suggestions] == ["offset fingers", "another resting pose", "an internal grip"]
    assert "28.0 mm deep" in suggestions[-1]


def test_a_squat_cone_has_no_face_to_push_on_anywhere(posed):
    _, mesh, com = posed(cq.Workplane("XY").add(cq.Solid.makeCone(30, 0, 15)))

    nothing = propose_grasps(mesh, com, MU, GRIPPER).nothing_fits

    assert "within 26.6° of the closing direction" in nothing.reason
    assert nothing.suggestions == [LAST_RESORT]


def test_a_manual_angle_is_normalised_and_checked(posed):
    _, mesh, com = posed("cube", "standing")

    square = check_grasp(mesh, com, MU, GRIPPER, angle_deg=270)
    corner = check_grasp(mesh, com, MU, GRIPPER, angle_deg=45)

    assert (square.angle_deg, square.verdict, square.parallel_faces) == (90, "ok", True)
    assert corner.verdict == "blocked" and "within 26.6° of the closing direction" in corner.blocked_reasons[0]


def test_one_pick_sets_the_angle_from_its_normal_and_finds_the_face_opposite(posed):
    _, mesh, com = posed("cube", "standing")

    side = check_grasp(mesh, com, MU, GRIPPER, picks=[GraspPick(point=(0, -5, 4), normal=(0, -1, 0))])

    assert (side.angle_deg, side.verdict, side.width_mm) == (90, "ok", pytest.approx(10))
    with pytest.raises(ValueError, match="pick a side face"):
        check_grasp(mesh, com, MU, GRIPPER, picks=[GraspPick(point=(0, 0, 10), normal=(0, 0.2, 0.98))])


def test_two_picks_set_the_angle_from_the_line_between_them(posed):
    _, mesh, com = posed("cube", "standing")

    candidate = check_grasp(
        mesh, com, MU, GRIPPER, picks=[GraspPick(point=(5, 1, 4), normal=(1, 0, 0)), GraspPick(point=(-5, 1, 4), normal=(-1, 0, 0))]
    )

    assert (candidate.angle_deg, candidate.verdict) == (0, "ok")
    assert candidate.centre_mm == pytest.approx((0, 1), abs=1e-6)  # the grip goes through the picks
    assert candidate.com_offset_mm == pytest.approx(1)


def test_with_an_angle_the_picks_only_place_the_grip(posed):
    _, mesh, com = posed("cube", "standing")

    candidate = check_grasp(mesh, com, MU, GRIPPER, angle_deg=0, picks=[GraspPick(point=(5, 1.5, 4), normal=(0.6, 0.8, 0))])

    assert (candidate.angle_deg, candidate.verdict) == (0, "ok")
    assert candidate.centre_mm == pytest.approx((0, 1.5), abs=1e-6)


def test_a_pick_the_jaws_dont_reach_first_is_a_warning(posed):
    # A 30 x 10 x 10 block with a 1 mm recess in its +y side: too shallow to be a section, so the jaws grip the whole part
    recessed = cq.Workplane("XY").box(30, 10, 10).cut(cq.Workplane("XY").box(10, 2, 12).translate((0, 5, 0)))
    _, mesh, com = posed(recessed)

    candidate = check_grasp(mesh, com, MU, GRIPPER, picks=[GraspPick(point=(0, 4, 4), normal=(0, 1, 0))])

    assert candidate.angle_deg == 90 and candidate.span_mm is None and candidate.verdict == "warn"
    assert "the jaws first touch the part 1.0 mm further out than the picked point" in candidate.warnings


def test_a_pick_on_a_narrower_arm_grips_that_arm(posed):
    _, mesh, com = posed("l_bracket")  # as authored: an L lying flat, x -15..15, y -10..10; its inner face is at x = -9

    candidate = check_grasp(mesh, com, MU, GRIPPER, picks=[GraspPick(point=(-9, 3, 6), normal=(1, 0, 0))])

    assert candidate.angle_deg == 0 and candidate.width_mm == pytest.approx(6, abs=0.01)  # the arm, not the bracket's 30 mm
    assert not any("further out" in w for w in candidate.warnings)  # the jaws touch the arm's faces, the picked one too
    assert any("from the centre of mass" in w for w in candidate.warnings)  # held by the arm, away from the corner's mass
    near, far = candidate.span_mm
    assert candidate.centre_mm[1] + near >= -4 - 1e-6 and candidate.centre_mm[1] + far <= 10 + 1e-6  # within the arm


def test_an_off_centre_grip_is_a_warning(posed):
    _, mesh, com = posed("glass_tube", "lying on its side")

    near_the_end = check_grasp(
        mesh,
        com,
        MU,
        GRIPPER,
        picks=[GraspPick(point=(60, 8.5, 8.5), normal=(0, 1, 0)), GraspPick(point=(60, -8.5, 8.5), normal=(0, -1, 0))],
    )

    assert near_the_end.verdict == "warn"
    assert near_the_end.warnings[0].startswith("the grip is 60.0 mm from the centre of mass")


def test_manual_input_that_sets_no_direction_is_refused(posed):
    _, mesh, com = posed("cube", "standing")

    with pytest.raises(ValueError, match="give an angle or one or two face picks"):
        check_grasp(mesh, com, MU, GRIPPER)
    with pytest.raises(ValueError, match="too close together"):
        check_grasp(mesh, com, MU, GRIPPER, picks=[GraspPick(point=(5, 0, 4), normal=(1, 0, 0))] * 2)
    with pytest.raises(ValueError, match="nothing to grip above 12 mm"):
        check_grasp(mesh, com, MU, GRIPPER, angle_deg=0, grip_height_mm=12)


def test_the_table_mesh_rests_on_the_table_with_its_footprint_centred(posed):
    _, mesh, com = posed("l_bracket", "standing")

    lo, hi = mesh.vertices.min(axis=0), mesh.vertices.max(axis=0)

    assert lo[2] == pytest.approx(0) and (lo[:2] + hi[:2]) == pytest.approx((0, 0), abs=1e-9)
    assert hi - lo == pytest.approx((20, 12, 30))
    assert 0 < com[2] < 30


def screw() -> cq.Workplane:
    """An M6 x 30 countersunk screw, simplified: a 6 mm shank under a 12 mm head with a 90 degree countersink."""
    return cq.Workplane("XY").circle(3).extrude(26.7).faces(">Z").workplane().circle(3).workplane(offset=3.3).circle(6).loft()


@pytest.fixture(scope="module")
def lying_screw(posed, read):
    """(record, table-frame mesh, centre of mass, CAD-frame mesh, proposals) for the screw lying on its side."""
    shape = screw()
    record, mesh, com = posed(shape, "lying on its side")
    return record, mesh, com, read(shape)[1], propose_grasps(mesh, com, 0.4, GRIPPER)


def test_a_lying_screw_is_gripped_across_its_shank_clear_of_its_head(lying_screw):
    _, mesh, com, _, proposals = lying_screw

    shank, ends = proposals.candidates[:2]

    assert (shank.angle_deg, shank.verdict, shank.stock_fits) == (90, "ok", True)
    assert shank.width_mm == pytest.approx(6, abs=0.05) and shank.com_offset_mm == pytest.approx(0, abs=1e-6)
    near, far = shank.span_mm
    centre, u, v = np.array(shank.centre_mm), np.array([0.0, 1.0]), np.array([-1.0, 0.0])  # 90 degrees: u is +y, v is -x
    flat = mesh.vertices[:, :2] - centre
    head = flat[np.abs(flat @ u) > 3.2]  # wider than the shank: the head and its countersink
    assert len(head) and np.all((head @ v < near) | (head @ v > far))
    # gripping it end to end, head to tip, is still offered, after the shank
    assert ends.span_mm is None and ends.width_mm == pytest.approx(30.6, abs=0.5) and not ends.stock_fits


def test_a_section_grasp_is_rechecked_on_the_same_section_and_posed_with_its_width(lying_screw):
    record, mesh, com, cad_mesh, proposals = lying_screw
    shank = proposals.candidates[0]

    again = check_grasp(mesh, com, 0.4, GRIPPER, angle_deg=shank.angle_deg, centre_mm=shank.centre_mm, span_mm=shank.span_mm)
    part = posed_part(
        record, GraspChoice(angle_deg=shank.angle_deg, centre_mm=shank.centre_mm, span_mm=shank.span_mm), (0.6, 0.5), cad_mesh
    )

    assert (again.width_mm, again.span_mm, again.verdict) == (shank.width_mm, shank.span_mm, "ok")
    assert again.centre_mm == pytest.approx(shank.centre_mm, abs=1e-3)
    assert part.shape == "mesh" and part.grip_width_mm == pytest.approx(6, abs=0.05) and part.grip_span_mm == shank.span_mm
    assert part.extent_mm[0] == pytest.approx(12, abs=0.1)  # the sim still gets the whole screw, head and all


def test_fingers_for_a_section_are_sized_to_it_and_kept_off_the_head(lying_screw):
    record, _, _, cad_mesh, proposals = lying_screw
    shank = proposals.candidates[0]
    part = posed_part(
        record, GraspChoice(angle_deg=shank.angle_deg, centre_mm=shank.centre_mm, span_mm=shank.span_mm), (0.6, 0.5), cad_mesh
    )
    space = SearchSpace(part, gripper=GRIPPER)
    near, far = shank.span_mm

    centre = space.centre()
    finger = build_finger(part, centre, GRIPPER)
    too_wide = centre.model_copy(update={"params": centre.params.model_copy(update={"pad_width_mm": 2 * min(-near, far) + 4})})

    assert space.bounds()["pad_width_mm"][1] <= 2 * min(-near, far) + 1e-9
    assert problems(part, finger, GRIPPER) == []
    # closed on the 6 mm shank: the pad face sits slack_mm off it with the jaws open
    assert finger.jaw_close_mm == pytest.approx(GRIPPER.stroke_mm - centre.params.slack_mm - SQUEEZE_MM, abs=0.05)
    assert "the pads would reach the wider part beside the grip" in problems(part, build_finger(part, too_wide, GRIPPER), GRIPPER)
    held = MockSim().run_batch(part, [finger, None], [{"dx": 0.0, "dy": 0.0, "yaw_deg": 0.0}], SimSettings())
    assert [outcome.held for outcome in held] == [[True], [True]]
