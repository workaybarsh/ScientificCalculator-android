"""Immutable spreadsheet cursor helpers for the five-column LCD grid."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast


@dataclass(frozen=True, slots=True)
class SpreadsheetCursor:
    """A bounded A–E / 1–45 location plus the editor-consumption rule."""

    column: int = 0
    row: int = 0
    editing: bool = False

    def __post_init__(self) -> None:
        if not 0 <= self.column <= 4 or not 0 <= self.row <= 44:
            raise ValueError("spreadsheet cursor is outside A1:E45")

    @property
    def address(self) -> str:
        return f"{chr(65 + self.column)}{self.row + 1}"

    @classmethod
    def from_flow(cls, flow: Mapping[str, object]) -> SpreadsheetCursor:
        # The application always stores its own previously-clamped ints here;
        # the cast reflects that invariant rather than trusting caller input.
        column = cast(Any, flow.get("sheet_column", 0))
        row = cast(Any, flow.get("sheet_row", 0))
        return cls(int(column), int(row), bool(flow.get("editing", False)))

    def move_column(self, direction: int) -> SpreadsheetCursor:
        return self if self.editing else SpreadsheetCursor(max(0, min(4, self.column + direction)), self.row, False)

    def move_row(self, direction: int) -> SpreadsheetCursor:
        # Vertical arrows are intentionally consumed while editing, but must
        # not move the selected cell under the user's text cursor.
        return self if self.editing else SpreadsheetCursor(self.column, max(0, min(44, self.row + direction)), False)

    def apply_to(self, flow: dict[str, object]) -> None:
        flow.update({"sheet_column": self.column, "sheet_row": self.row, "editing": self.editing})
