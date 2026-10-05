"""Stateless conversion between calculator angle units and radians."""

from __future__ import annotations

import sympy as sp

# Every safe-parser result (``int | float | complex``) and every SymPy
# expression the calculus bindings pass through (``sp.Expr``) supports the
# multiplication and division used below; the bare ``sp.Basic`` base class
# does not define arithmetic operators.
Numeric = sp.Expr | int | float | complex


def angle_to_radians(value: Numeric, angle_unit: str) -> Numeric:
    """Convert a calculator angle to radians without retaining settings state."""
    if angle_unit == "DEG":
        return value * sp.pi / 180
    if angle_unit == "GRA":
        return value * sp.pi / 200
    return value


def radians_to_angle(value: Numeric, angle_unit: str) -> Numeric:
    """Convert radians to the selected calculator angle unit."""
    if angle_unit == "DEG":
        return value * 180 / sp.pi
    if angle_unit == "GRA":
        return value * 200 / sp.pi
    return value
