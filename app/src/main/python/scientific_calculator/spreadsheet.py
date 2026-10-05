from __future__ import annotations

import builtins
import re
from dataclasses import dataclass, field
from typing import Any, cast

from .calculator_engine import CalculatorError, ScientificCalculatorEngine

CELL_RE = re.compile(r"\$?([A-E])\$?([1-9]|[1-3][0-9]|4[0-5])$")
RANGE_RE = re.compile(
    r"(\$?[A-E]\$?(?:[1-9]|[1-3][0-9]|4[0-5])):"
    r"(\$?[A-E]\$?(?:[1-9]|[1-3][0-9]|4[0-5]))"
)
REFERENCE_RE = re.compile(
    r"(?<![A-Za-z0-9_])\$?[A-E]\$?(?:[1-9]|[1-3][0-9]|4[0-5])"
    r"(?![A-Za-z0-9_])"
)
SHIFT_REFERENCE_RE = re.compile(
    r"(?<![A-Za-z0-9_])(\$?)([A-E])(\$?)([1-9]|[1-3][0-9]|4[0-5])"
    r"(?![A-Za-z0-9_])"
)


@dataclass
class SpreadsheetModel:
    engine: ScientificCalculatorEngine
    cells: dict[str, str] = field(default_factory=dict)
    cache: dict[str, float] = field(default_factory=dict)
    dirty_cells: set[str] = field(default_factory=set)
    needs_recalculation: bool = False

    def normalize_addr(self, address: str) -> str:
        if not isinstance(address, str):
            raise CalculatorError("Range ERROR")
        return address.replace("$", "").upper()

    def valid(self, address: str) -> bool:
        return isinstance(address, str) and bool(CELL_RE.fullmatch(address.upper()))

    def _require_addr(self, address: str) -> str:
        # Validate raw input first: otherwise A$$1 becomes valid after '$'
        # removal in normalize_addr.
        if not self.valid(address):
            raise CalculatorError("Range ERROR")
        normalized = self.normalize_addr(address)
        return normalized

    @staticmethod
    def _validate_text(text: str) -> None:
        if not isinstance(text, str):
            raise CalculatorError("Syntax ERROR")
        if text.startswith("=") and len(text[1:].encode()) > 49:
            raise CalculatorError("Memory ERROR: formül 49 baytı aşıyor")
        if not text.startswith("=") and len(text.encode()) > 10:
            raise CalculatorError("Memory ERROR: sabit 10 baytı aşıyor")

    @staticmethod
    def _memory_used(cells: dict[str, str]) -> int:
        return sum(
            (49 if value.startswith("=") else 10) + len(value.encode())
            for value in cells.values()
        )

    def _evaluate(self, expression: str):
        """Evaluate a cell without changing the calculator's Ans or history."""
        saved_ans = self.engine.ans
        saved_history = self.engine.history
        saved_history_items = list(saved_history)
        try:
            return self.engine.evaluate(expression, exact=False)
        finally:
            self.engine.ans = saved_ans
            saved_history[:] = saved_history_items
            self.engine.history = saved_history

    def _calculate_cache(self) -> dict[str, float]:
        # One calculation pass can reach the same dependency through several
        # cells.  Reusing a per-pass cache avoids recalculating that expression
        # while keeping the public ``value`` method independent of stale UI
        # cache entries.
        calculated: dict[str, float] = {}
        for address in list(self.cells):
            self._value(address, set(), calculated)
        return calculated

    def _commit_cells(self, candidate: dict[str, str]) -> None:
        """Commit a candidate sheet atomically, recalculating when enabled."""
        if self._memory_used(candidate) > 1700:
            raise CalculatorError("Memory ERROR")

        previous_cells = self.cells
        previous_cache = self.cache
        previous_dirty = self.dirty_cells
        previous_needs = self.needs_recalculation
        self.cells = candidate
        try:
            calculated = (
                self._calculate_cache()
                if self.engine.settings.spreadsheet_auto_calc
                else None
            )
        except Exception:
            self.cells = previous_cells
            self.cache = previous_cache
            self.dirty_cells = previous_dirty
            self.needs_recalculation = previous_needs
            raise

        if calculated is not None:
            self.cache = calculated
            self.dirty_cells.clear()
            self.needs_recalculation = False
        else:
            # A changed formula can invalidate any cached dependant.  Marking
            # the complete live sheet is conservative and never hides a stale
            # result when dependency analysis is intentionally deferred.
            self.cache = {key: value for key, value in self.cache.items() if key in candidate}
            self.dirty_cells = set(candidate)
            self.needs_recalculation = bool(candidate)

    def set(self, address: str, text: str) -> None:
        address = self._require_addr(address)
        self._validate_text(text)
        candidate = dict(self.cells)
        candidate[address] = text
        self._commit_cells(candidate)

    def delete(self, address: str) -> None:
        address = self._require_addr(address)
        candidate = dict(self.cells)
        candidate.pop(address, None)
        self._commit_cells(candidate)

    def delete_all(self) -> None:
        self.cells.clear()
        self.cache.clear()
        self.dirty_cells.clear()
        self.needs_recalculation = False

    def memory_used(self) -> int:
        return self._memory_used(self.cells)

    def free_space(self) -> int:
        return max(0, 1700 - self.memory_used())

    def _coords(self, address: str) -> tuple[int, int]:
        address = self._require_addr(address)
        return ord(address[0]) - 65, int(address[1:]) - 1

    @staticmethod
    def _addr(column: int, row: int) -> str:
        return f"{chr(65 + column)}{row + 1}"

    def range_values(
        self,
        start: str,
        end: str,
        stack: builtins.set[str],
        calculated: dict[str, float] | None = None,
    ):
        c1, r1 = self._coords(start)
        c2, r2 = self._coords(end)
        values = []
        for row in range(min(r1, r2), max(r1, r2) + 1):
            for column in range(min(c1, c2), max(c1, c2) + 1):
                values.append(self._value(self._addr(column, row), stack, calculated))
        return values

    def value(self, address: str, stack: builtins.set[str] | None = None) -> float:
        """Evaluate one cell without relying on a previous recalculation pass."""
        return self._value(address, stack)

    def _value(
        self,
        address: str,
        stack: builtins.set[str] | None = None,
        calculated: dict[str, float] | None = None,
    ) -> float:
        address = self._require_addr(address)
        if calculated is not None and address in calculated:
            return calculated[address]
        stack = set() if stack is None else set(stack)
        if address in stack:
            raise CalculatorError("Circular ERROR")
        stack.add(address)

        raw = self.cells.get(address, "")
        if raw == "":
            result = 0.0
        elif not raw.startswith("="):
            result = float(cast(Any, self._evaluate(raw)))
        else:
            expression = raw[1:]
            ranges = {}

            def replace_range(match):
                values = self.range_values(match.group(1), match.group(2), stack, calculated)
                key = f"__R{len(ranges)}"
                ranges[key] = values
                return key

            expression = RANGE_RE.sub(replace_range, expression)

            def replace_aggregate(match):
                function, key = match.group(1), match.group(2)
                values = ranges[key]
                if function == "Sum":
                    return str(sum(values))
                if function == "Mean":
                    return str(sum(values) / len(values) if values else 0)
                if function == "Min":
                    return str(min(values))
                return str(max(values))

            expression = re.sub(
                r"\b(Sum|Mean|Min|Max)\((__R\d+)\)",
                replace_aggregate,
                expression,
            )
            references = set(REFERENCE_RE.findall(expression))
            for reference in sorted(references, key=len, reverse=True):
                expression = expression.replace(
                    reference, str(self._value(reference, stack, calculated))
                )
            result = float(cast(Any, self._evaluate(expression)))
        # Empty references evaluate as zero but are not stored as sheet cells;
        # persisting them in the cache would make a deleted cell appear live.
        if calculated is not None and address in self.cells:
            calculated[address] = result
        return result

    def recalculate(self) -> dict[str, float]:
        calculated = self._calculate_cache()
        self.cache = calculated
        self.dirty_cells.clear()
        self.needs_recalculation = False
        return self.cache

    def shift_formula(self, formula: str, dc: int, dr: int) -> str:
        def replace_reference(match):
            column_absolute = match.group(1) == "$"
            column = ord(match.group(2)) - 65
            row_absolute = match.group(3) == "$"
            row = int(match.group(4)) - 1
            if not column_absolute:
                column += dc
            if not row_absolute:
                row += dr
            if not (0 <= column < 5 and 0 <= row < 45):
                raise CalculatorError("Range ERROR")
            return (
                ("$" if column_absolute else "")
                + chr(65 + column)
                + ("$" if row_absolute else "")
                + str(row + 1)
            )

        return SHIFT_REFERENCE_RE.sub(replace_reference, formula)

    def copy(self, source: str, destination: str) -> None:
        source = self._require_addr(source)
        destination = self._require_addr(destination)
        raw = self.cells.get(source, "")
        if raw.startswith("="):
            c1, r1 = self._coords(source)
            c2, r2 = self._coords(destination)
            raw = self.shift_formula(raw, c2 - c1, r2 - r1)
        self._validate_text(raw)
        candidate = dict(self.cells)
        candidate[destination] = raw
        self._commit_cells(candidate)

    def cut(self, source: str, destination: str) -> None:
        source = self._require_addr(source)
        destination = self._require_addr(destination)
        if source == destination:
            return
        raw = self.cells.get(source, "")
        self._validate_text(raw)
        candidate = dict(self.cells)
        candidate[destination] = raw
        candidate.pop(source, None)
        self._commit_cells(candidate)

    def fill_value(self, start: str, end: str, value) -> None:
        c1, r1 = self._coords(start)
        c2, r2 = self._coords(end)
        text = str(value)
        self._validate_text(text)
        candidate = dict(self.cells)
        for row in range(min(r1, r2), max(r1, r2) + 1):
            for column in range(min(c1, c2), max(c1, c2) + 1):
                candidate[self._addr(column, row)] = text
        self._commit_cells(candidate)

    def fill_formula(self, start: str, end: str, formula: str) -> None:
        c1, r1 = self._coords(start)
        c2, r2 = self._coords(end)
        self._validate_text(formula)
        candidate = dict(self.cells)
        for row in range(min(r1, r2), max(r1, r2) + 1):
            for column in range(min(c1, c2), max(c1, c2) + 1):
                shifted = (
                    formula
                    if (column, row) == (c1, r1)
                    else self.shift_formula(formula, column - c1, row - r1)
                )
                self._validate_text(shifted)
                candidate[self._addr(column, row)] = shifted
        self._commit_cells(candidate)
