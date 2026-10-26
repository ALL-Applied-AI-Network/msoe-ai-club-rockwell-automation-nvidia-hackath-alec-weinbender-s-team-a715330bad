import cadquery as cq
import pytest

from api.db.tables import CellProfileRow
from api.models.cell_profile import DEFAULT_PROFILE
from api.models.design import Design
from api.models.family import FamilyChoice, ParamRange, VPadParams
from api.models.finger import stock_blade
from api.models.part import Part
from api.models.piece import pieces_bounds
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


# The finger library


def test_every_cell_gets_its_stock_fingers_once(db, profile_id):
    fingers.ensure_stock_fingers(db)
    fingers.ensure_stock_fingers(db)

    (stock,) = [r for r, _ in fingers.list_fingers(db)]
    assert stock.source == stock.family == "stock" and stock.code == "FNG-0001" and stock.cell_profile_name == "UWM CSI cell"
    assert stock.pad_friction == (1.5, 1.3)  # the real fingers' soft tips, which the twin runs them with
    assert (stock.name, stock.extent_mm) == ("Stock fingers", (12.0, 6.0, 76.0))


def test_an_uploaded_finger_is_placed_in_the_gripper_frame(db, config, cad, profile_id, step_file):
    # authored mirrored and upside down: the gripping face toward +x, the fingertips up
    shape = cq.Workplane("XY").box(12, 6, 76).translate((-20, 5, 100))
    content = step_file(shape, "finger.step")

    placed = fingers.create_finger(db, config, cad, "finger.step", content, cell_profile_id=profile_id, mirror=True, upside_down=True)

    lo, hi = pieces_bounds(placed.pieces)
    assert lo == pytest.approx([0, -3, 0], abs=1e-6) and hi == pytest.approx([12, 3, 76], abs=1e-6)
    assert placed.extent_mm == pytest.approx((12, 6, 76)) and placed.source == "uploaded" and placed.name == "finger"
    assert placed.pad_friction == DEFAULT_PROFILE.pad_friction and fingers.PLACEMENT_NOTE in placed.warnings
    assert placed.file_path.endswith("finger.step")


def test_a_finger_reaching_past_the_free_space_is_stored_with_a_warning(db, config, cad, profile_id, step_file):
    content = step_file(cq.Workplane("XY").box(12, 80, 76), "wide.step")

    placed = fingers.create_finger(db, config, cad, "wide.step", content, cell_profile_id=profile_id)

    assert any("more than the 45 x 30 mm" in w for w in placed.warnings)


def test_an_upload_the_library_cant_take_says_why(db, config, cad, profile_id, step_file, stl_file):
    with pytest.raises(fingers.FingerInputError, match="units required"):
        fingers.create_finger(db, config, cad, "f.stl", stl_file(cq.Workplane("XY").box(5, 5, 5)), cell_profile_id=profile_id)
    with pytest.raises(fingers.UnsupportedFingerFormatError):
        fingers.create_finger(db, config, cad, "f.sldprt", b"solidworks", cell_profile_id=profile_id)
    with pytest.raises(fingers.FingerInputError, match="not a readable STEP"):
        fingers.create_finger(db, config, cad, "f.step", b"not a step file", cell_profile_id=profile_id)
    with pytest.raises(fingers.FingerInputError, match="stock fingers are added by the app"):
        fingers.create_finger(
            db, config, cad, "f.step", step_file(cq.Workplane("XY").box(5, 5, 5)), cell_profile_id=profile_id, family="stock"
        )
    with pytest.raises(CellProfileNotFoundError):
        fingers.create_finger(db, config, cad, "f.step", step_file(cq.Workplane("XY").box(5, 5, 5)), cell_profile_id=999)


def test_a_generation_jobs_design_joins_the_library_once(isaac_job):
    added = fingers.add_from_job(isaac_job.db, isaac_job.job_id, "d1")

    assert added.source == "generated" and added.family == "vpad" and added.origin_label == "D1"
    assert added.origin_job_id == isaac_job.job_id and added.origin_sim_backend == "isaac" and added.design.kind in ("search", "locked")
    assert added.built_for is not None and added.name.startswith("EXP-")
    with pytest.raises(fingers.FingerConflictError, match="in the library already"):
        fingers.add_from_job(isaac_job.db, isaac_job.job_id, "d1")
    with pytest.raises(fingers.FingerConflictError, match="stock fingers"):
        fingers.add_from_job(isaac_job.db, isaac_job.job_id, "stock")
    imprint = fingers.add_from_job(isaac_job.db, isaac_job.job_id, "IMP", name="  Cap   imprint ")
    assert imprint.family == "imprint" and imprint.name == "Cap imprint"
    _, geometry = fingers.finger_geometry(isaac_job.db, imprint.id)
    assert geometry is not None and geometry.pieces


def test_the_library_lists_where_each_finger_has_been_tried(evaluated):
    listed = {r.id: stats for r, stats in fingers.list_fingers(evaluated.db)}

    assert set(listed) == {evaluated.stock_id, evaluated.generated_id, evaluated.uploaded_id}
    assert all(s.parts_evaluated == 1 and s.best_success is not None and s.validated_parts == 0 for s in listed.values())
    assert [r.id for r, _ in fingers.list_fingers(evaluated.db, source="uploaded")] == [evaluated.uploaded_id]
    assert [r.id for r, _ in fingers.list_fingers(evaluated.db, family="vpad")] == [evaluated.generated_id]
    assert len(fingers.list_fingers(evaluated.db, part_id=evaluated.part_id)) == 3
    assert fingers.list_fingers(evaluated.db, part_id="other") == []
    best = max(s.best_success for s in listed.values())
    assert [r.id for r, s in fingers.list_fingers(evaluated.db, min_success=best)] == [
        fid for fid, s in listed.items() if s.best_success == best
    ]
    assert fingers.list_fingers(evaluated.db, cell_profile_name="uwm csi CELL") != []


def test_editing_a_finger_changes_only_what_was_sent(evaluated_copy):
    e = evaluated_copy

    edited = fingers.update_finger(e.db, e.uploaded_id, {"name": "  Flat   blade ", "quantity_on_hand": 4, "archived": True})

    assert (edited.name, edited.quantity_on_hand, edited.archived) == ("Flat blade", 4, True)
    assert fingers.get_finger(e.db, e.uploaded_id).pieces == edited.pieces
    assert e.uploaded_id not in {r.id for r, _ in fingers.list_fingers(e.db)}
    assert e.uploaded_id in {r.id for r, _ in fingers.list_fingers(e.db, archived=True)}
    with pytest.raises(fingers.FingerInputError, match="can't change pieces"):
        fingers.update_finger(e.db, e.uploaded_id, {"pieces": []})
    with pytest.raises(fingers.FingerInputError, match="needs a name"):
        fingers.update_finger(e.db, e.uploaded_id, {"name": " "})
    with pytest.raises(fingers.FingerInputError, match="only the cell's own"):
        fingers.update_finger(e.db, e.uploaded_id, {"family": "stock"})
    with pytest.raises(fingers.FingerNotFoundError):
        fingers.update_finger(e.db, "nope", {"notes": "x"})


def test_the_stock_fingers_show_the_twins_model_of_the_real_blades(evaluated):
    record, geometry = fingers.finger_geometry(evaluated.db, evaluated.stock_id)

    assert record.source == "stock" and geometry.pieces == stock_blade(fingers.cell_profile_for(evaluated.db, record).profile.gripper)
    assert geometry.jaw_close_mm == 0 and geometry.friction == record.pad_friction


def test_the_stock_fingers_cant_be_archived(evaluated_copy):
    e = evaluated_copy
    with pytest.raises(fingers.FingerInputError, match="stay in the library"):
        fingers.update_finger(e.db, e.stock_id, {"archived": True})
    assert fingers.update_finger(e.db, e.stock_id, {"notes": "on both arms"}).notes == "on both arms"
