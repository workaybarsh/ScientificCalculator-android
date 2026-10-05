"""State-free equation, inequality, polynomial, and ratio calculations."""

from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Any, cast

import numpy as np
import sympy as sp

from ..errors import CalculatorError
from ..numeric_validation import finite_real_float
from .bounded_collections import bounded_iterable


def solve_simultaneous(values: object, constants: object, maximum_dimension: int) -> np.ndarray:
    """Solve a bounded square simultaneous-equation system."""
    try:
        raw_values = bounded_iterable(
            values,
            maximum=maximum_dimension,
            invalid_message="Argument ERROR: geçersiz denklem verisi",
            limit_message="Argument ERROR: too many simultaneous-equation values",
            array_maximum=maximum_dimension**2,
        )
        raw_constants = bounded_iterable(
            constants,
            maximum=maximum_dimension,
            invalid_message="Argument ERROR: geçersiz denklem verisi",
            limit_message="Argument ERROR: too many simultaneous-equation values",
        )
        if not isinstance(raw_values, np.ndarray):
            raw_values = [
                bounded_iterable(
                    row,
                    maximum=maximum_dimension,
                    invalid_message="Argument ERROR: geçersiz denklem verisi",
                    limit_message="Argument ERROR: too many simultaneous-equation values",
                )
                if isinstance(row, Iterable) and not isinstance(row, (str, bytes))
                else row
                for row in raw_values
            ]
        coefficient_matrix = np.asarray(raw_values, dtype=float)
        result_vector = np.asarray(raw_constants, dtype=float)
    except CalculatorError:
        raise
    except (TypeError, ValueError, OverflowError) as exc:
        raise CalculatorError("Argument ERROR: geçersiz denklem verisi") from exc
    if (
        coefficient_matrix.ndim != 2
        or coefficient_matrix.shape[0] != coefficient_matrix.shape[1]
        or coefficient_matrix.shape[0] not in (2, 3, 4)
        or result_vector.shape != (coefficient_matrix.shape[0],)
    ):
        raise CalculatorError("Dimension ERROR")
    if not np.all(np.isfinite(coefficient_matrix)) or not np.all(np.isfinite(result_vector)):
        raise CalculatorError("Math ERROR: denklem verileri sonlu olmalıdır")
    try:
        solution = np.linalg.solve(coefficient_matrix, result_vector)
    except np.linalg.LinAlgError as exc:
        raise CalculatorError("Math ERROR") from exc
    if not np.all(np.isfinite(solution)):
        raise CalculatorError("Math ERROR: denklem sonucu sonlu değil")
    return solution


def polynomial_roots(coefficients: object, maximum_coefficients: int, include_complex: bool) -> np.ndarray:
    """Return roots for a degree-two through degree-four polynomial."""
    try:
        values = [
            complex(cast(Any, value))
            for value in bounded_iterable(
                coefficients,
                maximum=maximum_coefficients,
                invalid_message="Argument ERROR",
                limit_message="Argument ERROR: too many polynomial coefficients",
            )
        ]
    except CalculatorError:
        raise
    except (TypeError, ValueError, OverflowError) as exc:
        raise CalculatorError("Argument ERROR") from exc
    if len(values) - 1 not in (2, 3, 4):
        raise CalculatorError("Argument ERROR")
    if any(not (math.isfinite(value.real) and math.isfinite(value.imag)) for value in values):
        raise CalculatorError("Math ERROR: polynomial coefficients must be finite")
    if values[0] == 0:
        raise CalculatorError("Argument ERROR: polynomial leading coefficient must not be zero")
    roots = np.roots(values)
    if not include_complex:
        roots = np.array([root.real for root in roots if abs(root.imag) <= np.finfo(float).eps * max(1.0, abs(root.real))])
    return roots


def solve_inequality(coefficients: object, relation: str, maximum_coefficients: int) -> sp.Expr:
    """Solve one supported real polynomial inequality."""
    try:
        values = [
            float(cast(Any, value))
            for value in bounded_iterable(
                coefficients,
                maximum=maximum_coefficients,
                invalid_message="Argument ERROR",
                limit_message="Argument ERROR: too many inequality coefficients",
            )
        ]
    except CalculatorError:
        raise
    except (TypeError, ValueError, OverflowError) as exc:
        raise CalculatorError("Argument ERROR") from exc
    if len(values) - 1 not in (1, 2, 3, 4):
        raise CalculatorError("Argument ERROR")
    if not all(math.isfinite(value) for value in values):
        raise CalculatorError("Math ERROR: inequality coefficients must be finite")
    if values[0] == 0:
        raise CalculatorError("Argument ERROR: inequality leading coefficient must not be zero")
    if relation not in {">", "<", "≥", "<=", "≤", ">="}:
        raise CalculatorError("Argument ERROR")
    symbol = sp.Symbol("x", real=True)
    polynomial = sum(sp.Float(value) * symbol ** (len(values) - 1 - index) for index, value in enumerate(values))
    comparisons = {
        ">": polynomial > 0,
        "<": polynomial < 0,
        "≥": polynomial >= 0,
        "<=": polynomial <= 0,
        "≤": polynomial <= 0,
        ">=": polynomial >= 0,
    }
    return cast(sp.Expr, sp.reduce_inequalities(comparisons[relation], symbol))


def solve_ratio(kind: str, parameters: dict[str, object]) -> float:
    """Solve one supported proportional-ratio form."""
    def finite(name: str) -> float:
        try:
            return finite_real_float(parameters[name], "Math ERROR: oran değerleri sonlu reel olmalıdır")
        except KeyError as exc:
            raise CalculatorError("Argument ERROR: oran değeri eksik") from exc

    if kind == "A:B=X:D":
        left, denominator, right = finite("A"), finite("B"), finite("D")
        if denominator == 0:
            raise CalculatorError("Math ERROR")
        result = left * right / denominator
    elif kind == "A:B=C:X":
        denominator, left, right = finite("A"), finite("B"), finite("C")
        if denominator == 0:
            raise CalculatorError("Math ERROR")
        result = left * right / denominator
    else:
        raise CalculatorError("Argument ERROR: unsupported ratio form")
    if not math.isfinite(result):
        raise CalculatorError("Math ERROR: oran sonucu sonlu değil")
    return result
