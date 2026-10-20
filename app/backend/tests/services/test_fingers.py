import pytest

from api.db.tables import CellProfileRow
from api.models.cell_profile import DEFAULT_PROFILE
from api.models.design import Design
from api.models.family import FamilyChoice, ParamRange, VPadParams
from api.models.part import Part
from api.services import fingers
from api.services.cell_profiles import CellProfileNotFoundError

CAP, CUBE = Part(), Part(shape="box")


def test_varying_one_parameter_previews_its_two_ends_with_the_rest_in_the_middle(db, profile_id):
    preview = fingers.preview_fingers(db, CAP, profile_id, FamilyChoice(), vary="slack_mm")

    low, high = preview.designs
    assert (low.label, high.label) == ("min", "max")
    assert low.design.params.slack_mm < high.design.params.slack_mm
    others = {"slack_mm", "family"}
    assert low.design.params.model_dump(exclude=others) == high.design.params.model_dump(exclude=others)
    assert low.problems == high.problems == []
    assert low.finger.closed_gap_mm < high.finger.closed_gap_mm, "more slack sets the pads further apart"
    assert preview.free == ["pad_width_mm", "groove_angle_deg", "groove_depth_mm", "slack_mm", "tip_height_mm", "lead_in_mm"]
    assert [p.name for p in preview.params] == preview.free


def test_the_ends_follow_the_users_range(db, profile_id):
    choice = FamilyChoice(ranges={"pad_width_mm": ParamRange(lo=15, hi=16)})

    low, high = fingers.preview_fingers(db, CAP, profile_id, choice, vary="pad_width_mm").designs

    assert (low.design.params.pad_width_mm, high.design.params.pad_width_mm) == (15, 16)


def test_given_designs_are_previewed_in_order_baselines_included(db, profile_id):
    designs = [Design(kind="stock"), Design(kind="imprint"), Design(params=VPadParams(pad_width_mm=9, slack_mm=2, tip_height_mm=3))]

    preview = fingers.preview_fingers(db, CUBE, profile_id, FamilyChoice(), designs=designs)

    assert [d.label for d in preview.designs] == ["0", "1", "2"]
    assert [d.design for d in preview.designs] == designs
    assert all(d.finger is not None and d.problems == [] for d in preview.designs)
    assert preview.designs[0].finger.closed_gap_mm == 0


def test_without_vary_or_designs_the_middle_design_is_shown(db, profile_id):
    (centre,) = fingers.preview_fingers(db, CUBE, profile_id, FamilyChoice()).designs

    assert centre.label == "centre" and centre.design.kind == "search" and centre.problems == []


def test_a_design_outside_the_clearance_reports_it(db, profile_id):
    wide = Design(params=VPadParams(pad_width_mm=30, slack_mm=2, tip_height_mm=3))

    (preview,) = fingers.preview_fingers(db, CUBE, profile_id, FamilyChoice(), clearance_mm=4, designs=[wide]).designs

    assert preview.problems == ["the finger needs 10.0 mm beside the part, and the part has 4 mm of clearance"]


def test_the_geometry_comes_from_the_cell_profiles_gripper(db, profile_id):
    with db.session() as s:
        row = CellProfileRow(name="long stroke", version=1, profile=DEFAULT_PROFILE.model_copy(update={"stroke_per_jaw_mm": 10.0}))
        s.add(row)
        s.flush()
        long_id = row.id
    design = [Design(params=VPadParams(pad_width_mm=20, slack_mm=3, tip_height_mm=4))]

    (default,) = fingers.preview_fingers(db, CAP, profile_id, FamilyChoice(), designs=design).designs
    (longer,) = fingers.preview_fingers(db, CAP, long_id, FamilyChoice(), designs=design).designs

    assert longer.finger.jaw_open_mm == 10
    assert longer.finger.closed_gap_mm == pytest.approx(default.finger.closed_gap_mm - 8)


@pytest.mark.parametrize(
    "choice, vary, why",
    [
        (FamilyChoice(locks={"slack_mm": 2}), "slack_mm", "it's locked"),
        (FamilyChoice(), "groove_depth_mm", "it doesn't apply to this part"),
        (FamilyChoice(), "colour", "V-pad has no such parameter"),
    ],
)
def test_only_a_free_parameter_can_be_varied(db, profile_id, choice, vary, why):
    with pytest.raises(fingers.PreviewError, match=why):
        fingers.preview_fingers(db, CUBE, profile_id, choice, vary=vary)


def test_an_unknown_profile_is_not_found(db):
    with pytest.raises(CellProfileNotFoundError):
        fingers.preview_fingers(db, CAP, 999, FamilyChoice())


def test_a_grip_height_locks_the_previews_tip_height_as_the_plan_does(db, profile_id):
    preview = fingers.preview_fingers(db, Part(), profile_id, FamilyChoice(), grip_height_mm=4.0)

    assert "tip_height_mm" not in preview.free
    assert all(d.design.params.tip_height_mm == pytest.approx(4.0) for d in preview.designs)
