"""Typed failures exchanged between calculation processes and the UI."""
from __future__ import annotations


class CalculationTimeout(RuntimeError):
    """A calculation exceeded the caller's allowed wall-clock time."""


class CalculationCancelled(RuntimeError):
    """A calculation was deliberately invalidated before it completed."""


class WorkerCrashed(RuntimeError):
    """A calculation process exited without a valid response."""


class WorkerProtocolError(WorkerCrashed):
    """A calculation process returned an invalid response payload."""
