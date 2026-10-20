"""Batches by the caller's Idempotency-Key, so one whose answer was lost with the connection (the app's port forward
dropped with the VPN mid-round) is answered from the run already made, or still running, instead of being run again.

The app sends each round once under a new key, and again under the same key only after losing the connection. The last
KEEP finished keys are kept; a batch still running is never dropped. Only the event loop touches this, so it has no lock.
"""

from collections import OrderedDict
from collections.abc import Callable
from concurrent.futures import Future

KEEP = 32


class RecentBatches:
    def __init__(self, keep: int = KEEP) -> None:
        self._futures: OrderedDict[str, Future] = OrderedDict()
        self._keep = keep

    def submit(self, key: str | None, submit: Callable[[], Future]) -> Future:
        """The future of this key's batch: the one submitted under it before, else a new one from submit(). Without a
        key, always a new one."""
        if key is None:
            return submit()
        future = self._futures.get(key)
        if future is None or future.cancelled():
            future = self._futures[key] = submit()
        self._futures.move_to_end(key)
        for old in [k for k, f in self._futures.items() if f.done()]:  # oldest first
            if len(self._futures) <= self._keep:
                break
            del self._futures[old]
        return future
