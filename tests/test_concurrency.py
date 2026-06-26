"""Unit tests for the bounded concurrency limiter."""

from __future__ import annotations

import pytest

from aisnekbox.concurrency import CapacityError, Limiter


def test_rejects_invalid_capacity() -> None:
    with pytest.raises(ValueError):
        Limiter(0)


def test_slot_acquires_and_releases() -> None:
    limiter = Limiter(1)
    with limiter.slot():
        pass
    # Slot is released afterwards, so it can be acquired again.
    with limiter.slot():
        pass


def test_slot_rejects_when_full() -> None:
    limiter = Limiter(1)
    with limiter.slot(), pytest.raises(CapacityError):  # noqa: SIM117
        with limiter.slot():
            pass


def test_slot_released_on_exception() -> None:
    limiter = Limiter(1)
    with pytest.raises(RuntimeError), limiter.slot():
        raise RuntimeError("boom")
    # The slot must have been freed despite the exception.
    with limiter.slot():
        pass


def test_max_concurrency_property() -> None:
    assert Limiter(4).max_concurrency == 4
