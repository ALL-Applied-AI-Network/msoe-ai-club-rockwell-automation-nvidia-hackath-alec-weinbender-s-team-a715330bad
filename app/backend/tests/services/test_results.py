from pathlib import Path

import pytest
from sqlalchemy import func, select

from api.clients.sim import MockSim
from api.db.tables import ResultRow, TrialRow
from api.models.error_model import ErrorModel
from api.models.family import FamilyChoice
from api.models.grasp import GraspChoice
from api.models.job_spec import JobSpec
from api.models.results import grasp_pose_text
from api.models.task import Task
from api.services import cell_profiles, jobs, optimizer, parts, results

CUBE_LOCKS = {"pad_width_mm": 12.0, "slack_mm": 2.0, "tip_height_mm": 3.0, "lead_in_mm": 0.0}


@pytest.fixture
def cube_spec(db, config, cad, shapes, step_file, profile_id):
    """cube_spec(**changes) -> a spec for a 10 mm PLA cube standing on the table, with one locked V-pad design."""
    record = parts.create_part(db, config, cad, "cube.step", step_file(shapes["cube"], "cube.step"), None)
    parts.update_part(db, record.id, {"material": "pla", "pose": 0})

    def create(**changes):
        values = {"part_id": record.id, "cell_profile_id": profile_id, "grasp": GraspChoice(angle_deg=0)}
        return JobSpec(**values | {"families": [FamilyChoice(locks=CUBE_LOCKS)]} | changes)

    return create


def test_the_results_view_has_every_section(finished_job):
    db, job_id = finished_job.db, finished_job.job_id

    view = results.results(db, job_id)

    header = view.header
    assert (header.experiment_id, header.status, header.sim_backend, header.part_name) == ("EXP-0001", "done", "mock", "vial_cap.step")
    assert (header.cell_profile_name, header.cell_profile_version, header.rescored) == ("UWM CSI cell", 1, False)
    summary = view.summary
    assert (summary.best.label, summary.stock.label, summary.imprint.label, summary.leader) == ("D1", "STOCK", "IMP", "D1")
    assert summary.stock.success == 0 and summary.gain_vs_stock == summary.best.success  # the cap is wider than the stock tips
    assert summary.designs_evaluated == 18 and summary.task_metric_label is None and summary.best.task_metric is None
    with db.session() as s:
        stored = s.get(ResultRow, job_id)
        assert summary.best.success == stored.predicted_success
    assert [row.label for row in view.final_table] == ["D1", "D2", "D3", "STOCK", "IMP"]
    assert not any(row.print_selected for row in view.final_table)
    assert view.curves.target_sigma_mm == 3.0 and [c.label for c in view.curves.designs] == ["D1", "D2", "D3", "STOCK", "IMP"]
    assert all(list(c.success) == ["0.5", "1", "2", "3", "4", "5"] for c in view.curves.designs)
    assert [m.label for m in view.held_maps] == ["D1", "STOCK"] and all(len(m.points) == 321 for m in view.held_maps)
    assert not any(p.held for p in view.held_maps[1].points)
    in_hand = view.in_hand
    assert in_hand.label == "D1" and in_hand.n_held == sum(p.held for p in view.held_maps[0].points) == len(in_hand.offsets_mm)
    failures = view.failures
    assert sum(g.points for g in failures.by_direction) == 320 and [g.direction for g in failures.by_direction][:3] == ["+x", "+x+y", "+y"]
    assert any(c.startswith("mock sim") for c in failures.caveats) and any("placeholder" in c for c in failures.caveats)
    best = view.best_finger
    assert best.files == ["step", "stl_left", "stl_right", "print_sheet"] and not best.download_blocked
    assert "grasp_angle_deg: 0" in best.grasp_pose_text and best.grasp_pose["grasp_angle_deg"] == 0
    assert view.physical.badge == "none"
    search = view.run.searches[0]
    assert (search.key, search.method, search.designs_evaluated, search.rounds, search.stop_reason) == ("vpad", "bo", 18, 3, "budget")
    assert search.best_so_far == sorted(search.best_so_far) and len(search.best_so_far) == 18
    assert view.run.versions["python"] and view.run.seed == 0 and view.run.error == ErrorModel()


def test_a_rescore_changes_the_numbers_and_stores_nothing(finished_job):
    db, job_id = finished_job.db, finished_job.job_id
    with db.session() as s:
        stored = s.scalar(select(func.count()).select_from(TrialRow).where(TrialRow.job_id == job_id))
    base = results.results(db, job_id)

    tighter = results.results(db, job_id, error=ErrorModel.from_preset("calibrated"))
    place = results.results(db, job_id, task=Task(kind="place", offset_tolerance_mm=0.5))

    def numbers(view):
        return [(row.label, row.success) for row in view.final_table]

    assert tighter.header.rescored and place.header.rescored and tighter.curves.target_sigma_mm == 1.0
    assert numbers(tighter) != numbers(base) and numbers(place) != numbers(base)
    assert place.summary.task_metric_label == "held grasps within 0.5 mm" and place.summary.best.task_metric is not None
    assert place.in_hand.offset_tolerance_mm == 0.5
    assert results.results(db, job_id) == base
    with db.session() as s:
        assert s.scalar(select(func.count()).select_from(TrialRow).where(TrialRow.job_id == job_id)) == stored


def test_a_transport_rescore_of_a_run_without_one_says_it_isnt_checked(finished_job):
    view = results.results(finished_job.db, finished_job.job_id, task=Task(transport="fast"))

    assert any("transport" in c for c in view.failures.caveats)


def test_other_designs_are_exported_on_demand_and_cached(finished_job, cad, monkeypatch):
    db, config, job_id = finished_job.db, finished_job.config, finished_job.job_id
    job = jobs.get_job(db, job_id)

    export = results.design_export(db, job_id, "d2", cad=cad, outputs_dir=config.outputs_dir)

    assert export.label == "D2" and not export.blocked and sorted(export.files) == ["print_sheet", "step", "stl_left", "stl_right"]
    assert all(Path(p).parent == config.outputs_dir / job_id / "D2" for p in export.files.values())
    monkeypatch.setattr(cad, "export", lambda *args, **kwargs: pytest.fail("exported again instead of using the cache"))
    assert results.design_export(db, job_id, "D2", cad=cad, outputs_dir=config.outputs_dir) == export
    path, name = results.design_file(db, job_id, "D2", "stl_right", cad=cad, outputs_dir=config.outputs_dir)
    assert path.exists() and name == f"{job.name}_EXP-0001_D2_MOCK_R.stl"
    with db.session() as s:
        stored = s.get(ResultRow, job_id).cad_files
    assert results.design_export(db, job_id, "D1", cad=cad, outputs_dir=config.outputs_dir).files == stored


def test_the_stock_fingers_and_unknown_labels_cant_be_exported(finished_job, cad):
    db, config, job_id = finished_job.db, finished_job.config, finished_job.job_id

    with pytest.raises(results.DesignNotExportableError, match="already on the robot"):
        results.design_export(db, job_id, "STOCK", cad=cad, outputs_dir=config.outputs_dir)
    with pytest.raises(results.DesignNotFoundError, match="D1, D2, D3, STOCK, IMP"):
        results.design_export(db, job_id, "D9", cad=cad, outputs_dir=config.outputs_dir)


def test_grasp_poses_and_the_finger_preview(finished_job):
    db, job_id = finished_job.db, finished_job.job_id

    with db.session() as s:
        stored = s.get(ResultRow, job_id).grasp_pose
    assert results.grasp_pose(db, job_id, "D1") == stored
    other = results.grasp_pose(db, job_id, "D3")
    assert other["grasp_angle_deg"] == 0 and other["tip_height_mm"] > 0
    stock = results.grasp_pose(db, job_id, "STOCK")
    assert (stock["tip_height_mm"], stock["jaw_close_mm"]) == (2.5, 6.0)  # the sim's stock grasp; the 31.75 mm cap clamps the jaws open
    preview = results.finger_preview(db, job_id, "D1")
    assert preview.label == "D1" and preview.jaw_open_mm == 6.0 and preview.part.shape == "cylinder"
    left, right = preview.finger.pieces[0], preview.right[0]
    assert [(-x, y, z) for x, y, z in left.points] == right.points and right.triangles[0] == (
        left.triangles[0][0],
        left.triangles[0][2],
        left.triangles[0][1],
    )


def test_a_job_without_a_final_test_has_no_designs_yet(db, config, cube_spec, spawned, cad):
    job = jobs.create_job(db, config, cube_spec())

    view = results.results(db, job.id)

    assert view.summary is None and view.final_table == [] and view.best_finger is None and view.held_maps == []
    assert view.run.searches[0].designs_evaluated == 0 and view.run.searches[0].stop_reason is None
    with pytest.raises(results.ResultsNotReadyError):
        results.design_export(db, job.id, "D1", cad=cad, outputs_dir=config.outputs_dir)
    with pytest.raises(results.ResultsNotReadyError):
        results.run_metadata(db, job.id)
    with pytest.raises(jobs.JobNotFoundError):
        results.results(db, "nope")


def test_a_failed_blocking_check_blocks_the_download(db, config, cad, cube_spec, profile_id, spawned):
    cell = cell_profiles.get_profile(db, profile_id).profile.model_copy(update={"max_finger_length_mm": 50.0})
    short = cell_profiles.create_profile(db, "short fingers", cell)
    job = jobs.create_job(db, config, cube_spec(cell_profile_id=short.id))
    optimizer.run_job(db, job.id, sim=MockSim(), cad=cad, outputs_dir=config.outputs_dir)

    assert results.results(db, job.id).best_finger.download_blocked
    with pytest.raises(results.ExportBlockedError) as raised:
        results.design_file(db, job.id, "D1", "step", cad=cad, outputs_dir=config.outputs_dir)
    assert [c.name for c in raised.value.checks] == ["finger length"] and "50 mm" in raised.value.checks[0].detail
    assert [c.name for c in results.design_export(db, job.id, "IMP", cad=cad, outputs_dir=config.outputs_dir).blocked] == ["finger length"]


def test_a_job_over_one_pose_has_no_per_pose_scores(finished_job):
    view = results.results(finished_job.db, finished_job.job_id)

    assert view.summary.best.poses is None and all(row.poses is None for row in view.final_table)
    assert [(m.label, m.pose) for m in view.held_maps] == [("D1", None), ("STOCK", None)]


def test_a_job_over_two_poses_scores_each_design_in_each(two_pose_job):
    db, job_id = two_pose_job.db, two_pose_job.job_id

    view = results.results(db, job_id)
    rescored = results.results(db, job_id, error=ErrorModel(sigma_mm=1))

    best = view.summary.best
    assert [(p.key, p.label) for p in best.poses] == [("p0", "on its side"), ("p1", "standing")]
    assert best.success == pytest.approx(sum(p.weight * p.success for p in best.poses))
    assert best.capture_radius_mm == min(p.capture_radius_mm for p in best.poses)
    assert all(len(row.poses) == 2 for row in view.final_table)
    assert [(m.label, m.pose, m.pose_label) for m in view.held_maps] == [
        ("D1", "p0", "on its side"),
        ("D1", "p1", "standing"),
        ("STOCK", "p0", "on its side"),
        ("STOCK", "p1", "standing"),
    ]
    d1 = next(curve for curve in view.curves.designs if curve.label == "D1")
    assert d1.success["3"] == pytest.approx(best.success)  # the job's own 3 mm
    _, trial = results.final_trial(db, job_id, "D1")
    assert view.in_hand.n_held == sum(trial.held) + sum(trial.pose_outcomes[0].held)
    assert any("2 resting poses" in caveat for caveat in view.failures.caveats)
    assert len(rescored.summary.best.poses) == 2 and rescored.summary.best.success != best.success


def test_the_finger_preview_and_grasp_pose_come_per_pose(two_pose_job):
    db, job_id = two_pose_job.db, two_pose_job.job_id

    primary, standing = results.finger_preview(db, job_id, "D1"), results.finger_preview(db, job_id, "D1", "p1")
    pose = results.grasp_pose(db, job_id, "D2")  # worked out now: only D1's is stored

    assert (primary.pose, standing.pose, standing.pose_label) == ("p0", "p1", "standing")
    assert standing.finger.pieces == primary.finger.pieces and standing.part.extent_mm == pytest.approx((10, 10, 20))
    assert standing.finger.tip_height_mm > primary.finger.tip_height_mm
    with pytest.raises(results.DesignNotFoundError, match="has no resting pose 'p9'; its poses are p0, p1"):
        results.finger_preview(db, job_id, "D1", "p9")
    assert [(p["resting_pose"], p["grasp_angle_deg"]) for p in pose["poses"]] == [("on its side", 90), ("standing", 0)]
    assert "pose 2:\n  resting_pose: standing\n" in grasp_pose_text(pose)
