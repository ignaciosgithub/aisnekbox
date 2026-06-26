"""Bounded concurrency control for sandbox execution.

Each evaluation spawns an NsJail subprocess that consumes CPU, memory and a
process slot. Without a ceiling, a burst of requests could spawn an unbounded
number of jails and exhaust the host (a denial-of-service vector). The
:class:`Limiter` caps the number of in-flight evaluations and rejects excess
load immediately with backpressure instead of degrading the whole service.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager


class CapacityError(RuntimeError):
    """Raised when no execution slot is available right now."""


class Limiter:
    """A non-blocking counting semaphore around sandbox execution slots."""

    def __init__(self, max_concurrency: int) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be >= 1")
        self._max = max_concurrency
        self._semaphore = threading.BoundedSemaphore(max_concurrency)

    @property
    def max_concurrency(self) -> int:
        return self._max

    @contextmanager
    def slot(self) -> Iterator[None]:
        """Acquire a slot for the duration of the ``with`` block.

        Acquisition is non-blocking: if every slot is taken the caller is
        rejected with :class:`CapacityError` rather than queuing, so clients
        receive fast, explicit backpressure.
        """
        if not self._semaphore.acquire(blocking=False):
            raise CapacityError("no execution slot available")
        try:
            yield
        finally:
            self._semaphore.release()
