"""Form definitions and read-only queries for LCD workflows.

Which inputs a matrix, vector, ratio, or distribution workflow needs is domain
knowledge, not presentation: it follows from the mathematics, not from how the
LCD draws a form. This module answers that question and reports what a flow
mapping currently holds.

Starting a form, moving through it, and committing its result stay with the
application, which owns the live flow state. Nothing here mutates it.
"""

from __future__ import annotations

from typing import Any

from . import lcd_fields
from .spreadsheet_cursor import SpreadsheetCursor

FormDefinition = tuple[str, list[dict[str, Any]], str]

# Each distribution names its inputs, their LCD labels, and their defaults.
_DISTRIBUTION_INPUTS: dict[str, tuple[tuple[str, str, float], ...]] = {
    "Normal PD": (("x", "x", 0), ("sigma", "σ", 1), ("mu", "μ", 0)),
    "Normal CD": (("lower", "lower", -1), ("upper", "upper", 1), ("sigma", "σ", 1), ("mu", "μ", 0)),
    "Inverse Normal": (("area", "area", 0.5), ("sigma", "σ", 1), ("mu", "μ", 0)),
    "Binomial PD": (("x", "x", 0), ("N", "N", 1), ("p", "p", 0.5)),
    "Binomial CD": (("x", "x", 0), ("N", "N", 1), ("p", "p", 0.5)),
    "Poisson PD": (("x", "x", 0), ("lam", "lambda", 1)),
    "Poisson CD": (("x", "x", 0), ("lam", "lambda", 1)),
}


def matrix_form(name, rows: int, columns: int) -> FormDefinition:
    """One row per matrix row, each requiring exactly the declared width."""
    fields = [
        {
            "key": f"matrix_row_{row}",
            "label": f"row {row + 1} ({columns} values)",
            "type": "matrix_row",
            "columns": columns,
            "default": "",
        }
        for row in range(rows)
    ]
    return f"{name} {rows}×{columns}", fields, "matrix_rows"


def vector_form(name, dimension: int) -> FormDefinition:
    fields = [
        lcd_fields.number_field(f"vector_{index}", f"component {index + 1}", 0)
        for index in range(dimension)
    ]
    return f"{name} {dimension}D", fields, "vector_values"


def ratio_form(kind: str) -> FormDefinition:
    """A ratio always takes A and B, then whichever of C or D is known."""
    solving_for_d = kind == "A:B = X:D"
    fields = [
        lcd_fields.number_field("ratio_A", "A", 0),
        lcd_fields.number_field("ratio_B", "B", 1),
        lcd_fields.number_field("ratio_D" if solving_for_d else "ratio_C", "D" if solving_for_d else "C", 1),
    ]
    return "RATIO " + kind, fields, "ratio_values"


def distribution_form(kind: str) -> FormDefinition:
    """Counts are non-negative integers; the remaining parameters are real."""
    fields = []
    for key, label, default in _DISTRIBUTION_INPUTS[kind]:
        integer = key in {"x", "N"} and kind.startswith(("Binomial", "Poisson"))
        fields.append(
            lcd_fields.number_field(key, label, default, integer=integer, minimum=0 if integer else None)
        )
    return "DIST " + kind, fields, "distribution_run"


def is_history(flow) -> bool:
    """Report whether *flow* is the History browser rather than a form."""
    return bool(flow and flow.get("mode") == "History")


def current_spec(flow) -> dict[str, Any] | None:
    """Return the field specification the caret currently sits on."""
    if not flow or flow.get("phase") != "form":
        return None
    fields = flow.get("fields", [])
    index = flow.get("index", 0)
    return fields[index] if 0 <= index < len(fields) else None


def sheet_address(flow) -> str:
    return SpreadsheetCursor.from_flow(flow).address


def sheet_target_address(flow) -> str:
    values = flow["values"]
    return f"{values['sheet_target_column']}{values['sheet_target_row']}"


__all__ = [
    "current_spec",
    "distribution_form",
    "is_history",
    "matrix_form",
    "ratio_form",
    "sheet_address",
    "sheet_target_address",
    "vector_form",
]
