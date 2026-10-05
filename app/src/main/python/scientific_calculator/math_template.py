"""Tk-independent state for natural mathematical LCD templates.

The UI owns rendering, while this module owns which mathematical input slot is
active and how arrow/backspace navigation changes that state.  Keeping it pure
makes integral, matrix, equation, and future mathematical templates testable
without creating a Tcl interpreter.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum


class NavigationDirection(StrEnum):
    LEFT = "left"
    RIGHT = "right"
    UP = "up"
    DOWN = "down"


@dataclass(frozen=True, slots=True)
class TemplateSlot:
    """One editable mathematical region and its optional geometric neighbours."""

    key: str
    left: str | None = None
    right: str | None = None
    up: str | None = None
    down: str | None = None

    def neighbour(self, direction: NavigationDirection) -> str | None:
        return {
            NavigationDirection.LEFT: self.left,
            NavigationDirection.RIGHT: self.right,
            NavigationDirection.UP: self.up,
            NavigationDirection.DOWN: self.down,
        }[direction]


@dataclass(slots=True)
class MathTemplate:
    """Mutable values plus a validated, bounded navigation graph."""

    slots: tuple[TemplateSlot, ...]
    active_slot: str
    values: dict[str, str] = field(default_factory=dict)
    _by_key: dict[str, TemplateSlot] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._by_key = {slot.key: slot for slot in self.slots}
        if not self.slots or len(self._by_key) != len(self.slots):
            raise ValueError("template slots must be non-empty and unique")
        if self.active_slot not in self._by_key:
            raise ValueError("active slot must exist in the template")
        unknown_values = set(self.values) - set(self._by_key)
        if unknown_values:
            raise ValueError("template values must refer to known slots")
        for slot in self.slots:
            for direction in NavigationDirection:
                target = slot.neighbour(direction)
                if target is not None and target not in self._by_key:
                    raise ValueError("template neighbour must refer to a known slot")
        self.values = {key: str(value) for key, value in self.values.items()}

    @classmethod
    def linear(cls, keys: Iterable[str], *, values: dict[str, str] | None = None) -> MathTemplate:
        """Build a row template whose left/right edges stop at its ends."""

        names = tuple(keys)
        return cls(
            tuple(
                TemplateSlot(
                    key=name,
                    left=names[index - 1] if index else None,
                    right=names[index + 1] if index + 1 < len(names) else None,
                )
                for index, name in enumerate(names)
            ),
            active_slot=names[0] if names else "",
            values={} if values is None else values,
        )

    @property
    def active_value(self) -> str:
        return self.values.get(self.active_slot, "")

    def set_active_value(self, value: object) -> None:
        self.values[self.active_slot] = str(value)

    def move(self, direction: NavigationDirection) -> bool:
        """Move to a valid neighbour and report whether the active slot changed."""

        target = self._by_key[self.active_slot].neighbour(direction)
        if target is None:
            return False
        self.active_slot = target
        return True

    def backspace(self) -> bool:
        """Delete one character, or move left only when the current slot is empty."""

        value = self.active_value
        if value:
            self.values[self.active_slot] = value[:-1]
            return True
        return self.move(NavigationDirection.LEFT)
