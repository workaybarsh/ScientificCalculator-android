"""Small calculator numeric utilities with explicit parsing dependencies."""

from __future__ import annotations

import math
import random
from collections.abc import Callable
from typing import Any, cast

import sympy as sp

from ..errors import CalculatorError

ParseValue = Callable[[str], sp.Expr]


def dms_from_decimal(value: float) -> tuple[float, int, float]:
    """Split degrees while preserving a negative zero degree component."""
    sign = -1 if value < 0 else 1
    magnitude = abs(value)
    degrees = int(magnitude)
    minutes = int((magnitude - degrees) * 60)
    seconds = ((magnitude - degrees) * 60 - minutes) * 60
    return math.copysign(float(degrees), sign), minutes, seconds


def decimal_from_dms(degrees: float, minutes: float, seconds: float) -> float:
    """Recombine DMS while preserving a negative signed-zero degree input."""
    sign = -1 if degrees < 0 or (degrees == 0 and math.copysign(1.0, float(degrees)) < 0) else 1
    return sign * (abs(degrees) + minutes / 60 + seconds / 3600)


def _parsed_integer(value: object, parse_text: ParseValue, *, message: str) -> int:
    try:
        parsed = parse_text(value) if isinstance(value, str) else sp.sympify(value)
    except Exception as exc:
        raise CalculatorError(message) from exc
    if (
        not isinstance(parsed, sp.Basic)
        or parsed.free_symbols
        or parsed.is_finite is not True
        or parsed.is_integer is not True
    ):
        raise CalculatorError(message)
    return int(cast(Any, parsed))


def prime_factorization(value: object, parse_text: ParseValue) -> dict[int, int]:
    """Factor a finite positive integer under the calculator's input limit."""
    integer = _parsed_integer(value, parse_text, message="Math ERROR: FACT requires a positive integer")
    if integer <= 0 or integer >= 10**10:
        raise CalculatorError("Math ERROR: FACT requires a positive integer of at most 10 digits")
    return sp.factorint(integer)


def random_number() -> float:
    """Return the calculator-compatible three-decimal random value."""
    return random.randint(0, 999) / 1000.0


def random_int(lower: object, upper: object, parse_text: ParseValue) -> int:
    """Return a random integer from validated finite inclusive bounds."""
    message = "Argument ERROR: RanInt bounds must be finite integers"
    first = _parsed_integer(lower, parse_text, message=message)
    second = _parsed_integer(upper, parse_text, message=message)
    if first > second:
        raise CalculatorError("Argument ERROR: lower bound exceeds upper bound")
    return random.randint(first, second)
