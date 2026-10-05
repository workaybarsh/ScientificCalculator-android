"""Unit-conversion catalogue and safe, stateless conversion service."""

from __future__ import annotations

from collections.abc import Callable

from ..errors import CalculatorError
from ..numeric_validation import finite_real_float

Conversion = Callable[[float], float]

# Keep this mutable compatibility catalogue: integrations historically add a
# conversion at runtime, while the conversion operation itself stays pure.
CONVERSIONS: dict[str, Conversion] = {
    "in→cm": lambda x: x * 2.54, "cm→in": lambda x: x / 2.54,
    "ft→m": lambda x: x * 0.3048, "m→ft": lambda x: x / 0.3048,
    "yd→m": lambda x: x * 0.9144, "m→yd": lambda x: x / 0.9144,
    "mile→km": lambda x: x * 1.609344, "km→mile": lambda x: x / 1.609344,
    "n mile→m": lambda x: x * 1852.0, "m→n mile": lambda x: x / 1852.0,
    "pc→km": lambda x: x * 3.0856775814913673e13, "km→pc": lambda x: x / 3.0856775814913673e13,
    "acre→m²": lambda x: x * 4046.8564224, "m²→acre": lambda x: x / 4046.8564224,
    "gal(US)→L": lambda x: x * 3.785411784, "L→gal(US)": lambda x: x / 3.785411784,
    "gal(UK)→L": lambda x: x * 4.54609, "L→gal(UK)": lambda x: x / 4.54609,
    "oz→g": lambda x: x * 28.349523125, "g→oz": lambda x: x / 28.349523125,
    "lb→kg": lambda x: x * 0.45359237, "kg→lb": lambda x: x / 0.45359237,
    "km/h→m/s": lambda x: x / 3.6, "m/s→km/h": lambda x: x * 3.6,
    "atm→Pa": lambda x: x * 101325.0, "Pa→atm": lambda x: x / 101325.0,
    "mmHg→Pa": lambda x: x * 133.322387415, "Pa→mmHg": lambda x: x / 133.322387415,
    "kgf/cm²→Pa": lambda x: x * 98066.5, "Pa→kgf/cm²": lambda x: x / 98066.5,
    "lbf/in²→kPa": lambda x: x * 6.894757293168, "kPa→lbf/in²": lambda x: x / 6.894757293168,
    "kgf·m→J": lambda x: x * 9.80665, "J→kgf·m": lambda x: x / 9.80665,
    "J→cal": lambda x: x / 4.1855, "cal→J": lambda x: x * 4.1855,
    "hp→kW": lambda x: x * 0.7456998715822702, "kW→hp": lambda x: x / 0.7456998715822702,
    "°F→°C": lambda x: (x - 32) * 5 / 9, "°C→°F": lambda x: x * 9 / 5 + 32,
}


def convert_value(name: object, value: object, *, conversions: dict[str, Conversion] = CONVERSIONS) -> float:
    """Convert one finite real value without reading or mutating engine state."""
    if not isinstance(name, str):
        raise CalculatorError("Argument ERROR")
    try:
        converter = conversions[name]
    except KeyError as exc:
        raise CalculatorError("Argument ERROR") from exc
    numeric_value = finite_real_float(value, "Math ERROR: conversion input must be finite and real")
    try:
        result = converter(numeric_value)
    except (TypeError, ValueError, OverflowError, ZeroDivisionError) as exc:
        raise CalculatorError("Math ERROR: conversion could not be completed") from exc
    return finite_real_float(result, "Math ERROR: conversion result must be finite and real")
