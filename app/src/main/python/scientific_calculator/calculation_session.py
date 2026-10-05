"""Single application boundary for committing successful worker snapshots."""

from __future__ import annotations

from typing import Any, Protocol

from .calculation_worker import CalculationPayload
from .history import CalculationHistoryEntry


class CalculationState(Protocol):
    ans: Any
    history: list[CalculationHistoryEntry]
    memory: dict[str, Any]


class CalculationSession:
    """Apply only an already-successful worker payload to calculator state."""

    def __init__(self, state: CalculationState) -> None:
        self._state = state

    def apply_success(self, payload: CalculationPayload) -> None:
        """Commit copies, so a worker payload cannot retain mutable UI state."""

        history = list(payload.history)
        memory = dict(payload.memory)
        self._state.ans = payload.ans
        self._state.history[:] = history
        self._state.memory.clear()
        self._state.memory.update(memory)
