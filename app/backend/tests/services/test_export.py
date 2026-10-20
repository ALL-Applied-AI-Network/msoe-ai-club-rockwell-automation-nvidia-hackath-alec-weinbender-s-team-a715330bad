import json

import pytest

from api.services import export, jobs


def test_every_trial_is_a_row_with_its_raw_outcomes_and_context(finished_job):
    db, job_id = finished_job.db, finished_job.job_id
    job = jobs.get_job(db, job_id)

    rows = export.trial_rows(db, job_id)

    assert len(rows) == job.n_done == 18 + 2 + 5  # the search with its baselines, then the final test
    assert [row["number"] for row in rows] == list(range(len(rows)))
    first = rows[0]
    assert (first["job_id"], first["experiment_id"], first["name"], first["sim_backend"]) == (job_id, "EXP-0001", job.name, "mock")
    assert first["part_id"] == finished_job.part_id and first["part"]["shape"] == "cylinder"
    assert first["task"]["kind"] == "drop" and first["error"]["sigma_mm"] == 3.0
    search, final = [r for r in rows if r["grid"] == "search"], [r for r in rows if r["grid"] == "final"]
    assert {r["search"] for r in search} == {"baseline", "vpad"} and {r["round"] for r in search} == {0, 1, 2}
    assert all(len(r["held"]) == len(r["in_hand"]) == r["n_grasps"] == 81 for r in search)
    assert all(r["grid_definition"] == job.plan.grid.model_dump(mode="json") for r in search)
    assert all(r["grid_definition"] == job.plan.final_grid.model_dump(mode="json") for r in final)
    assert sorted(r["label"] for r in final) == ["D1", "D2", "D3", "IMP", "STOCK"]
    assert [r["label"] for r in rows if r["chosen_best"]] == ["D1"]
    vpad = next(r for r in search if r["kind"] == "search")
    assert vpad["params"]["family"] == "vpad" and vpad["held_after_transport"] is None and vpad["duration_s"] > 0
    json.dumps(rows)  # plain JSON all the way down


def test_rows_for_every_job_and_an_unknown_job(finished_job):
    assert len(export.trial_rows(finished_job.db)) == len(export.trial_rows(finished_job.db, finished_job.job_id))
    with pytest.raises(jobs.JobNotFoundError):
        export.trial_rows(finished_job.db, "nope")
