"""Immutable results returned by state-free calculator use cases."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from ..history import CalculationHistoryEntry


class _NoAnsUpdate:
    """Private sentinel that distinguishes no update from an explicit ``None`` value."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "NO_ANS_UPDATE"


NO_ANS_UPDATE = _NoAnsUpdate()


@dataclass(frozen=True, slots=True)
class EngineOutcome:
    """A completed use case plus the state changes a facade may atomically commit."""

    value: object
    ans: object = NO_ANS_UPDATE
    history: tuple[CalculationHistoryEntry, ...] = ()
    memory_updates: Mapping[str, object] = field(default_factory=dict)

    @property
    def updates_ans(self) -> bool:
        return self.ans is not NO_ANS_UPDATE

    @property
    def has_state_changes(self) -> bool:
        return self.updates_ans or bool(self.history) or bool(self.memory_updates)
