"""Primitive-safe, structured calculation history entries."""
from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field

HistoryPrimitive = None | bool | int | float | str
HistoryValue = HistoryPrimitive | tuple["HistoryValue", ...] | dict[str, "HistoryValue"]
_MAX_METADATA_DEPTH = 32
_MAX_METADATA_NODES = 1_024


def _normalise_value(value: object, *, depth: int = 0, seen: set[int] | None = None, budget: list[int] | None = None) -> HistoryValue:
    if depth > _MAX_METADATA_DEPTH:
        raise TypeError("History metadata is too deeply nested")
    if budget is None:
        budget = [0]
    budget[0] += 1
    if budget[0] > _MAX_METADATA_NODES:
        raise TypeError("History metadata has too many values")
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value
    if isinstance(value, str):
        return value
    if seen is None:
        seen = set()
    if isinstance(value, Mapping):
        value_id = id(value)
        if value_id in seen:
            raise TypeError("History metadata cannot contain cycles")
        seen.add(value_id)
        try:
            return {str(key): _normalise_value(item, depth=depth + 1, seen=seen, budget=budget) for key, item in value.items()}
        finally:
            seen.remove(value_id)
    if isinstance(value, (list, tuple)):
        value_id = id(value)
        if value_id in seen:
            raise TypeError("History metadata cannot contain cycles")
        seen.add(value_id)
        try:
            return tuple(_normalise_value(item, depth=depth + 1, seen=seen, budget=budget) for item in value)
        finally:
            seen.remove(value_id)
    raise TypeError("History metadata must contain only primitive values")


@dataclass(frozen=True, slots=True, eq=False)
class CalculationHistoryEntry:
    """A display-compatible pair with optional structured recall payload."""

    expression: str
    result: str
    kind: str = "legacy"
    metadata: dict[str, HistoryValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.expression, str) or not isinstance(self.result, str) or not isinstance(self.kind, str):
            raise TypeError("History entry text fields must be strings")
        if not isinstance(self.metadata, Mapping):
            raise TypeError("History metadata must be a mapping")
        object.__setattr__(self, "metadata", {str(key): _normalise_value(value) for key, value in self.metadata.items()})

    def __iter__(self) -> Iterator[str]:
        yield self.expression
        yield self.result

    def __len__(self) -> int:
        return 2

    def __getitem__(self, index: int) -> str:
        return (self.expression, self.result)[index]

    def __eq__(self, other: object) -> bool:
        if isinstance(other, CalculationHistoryEntry):
            return (
                self.expression,
                self.result,
                self.kind,
                self.metadata,
            ) == (other.expression, other.result, other.kind, other.metadata)
        if isinstance(other, tuple) and len(other) == 2:
            return (self.expression, self.result) == other
        return False

    @classmethod
    def from_legacy(cls, entry: object) -> CalculationHistoryEntry:
        if isinstance(entry, cls):
            return entry
        if not isinstance(entry, (list, tuple)) or len(entry) != 2:
            raise ValueError("Invalid history entry")
        expression, result = entry
        if not isinstance(expression, str) or not isinstance(result, str):
            raise ValueError("History entries must be text")
        return cls(expression, result)
