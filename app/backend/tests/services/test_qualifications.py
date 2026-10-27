import pytest

from api.services import qualifications


def pair(e):
    (q,) = qualifications.list_qualifications(e.db, finger_id=e.generated_id, part_id=e.part_id)
    return q


def test_a_pair_is_simulated_until_a_real_session_is_logged(evaluated_copy):
    e = evaluated_copy
    q = pair(e)
    assert q.status == "simulated" and q.sessions == [] and q.measured_success is None and q.comparisons == []
    assert q.finger_code == "FNG-0002" and q.part_name == "cube.step"

    logged = qualifications.add_session(e.db, q.id, trials=10, successes=9, operator="Shamar", notes="first slot")

    assert logged.status == "validated" and logged.real_trials == 10 and logged.measured_success == 0.9
    (comparison,) = logged.comparisons
    assert comparison.kind == "natural" and comparison.predicted_success == pytest.approx(q.prediction.success)
    assert logged.gap_flagged == comparison.gap_flagged


def test_sessions_can_be_corrected_and_removed(evaluated_copy):
    e = evaluated_copy
    q = qualifications.add_session(e.db, pair(e).id, trials=10, successes=2)
    (session,) = q.sessions

    fixed = qualifications.update_session(e.db, q.id, session.id, {"successes": 8, "kind": "commanded", "predicted_success": 0.8})
    assert (fixed.sessions[0].successes, fixed.sessions[0].kind) == (8, "commanded")
    assert fixed.comparisons[0].predicted_success == 0.8 and not fixed.gap_flagged

    with pytest.raises(qualifications.QualificationInputError, match="more successes than trials"):
        qualifications.update_session(e.db, q.id, session.id, {"successes": 11})
    with pytest.raises(qualifications.QualificationInputError, match="can't change"):
        qualifications.update_session(e.db, q.id, session.id, {"qualification_id": 3})
    with pytest.raises(qualifications.SessionNotFoundError):
        qualifications.delete_session(e.db, q.id + 1000, session.id)

    emptied = qualifications.delete_session(e.db, q.id, session.id)
    assert emptied.status == "simulated" and emptied.sessions == []


def test_a_pair_no_evaluation_covered_can_still_be_logged(evaluated_copy, cad, shapes, step_file):
    from api.services import parts

    e = evaluated_copy
    bar = parts.create_part(e.db, e.config, cad, "bar.step", step_file(shapes["bar"], "bar.step"), None)

    q = qualifications.ensure_qualification(e.db, e.uploaded_id, bar.id)
    again = qualifications.ensure_qualification(e.db, e.uploaded_id, bar.id)

    assert q.id == again.id and q.prediction is None
    logged = qualifications.add_session(e.db, q.id, trials=5, successes=5)
    assert logged.status == "validated" and logged.comparisons[0].predicted_success is None and not logged.gap_flagged
    with pytest.raises(qualifications.QualificationInputError, match="isn't in the library"):
        qualifications.ensure_qualification(e.db, "nope", bar.id)
    with pytest.raises(qualifications.QualificationInputError, match="doesn't exist"):
        qualifications.ensure_qualification(e.db, e.uploaded_id, "nope")


def test_a_bad_session_is_refused(evaluated_copy):
    e = evaluated_copy
    with pytest.raises(qualifications.QualificationInputError, match="more successes than trials"):
        qualifications.add_session(e.db, pair(e).id, trials=3, successes=4)
    with pytest.raises(qualifications.QualificationNotFoundError):
        qualifications.add_session(e.db, 999, trials=3, successes=1)
