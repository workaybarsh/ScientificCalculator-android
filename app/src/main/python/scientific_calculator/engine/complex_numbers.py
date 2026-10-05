"""Calculator polar/rectangular primitives independent from UI state."""

from __future__ import annotations

import cmath
import math

from ..errors import CalculatorError

# What ``complex()``/``math.radians()``/``cmath.rect()`` accept, and the same
# set every caller and regression test passes: a Python ``int``, ``float``,
# or ``complex``.
Numeric = int | float | complex


def complex_argument(value: Numeric, angle_unit: str) -> float:
    """Return an argument in the requested unit, rejecting arg(0)."""
    number = complex(value)
    if number == 0:
        raise CalculatorError("Math ERROR: arg(0) tanımsızdır")
    angle = cmath.phase(number)
    if angle_unit == "DEG":
        return math.degrees(angle)
    if angle_unit == "GRA":
        return angle * 200 / math.pi
    return angle


def to_polar(value: Numeric, angle_unit: str) -> tuple[float, float]:
    """Return calculator polar coordinates, retaining the explicit zero convention."""
    number = complex(value)
    return (0.0, 0.0) if number == 0 else (abs(number), complex_argument(number, angle_unit))


def from_polar(radius: int | float, angle: int | float, angle_unit: str) -> complex:
    """Return rectangular coordinates from calculator polar coordinates."""
    resolved_angle: int | float
    if angle_unit == "DEG":
        resolved_angle = math.radians(angle)
    elif angle_unit == "GRA":
        resolved_angle = angle * math.pi / 200
    else:
        resolved_angle = angle
    return cmath.rect(radius, resolved_angle)
