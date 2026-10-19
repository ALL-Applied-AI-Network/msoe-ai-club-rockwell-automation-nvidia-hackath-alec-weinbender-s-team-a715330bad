from api.models.part import Part
from api.services import export, jobs


def test_part_key_groups_rows_by_part():
    assert export.part_key(Part(shape="sphere", diameter_mm=40, length_mm=12.5)) == "sphere-40x12.5"


def test_one_trial_row_per_simulated_design_and_one_chosen_best(finished_job):
    rows = export.trial_rows(finished_job.db)

    assert len(rows) == len(jobs.get_job_detail(finished_job.db, finished_job.job_id).trials)
    assert sum(r["chosen_best"] for r in rows) == 1
    assert {r["part_key"] for r in rows} == {"sphere-40x40"}


def test_one_suggestion_row_per_llm_proposal(finished_job):
    rows = export.suggestion_rows(finished_job.db)

    assert len(rows) == 2
    assert all(r["source"] == "mock" and r["job_best"] is not None for r in rows)
