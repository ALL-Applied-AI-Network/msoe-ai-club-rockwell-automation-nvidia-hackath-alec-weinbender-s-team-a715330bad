"""recent_batches.py: a batch sent again under its key gets the first one's future, running or done; old finished keys
are dropped, running ones never."""

from concurrent.futures import Future

from sim_server.recent_batches import RecentBatches


def submitter():
    made: list[Future] = []

    def submit() -> Future:
        made.append(Future())
        return made[-1]

    return submit, made


def test_a_key_sent_again_gets_its_first_batch_running_or_done():
    batches, (submit, made) = RecentBatches(), submitter()

    first = batches.submit("round-3", submit)
    assert batches.submit("round-3", submit) is first  # still running: the retry waits on it
    first.set_result("held")
    assert batches.submit("round-3", submit) is first  # done: answered from it
    assert len(made) == 1


def test_without_a_key_or_under_a_new_one_every_batch_runs():
    batches, (submit, made) = RecentBatches(), submitter()

    batches.submit(None, submit)
    batches.submit(None, submit)
    batches.submit("a", submit)
    batches.submit("b", submit)

    assert len(made) == 4


def test_a_cancelled_batch_runs_again():
    batches, (submit, made) = RecentBatches(), submitter()
    batches.submit("a", submit).cancel()

    assert batches.submit("a", submit) is made[1]


def test_old_finished_keys_are_dropped_and_running_ones_kept():
    batches, (submit, made) = RecentBatches(keep=2), submitter()
    running = batches.submit("running", submit)
    for key in ("a", "b", "c"):
        batches.submit(key, submit).set_result(key)

    assert batches.submit("running", submit) is running  # over the limit, but still running
    assert batches.submit("c", submit) is made[3]
    batches.submit("a", submit)  # dropped: runs again
    assert len(made) == 5
