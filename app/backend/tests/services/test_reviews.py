import pytest

from api.services import reviews


def test_approval_needs_a_reviewer_name(db):
    with pytest.raises(reviews.ReviewError, match="reviewer name required"):
        reviews.set_review(db, "job1", status="approved", reviewer="  ", notes="")

    assert reviews.get_review(db, "job1") is None


def test_unknown_status_is_rejected(db):
    with pytest.raises(reviews.ReviewError, match="bad status"):
        reviews.set_review(db, "job1", status="looks fine", reviewer="alec", notes="")


def test_latest_review_replaces_the_previous_one(db):
    reviews.set_review(db, "job1", status="rejected", reviewer="alec", notes="tip too thin")
    reviews.set_review(db, "job1", status="approved", reviewer="alec", notes="v2 ok")

    review = reviews.get_review(db, "job1")

    assert (review.status, review.notes) == ("approved", "v2 ok")
