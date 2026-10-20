from api.models.part import Part
from api.services import export, jobs


def test_part_key_groups_rows_by_part():
    assert export.part_key(Part(diameter_mm=40, length_mm=12.5, upright=False)) == "cylinder-40x12.5-lying"
    assert export.part_key(Part(shape="box", width_mm=10, depth_mm=20, height_mm=5)) == "box-10x20x5"


def test_one_trial_row_per_simulated_design_and_one_chosen_best(finished_job):
    rows = export.trial_rows(finished_job.db)

    assert len(rows) == len(jobs.get_job_detail(finished_job.db, finished_job.job_id).trials)
    assert sum(r["chosen_best"] for r in rows) == 1
    assert {r["part_key"] for r in rows} == {"cylinder-31.75x15.7-upright"}
    assert all(r["grid"] is not None and len(r["held"]) > 0 for r in rows)
