"""Shared finite-number validation for calculator operations."""
from __future__ import annotations

import math
import sys
from typing import Any, cast

import numpy as np

from .errors import CalculatorError


def _sympy():
    """Return SymPy only when it is already loaded.

    A value cannot be a SymPy object unless SymPy has been imported, so these
    checks can answer without paying a 0.6 second import that the calculator's
    startup would otherwise incur before its window appears.
    """
    return sys.modules.get("sympy")


def is_known_nonfinite(value: object) -> bool:
    """Return True only when a mathematical result is definitively non-finite."""
    try:
        sp = _sympy()
        if sp is not None and isinstance(value, sp.Basic):
            # ``sp`` is looked up dynamically (see ``_sympy``) so pyright sees
            # ``sp.Basic`` as an unknown class and cannot narrow ``value``
            # through this ``isinstance`` check on its own.
            basic_value = cast(Any, value)
            if basic_value.has(sp.zoo, sp.nan, sp.oo, -sp.oo):
                return True
            return basic_value.is_finite is False
        if isinstance(value, (complex, np.complexfloating)):
            return not (math.isfinite(float(value.real)) and math.isfinite(float(value.imag)))
        if isinstance(value, (float, np.floating)):
            return not math.isfinite(float(value))
        if isinstance(value, np.number):
            return not math.isfinite(float(value))
        # Python/SymPy integers and fractions are exact and finite regardless
        # of whether conversion to a machine float would overflow.
        return False
    except (TypeError, ValueError, OverflowError):
        return True


def require_finite_math_result(value: object, message: str = "Math ERROR: sonuç sonlu değil") -> None:
    if is_known_nonfinite(value):
        raise CalculatorError(message)


def finite_real_float(value: object, message: str) -> float:
    """Convert a fully numeric, finite real value without accepting symbols."""
    require_finite_math_result(value, message)
    try:
        sp = _sympy()
        if sp is not None and isinstance(value, sp.Basic):
            basic_value = cast(Any, value)
            if basic_value.free_symbols or basic_value.is_number is not True:
                raise CalculatorError(message)
            numeric = sp.N(basic_value, 30)
            if numeric.is_real is not True:
                raise CalculatorError(message)
            result = float(numeric)
        elif isinstance(value, (complex, np.complexfloating)):
            if float(value.imag) != 0:
                raise CalculatorError(message)
            result = float(value.real)
        elif isinstance(value, bool):
            raise CalculatorError(message)
        else:
            # A caller-supplied ``int``, ``Fraction``, or ``np.number`` reaches
            # here; each supports ``__float__`` and the surrounding ``try``
            # converts a genuine mismatch into ``CalculatorError`` below.
            result = float(cast(Any, value))
    except CalculatorError:
        raise
    except (TypeError, ValueError, OverflowError) as exc:
        raise CalculatorError(message) from exc
    if not math.isfinite(result):
        raise CalculatorError(message)
    return result


def finite_complex(value: object, message: str) -> complex:
    """Convert a fully numeric finite value while retaining a non-real part."""
    require_finite_math_result(value, message)
    try:
        sp = _sympy()
        if sp is not None and isinstance(value, sp.Basic):
            basic_value = cast(Any, value)
            if basic_value.free_symbols or basic_value.is_number is not True:
                raise CalculatorError(message)
            result = complex(sp.N(basic_value, 30))
        elif isinstance(value, bool):
            raise CalculatorError(message)
        else:
            result = complex(cast(Any, value))
    except CalculatorError:
        raise
    except (TypeError, ValueError, OverflowError) as exc:
        raise CalculatorError(message) from exc
    if not (math.isfinite(result.real) and math.isfinite(result.imag)):
        raise CalculatorError(message)
    return result
