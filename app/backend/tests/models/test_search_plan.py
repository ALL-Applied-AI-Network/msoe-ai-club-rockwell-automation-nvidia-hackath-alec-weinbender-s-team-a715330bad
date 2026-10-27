import pytest

from api.models.cell_profile import DEFAULT_PROFILE, CellProfile, CellSimSettings
from api.models.error_model import ErrorModel
from api.models.family import FamilyChoice, ParamRange
from api.models.grasp import GraspChoice
from api.models.job_pose import JobPose
from api.models.job_spec import JobSpec
from api.models.part import Part
from api.models.piece import hull_piece
from api.models.search_plan import BASELINES, FINALISTS, SearchConfig, TimeEstimate, plan_job

CAP, BOX = Part(), Part(shape="box")
UNKNOWN = TimeEstimate(seconds=None, grasps_per_s=None, source="unknown")


def spec(**changes) -> JobSpec:
    return JobSpec(**{"part_id": "part", "cell_profile_id": 1, "grasp": GraspChoice(angle_deg=0), **changes})


def plan(part: Part = CAP, job: JobSpec | None = None, profile: CellProfile = DEFAULT_PROFILE, **kwargs):
    return plan_job(
        part, job or spec(), profile, sim_backend=kwargs.pop("sim_backend", "isaac"), estimate=kwargs.pop("estimate", UNKNOWN), **kwargs
    )


def test_an_upright_cylinder_searches_six_parameters_with_batch_bo_on_81_offsets():
    result = plan(CAP)
    (search,) = result.searches

    assert (search.key, search.method, len(search.free)) == ("vpad", "bo", 6)
    assert (search.budget, search.n_initial, search.batch_size, search.patience) == (128, 2 * 6 + 4, 8, 18)
    assert result.grid.yaws_deg == [0] and result.baselines == list(BASELINES)
    totals = result.totals
    assert (totals.search_offsets, totals.final_offsets) == (81, 321)
    assert (totals.search_designs, totals.search_grasps) == (128 + 2, 130 * 81)
    assert (totals.final_designs, totals.final_grasps) == (FINALISTS + 2, 5 * 321)
    assert totals.rounds == 1 + (128 - 16) // 8 + 1
    assert totals.total_grasps == 130 * 81 + 5 * 321
    assert result.blocked == []


def test_a_box_is_tested_at_three_yaws_so_its_batches_are_smaller():
    result = plan(BOX)
    (search,) = result.searches

    assert result.grid.yaws_deg == [-12, 0, 12]
    assert (result.totals.search_offsets, result.totals.final_offsets) == (243, 963)
    assert (len(search.free), search.n_initial, search.batch_size) == (4, 12, 4), "10 x 64 envs / 243 offsets rounds below 4"
    assert result.totals.search_grasps == 130 * 243
    assert result.totals.rounds == 1 + (128 - 12) // 4 + 1


def test_more_environments_mean_bigger_batches_but_at_least_four_learning_rounds():
    big = DEFAULT_PROFILE.model_copy(update={"sim": CellSimSettings(envs=1024)})

    (search,) = plan(CAP, profile=big).searches

    assert search.batch_size == (128 - 16) // 4


def test_locking_every_parameter_plans_a_single_design():
    locks = {"pad_width_mm": 9, "slack_mm": 2, "tip_height_mm": 3, "lead_in_mm": 1}
    result = plan(BOX, spec(families=[FamilyChoice(locks=locks)]))
    (search,) = result.searches

    assert (search.method, search.budget, search.n_initial, search.free) == ("single", 1, 1, [])
    assert search.space(BOX).locked_design().params.slack_mm == 2
    assert (result.totals.search_designs, result.totals.final_designs, result.totals.rounds) == (3, 3, 2)


@pytest.mark.parametrize("free, budget", [(1, 16), (2, 32)])
def test_one_or_two_free_parameters_are_swept_with_sobol(free, budget):
    names = ["pad_width_mm", "slack_mm", "tip_height_mm", "lead_in_mm"]
    locks = {name: v for name, v in zip(names[free:], (2.0, 3.0, 1.0), strict=False)}
    (search,) = plan(BOX, spec(families=[FamilyChoice(locks=locks)])).searches

    assert (search.method, search.budget, search.n_initial, search.batch_size) == ("sobol", budget, budget, budget)
    assert len(search.free) == free


def test_the_users_budget_replaces_the_rule():
    (search,) = plan(CAP, spec(budget=40)).searches

    assert (search.budget, search.n_initial, search.batch_size) == (40, 16, (40 - 16) // 4)


def test_the_grasps_grip_height_locks_the_tip_height():
    job = spec(grasp=GraspChoice(angle_deg=0, grip_height_mm=5), families=[FamilyChoice(ranges={"tip_height_mm": ParamRange(lo=1, hi=2)})])
    result = plan(CAP, job)
    (search,) = result.searches

    assert "tip_height_mm" not in search.free and search.locked == {"tip_height_mm": 5}
    assert search.n_initial == 2 * 5 + 4
    tip = {p.name: p for p in result.families[0].params}["tip_height_mm"]
    assert (tip.locked, tip.effective_range) == (5, (5, 5))
    assert search.space(CAP).from_unit([0.5] * 5).params.tip_height_mm == 5


def test_the_time_estimate_divides_the_grasps_by_the_throughput():
    result = plan(CAP, estimate=TimeEstimate(seconds=None, grasps_per_s=50, source="measured"))

    assert result.estimate.seconds == pytest.approx(result.totals.total_grasps / 50)
    assert result.estimate.source == "measured"
    assert plan(CAP).estimate.seconds is None


def test_warnings_cover_the_cell_the_preset_the_stock_fingers_and_the_bias():
    profile = DEFAULT_PROFILE.model_copy(update={"stroke_per_jaw_mm": 8.0})
    job = spec(error=ErrorModel(preset="typical", sigma_mm=5, bias_mm=3))

    warnings = plan(CAP, job, profile, sim_backend="mock").warnings

    assert "cell profile vs the sim: stroke_per_jaw_mm: this profile has 8 mm, the sim's twin 6 mm" in warnings
    assert "mock sim: geometry only, so its success rates are not predictions" in warnings
    assert "the 'Typical' error preset (3 mm, 8 deg) is a placeholder until measured on the cell" in warnings
    assert "the stock fingers open to 16 mm at the tips and the part is 31.8 mm wide: the stock baseline will score 0" in warnings
    assert "bias + 2σ (13.0 mm) reaches past the 12 mm outer ring: errors beyond the grid count as misses" in warnings


def test_a_plain_job_on_a_small_part_warns_about_nothing_but_its_preset():
    job = spec(error=ErrorModel.from_preset("twin"))

    assert plan(BOX, job).warnings == []


def test_clipped_ranges_and_mesh_parts_are_warned_about():
    mesh = Part(shape="mesh", pieces=[hull_piece([(x, y, z) for x in (-5, 5) for y in (-4, 4) for z in (0, 8)])])
    job = spec(families=[FamilyChoice(ranges={"slack_mm": ParamRange(lo=1, hi=20)})])

    result = plan(mesh, job)

    assert "the part is simulated as 1 convex pieces, an approximation of its shape" in result.warnings
    assert "V-pad: slack clipped to 5.5 mm: the stroke leaves no more" in result.warnings
    assert result.families[0].warnings == ["V-pad: slack clipped to 5.5 mm: the stroke leaves no more"]


def test_a_part_no_finger_can_grip_blocks_the_job_but_is_still_planned():
    wide = Part(shape="box", width_mm=90, depth_mm=10, height_mm=10)

    result = plan(wide)

    assert result.blocked == [
        "V-pad: no buildable design for this part: the finger reaches outside the space the gripper and its camera leave free"
    ]
    assert result.totals.search_designs == 130


def test_too_little_clearance_blocks_the_job():
    result = plan(BOX, clearance_mm=2.0)

    assert result.blocked and all(reason.startswith("V-pad: no buildable design for this part: ") for reason in result.blocked)
    assert result.searches[0].clearance_mm == 2.0
    assert plan(BOX, clearance_mm=8.0).blocked == []


def test_one_pose_plans_as_a_spec_with_one_grasp_did():
    alone = plan(BOX, poses=[JobPose(key="p0", label="standing", probability=1.0, grasp=GraspChoice(angle_deg=0), part=BOX)])

    legacy = plan(BOX)

    assert alone.model_dump(exclude={"poses"}) == legacy.model_dump(exclude={"poses"})
    assert [p.key for p in legacy.poses] == ["p0"] and alone.totals.poses == 1


def test_every_pose_multiplies_the_grasps_and_says_what_it_assumes():
    standing = Part(shape="box", height_mm=20)
    poses = [
        JobPose(key="p0", label="on its side", probability=0.6, weight=0.75, grasp=GraspChoice(angle_deg=0), part=BOX),
        JobPose(key="p1", label="standing", probability=0.2, weight=0.25, grasp=GraspChoice(angle_deg=0), part=standing),
    ]

    two, one = plan(BOX, poses=poses), plan(BOX)

    assert two.totals.poses == 2 and two.totals.total_grasps == 2 * one.totals.total_grasps
    assert (two.totals.search_grasps, two.totals.final_grasps) == (2 * one.totals.search_grasps, 2 * one.totals.final_grasps)
    assert (two.searches, two.grid, two.totals.rounds) == (one.searches, one.grid, one.totals.rounds)  # searched in the primary
    assert any("2 resting poses (on its side (75%), standing (25%))" in w for w in two.warnings)
    assert any("cover 80% of how the part comes to rest" in w for w in two.warnings)


def test_a_pose_the_middle_design_cant_grip_is_a_warning_not_a_blocker():
    wide = Part(shape="box", width_mm=40)  # far wider than the cube the fingers are built for: the pads land on it
    poses = [
        JobPose(key="p0", label="standing", probability=0.7, weight=0.7, grasp=GraspChoice(angle_deg=0), part=BOX),
        JobPose(key="p1", label="lying flat", probability=0.3, weight=0.3, grasp=GraspChoice(angle_deg=0), part=wide),
    ]

    result = plan(BOX, poses=poses)

    assert result.blocked == []
    assert any(w.startswith("V-pad, lying flat: the middle design can't grip this pose") for w in result.warnings)


def bo_search(**changes) -> SearchConfig:
    config = {"key": "vpad", "family": "vpad", "free": ["slack_mm"], "locked": {}, "ranges": {}, "method": "bo"}
    return SearchConfig(**config | {"n_initial": 12, "budget": 128, "batch_size": 4, "patience": 12} | changes)


def test_an_early_best_in_the_sobol_start_doesnt_use_up_the_patience():
    """EXP-0001 on the screw: the 3rd of 12 Sobol designs was the best and no BO design beat it. Counting the start as
    stale stopped the search after its first batch (16 designs); now BO gets `patience` designs of its own."""
    start = [0.1, 0.1, 0.851] + [0.5] * 9
    search = bo_search()
    assert search.stop_reason(start + [0.84] * 4) is None
    assert search.stop_reason(start + [0.84] * 11) is None
    assert search.stop_reason(start + [0.84] * 12) == "patience"


def test_a_bo_design_that_gains_resets_the_patience_and_one_that_gains_too_little_doesnt():
    search = bo_search()
    start = [0.5] * 12
    assert search.stop_reason(start + [0.5] * 11 + [0.6] + [0.6] * 11) is None  # 0.6 beat 0.5: 11 stale since
    assert search.stop_reason(start + [0.5] * 11 + [0.6] + [0.6] * 12) == "patience"
    assert search.stop_reason(start + [0.503] * 12) == "patience"  # under MIN_GAIN: no gain


def test_a_search_stops_on_its_budget_or_not_at_all_during_the_start():
    assert bo_search(budget=20).stop_reason([0.5] * 20) == "budget"
    assert bo_search().stop_reason([0.5] * 12) is None
    assert bo_search(method="sobol", n_initial=16, budget=16, batch_size=16).stop_reason([0.5] * 10) is None
