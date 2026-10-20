"""Runs every Isaac call on the main thread, one at a time, in arrival order.

Isaac Sim (Kit, USD, PhysX) must be driven from the thread that started it, and the twin's scripts all start it on the
main thread. FastAPI answers requests from an event loop and a thread pool, and the app's optimizer sends several batches
at once (one per pool process). So request handlers never touch Isaac: they submit a job here and wait on its future,
and the main thread runs the jobs.
"""

import logging
import queue
import threading
from collections.abc import Callable
from concurrent.futures import Future
from typing import Any

logger = logging.getLogger(__name__)


class SimQueueClosedError(RuntimeError):
    pass


class SimQueue:
    def __init__(self) -> None:
        self._jobs: queue.Queue[tuple[Future, Callable[..., Any], tuple]] = queue.Queue()
        self._lock = threading.Lock()
        self._closed = False

    @property
    def queued(self) -> int:
        """Jobs waiting, not counting the one running."""
        return self._jobs.qsize()

    def submit(self, fn: Callable[..., Any], /, *args: Any) -> Future:
        """Thread-safe. The future resolves once the main thread has run fn(*args)."""
        future: Future = Future()
        with self._lock:
            if self._closed:
                future.set_exception(SimQueueClosedError("the sim server is shutting down"))
            else:
                self._jobs.put((future, fn, args))
        return future

    def serve(self, keep_running: Callable[[], bool], poll_s: float = 0.5) -> None:
        """Runs jobs on the main thread while keep_running() is true. keep_running is checked between jobs."""
        if threading.current_thread() is not threading.main_thread():
            raise RuntimeError("SimQueue.serve must run on the main thread, which owns Isaac Sim")
        while keep_running():
            try:
                future, fn, args = self._jobs.get(timeout=poll_s)
            except queue.Empty:
                continue
            if not future.set_running_or_notify_cancel():
                continue
            try:
                future.set_result(fn(*args))
            except Exception as e:  # the waiting request reports it; the server keeps serving
                logger.exception("Sim job %s failed", getattr(fn, "__name__", fn))
                future.set_exception(e)

    def close(self) -> None:
        """Refuses new jobs and fails the waiting ones, so their requests return instead of hanging on shutdown."""
        with self._lock:
            self._closed = True
        while True:
            try:
                future, _, _ = self._jobs.get_nowait()
            except queue.Empty:
                return
            if future.set_running_or_notify_cancel():
                future.set_exception(SimQueueClosedError("the sim server is shutting down"))
