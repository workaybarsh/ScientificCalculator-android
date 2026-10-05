"""Field construction, parsing, and text rendering for LCD forms.

An LCD form describes its inputs as plain specification dictionaries. This
module builds those specifications, renders their current text, and converts
entered text back into calculator values.

It owns no application state and never touches Tk: the only collaborator it
needs is an engine to parse expressions with, which the caller passes in. That
keeps the numeric-entry rules independently testable and prevents form
validation from drifting into the Tk layer.
"""

from __future__ import annotations

import math
import re
from typing import Any

import numpy as np

from .errors import CalculatorError


def number_text(value) -> str:
    """Render a stored field value as the text an LCD form should show."""
    if isinstance(value, (int, np.integer)):
        return str(int(value))
    if isinstance(value, (float, np.floating)):
        return f"{float(value):.12g}"
    return str(value)


def choice_field(key, label, choices, default=None) -> dict[str, Any]:
    if default is None:
        default = next(iter(choices.values()))
    return {"key": key, "label": label, "type": "choice", "choices": choices, "default": default}


def action_choice_field(key, label, actions) -> dict[str, Any]:
    """Create choices with stable routing ids and concise visible labels."""
    choices = {index: action_id for index, (action_id, _display) in enumerate(actions, 1)}
    field = choice_field(key, label, choices)
    field["choice_labels"] = {action_id: display for action_id, display in actions}
    return field


def number_field(key, label, default: Any = "", integer=False, minimum=None, maximum=None) -> dict[str, Any]:
    field = {"key": key, "label": label, "type": "integer" if integer else "number", "default": default}
    if minimum is not None:
        field["minimum"] = minimum
    if maximum is not None:
        field["maximum"] = maximum
    return field


def field_text(flow, spec) -> str:
    """Return the text a field shows: its draft, its stored value, or default."""
    key = spec["key"]
    if key in flow.get("draft", {}):
        return flow["draft"][key]
    if key in flow.get("values", {}):
        value = flow["values"][key]
        if spec.get("type") == "choice":
            for number, choice in spec["choices"].items():
                if choice == value:
                    return str(number)
        return number_text(value)
    default = spec.get("default", "")
    if spec.get("type") == "choice":
        for number, choice in spec["choices"].items():
            if choice == default:
                return str(number)
    return number_text(default)


def array_lines(title, value) -> list[str]:
    data = np.asarray(value)
    if data.ndim == 0:
        return [f"{title} = {number_text(data.item())}"]
    if data.ndim == 1:
        return [f"{title} = [" + ", ".join(number_text(item) for item in data) + "]"]
    return [
        f"{title} r{row + 1}: [" + ", ".join(number_text(item) for item in data[row]) + "]"
        for row in range(data.shape[0])
    ]


def real_expression(parsed, label="value") -> float:
    """Reduce an already-parsed expression to a finite real number."""
    import sympy as sp

    if getattr(parsed, "free_symbols", set()):
        raise CalculatorError(f"Argument ERROR: {label} must be numeric")
    try:
        value = complex(sp.N(parsed, 17))
    except Exception as exc:
        raise CalculatorError(f"Argument ERROR: {label}") from exc
    if abs(value.imag) > 1e-12 or not math.isfinite(value.real):
        raise CalculatorError(f"Math ERROR: {label} must be finite and real")
    return float(value.real)


def parse_real(engine, text, label="value", integer=False, minimum=None, maximum=None):
    raw = str(text).strip()
    if not raw:
        raise CalculatorError(f"Argument ERROR: {label} is required")
    try:
        parsed = engine.parse(raw)
    except CalculatorError:
        raise
    except Exception as exc:
        raise CalculatorError(f"Argument ERROR: {label}") from exc
    result = real_expression(parsed, label)
    if integer:
        if not result.is_integer():
            raise CalculatorError(f"Argument ERROR: {label} must be an integer")
        result = int(result)
    if minimum is not None and result < minimum:
        raise CalculatorError(f"Argument ERROR: {label} must be at least {minimum}")
    if maximum is not None and result > maximum:
        raise CalculatorError(f"Argument ERROR: {label} must be at most {maximum}")
    return result


def parse_numbers(engine, text, label) -> list:
    values = [part for part in re.split(r"[ ,;\n]+", str(text).strip()) if part]
    if not values:
        raise CalculatorError(f"Argument ERROR: {label} is required")
    return [parse_real(engine, value, label) for value in values]


def matrix_row_tokens(text) -> list[str]:
    """Split a matrix row while treating ``+``/minus as cell separators.

    The calculator's physical minus key emits ``−`` while a physical
    keyboard emits ``-``. Both begin the following value and signs in
    scientific notation remain part of that value. This keeps entries
    such as ``1+1−1`` unambiguous without changing number-list syntax in
    the other modes.
    """
    values: list[str] = []
    current: list[str] = []

    def commit():
        value = "".join(current).strip()
        if value not in {"", "+", "-"}:
            values.append(value)
        current.clear()

    for character in str(text):
        if character == "−":
            character = "-"
        if character in " ,;\t\r\n":
            commit()
        elif character in "+-":
            if current and current[-1] in "eE":
                current.append(character)
            elif current:
                commit()
                if character == "-":
                    current.append(character)
            elif character == "-":
                current.append(character)
            # A leading '+' is purely cosmetic; leave the next value
            # positive instead of creating an empty matrix cell.
        else:
            current.append(character)
    commit()
    return values


def parse_matrix_row(engine, text, spec) -> list:
    """Parse one matrix row and require precisely its declared width."""
    label = spec.get("label", spec["key"])
    columns = int(spec["columns"])
    tokens = matrix_row_tokens(text)
    if not tokens:
        raise CalculatorError(f"Argument ERROR: {label} is required")
    values = [parse_real(engine, value, label) for value in tokens]
    if len(values) > columns:
        raise CalculatorError(f"Argument ERROR: {label} accepts at most {columns} values")
    if len(values) < columns:
        raise CalculatorError(f"Argument ERROR: {label} requires {columns} values")
    return values


def parse_function(engine, text, label="function") -> str:
    raw = str(text).strip()
    if not raw:
        raise CalculatorError(f"Argument ERROR: {label} is required")
    import sympy as sp

    try:
        symbol = sp.Symbol("x")
        engine.parse(raw, {"x": symbol})
    except CalculatorError:
        raise
    except Exception as exc:
        raise CalculatorError(f"Syntax ERROR: {label}") from exc
    return raw


def parse_field(engine, spec, raw):
    """Convert entered text into the value the field's declared type requires."""
    kind = spec.get("type", "text")
    label = spec.get("label", spec["key"])
    if kind == "number":
        return parse_real(engine, raw, label, minimum=spec.get("minimum"), maximum=spec.get("maximum"))
    if kind == "integer":
        return parse_real(
            engine, raw, label, integer=True, minimum=spec.get("minimum"), maximum=spec.get("maximum")
        )
    if kind == "numbers":
        return parse_numbers(engine, raw, label)
    if kind == "matrix_row":
        return parse_matrix_row(engine, raw, spec)
    if kind == "function":
        return parse_function(engine, raw, label)
    if kind == "choice":
        candidate = str(raw).strip()
        folded = candidate.casefold()
        labels = spec.get("choice_labels", {})
        for _number, choice_value in spec["choices"].items():
            display = labels.get(choice_value)
            if folded in {
                str(choice_value).casefold(),
                str(display).casefold() if display is not None else "",
            }:
                return choice_value
        choice = parse_real(engine, candidate, label, integer=True)
        if choice not in spec["choices"]:
            raise CalculatorError(f"Argument ERROR: choose one of {', '.join(map(str, spec['choices']))}")
        return spec["choices"][choice]
    if kind == "raw":
        return str(raw)
    return str(raw).strip()


__all__ = [
    "action_choice_field",
    "array_lines",
    "choice_field",
    "field_text",
    "matrix_row_tokens",
    "number_field",
    "number_text",
    "parse_field",
    "parse_function",
    "parse_matrix_row",
    "parse_numbers",
    "parse_real",
    "real_expression",
]
