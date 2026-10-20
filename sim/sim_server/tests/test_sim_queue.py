"""sim_queue.py: jobs submitted from any thread run on the main thread, in order; failures reach the waiting caller."""

import threading

import pytest

from sim_server.sim_queue import SimQueue, SimQueueClosedError


def test_jobs_from_other_threads_run_on_the_main_thread_in_order():
    queue, ran = SimQueue(), []

    def job(n):
        ran.append((n, threading.current_thread() is threading.main_thread()))
        return n * 10

    futures = []
    submitter = threading.Thread(target=lambda: futures.extend(queue.submit(job, n) for n in range(3)))
    submitter.start()
    submitter.join()
    queue.serve(keep_running=lambda: len(ran) < 3, poll_s=0.01)  # pytest runs tests on the main thread
    assert ran == [(0, True), (1, True), (2, True)]
    assert [f.result(timeout=1) for f in futures] == [0, 10, 20]


def test_a_failing_job_fails_its_future_and_the_queue_keeps_serving():
    queue, done = SimQueue(), []
    bad = queue.submit(lambda: 1 / 0)
    good = queue.submit(lambda: done.append(True) or "ok")
    queue.serve(keep_running=lambda: not done, poll_s=0.01)
    with pytest.raises(ZeroDivisionError):
        bad.result(timeout=1)
    assert good.result(timeout=1) == "ok"


def test_close_fails_waiting_jobs_and_refuses_new_ones():
    queue = SimQueue()
    waiting = queue.submit(lambda: "never")
    assert queue.queued == 1
    queue.close()
    with pytest.raises(SimQueueClosedError):
        waiting.result(timeout=1)
    with pytest.raises(SimQueueClosedError):
        queue.submit(lambda: "late").result(timeout=1)


def test_serve_refuses_any_thread_but_main():
    errors = []

    def serve():
        try:
            SimQueue().serve(keep_running=lambda: False)
        except RuntimeError as e:
            errors.append(e)

    thread = threading.Thread(target=serve)
    thread.start()
    thread.join()
    assert errors and "main thread" in str(errors[0])
