"""Validated probability-distribution calculations without engine state."""

from __future__ import annotations

import math
from typing import Any, cast

import numpy as np
import sympy as sp

from ..errors import CalculatorError


def _stats():
    """Import SciPy on first use: it costs about a second at startup."""
    from scipy import stats

    return stats


def _exact_nonnegative_integer(value: object, name: str) -> int:
    message = f"Argument ERROR: {name} negatif olmayan tam sayı olmalıdır"
    try:
        if isinstance(value, bool):
            raise ValueError("boolean is not an integer bound")
        if isinstance(value, (int, np.integer)) or (
            isinstance(value, (float, np.floating)) and math.isfinite(float(value)) and float(value).is_integer()
        ):
            result = int(value)
        elif (
            isinstance(value, sp.Basic)
            and not value.free_symbols
            and value.is_finite is True
            and value.is_integer is True
        ):
            result = int(cast(Any, value))
        else:
            raise ValueError("not a finite integer")
    except (TypeError, ValueError, OverflowError) as exc:
        raise CalculatorError(message) from exc
    if result < 0:
        raise CalculatorError(message)
    return result


def _finite_parameter(parameters: dict[str, object], name: str) -> float:
    try:
        value = float(cast(Any, parameters[name]))
    except (KeyError, TypeError, ValueError) as exc:
        raise CalculatorError(f"Argument ERROR: {name}") from exc
    if not math.isfinite(value):
        raise CalculatorError(f"Math ERROR: {name} sonlu olmalıdır")
    return value


def distribution(kind: str, parameters: dict[str, object]) -> float:
    """Calculate a supported distribution result with bounded domain checks."""
    try:
        if kind in {"Normal PD", "Normal CD", "Inverse Normal"}:
            mean = _finite_parameter(parameters, "mu")
            sigma = _finite_parameter(parameters, "sigma")
            if sigma <= 0:
                raise CalculatorError("Math ERROR: sigma pozitif olmalıdır")
            if kind == "Normal PD":
                result = _stats().norm.pdf(_finite_parameter(parameters, "x"), loc=mean, scale=sigma)
            elif kind == "Normal CD":
                lower = _finite_parameter(parameters, "lower")
                upper = _finite_parameter(parameters, "upper")
                if lower > upper:
                    raise CalculatorError("Argument ERROR: alt sınır üst sınırı aşamaz")
                standardized_lower = (lower - mean) / sigma
                standardized_upper = (upper - mean) / sigma
                if standardized_lower >= 0:
                    result = _stats().norm.sf(standardized_lower) - _stats().norm.sf(standardized_upper)
                elif standardized_upper <= 0:
                    result = _stats().norm.cdf(standardized_upper) - _stats().norm.cdf(standardized_lower)
                else:
                    result = _stats().norm.cdf(standardized_upper) + _stats().norm.sf(standardized_lower) - 1
            else:
                area = _finite_parameter(parameters, "area")
                if not 0 < area < 1:
                    raise CalculatorError("Argument ERROR: area 0 ile 1 arasında olmalıdır")
                result = _stats().norm.ppf(area, loc=mean, scale=sigma)
        elif kind in {"Binomial PD", "Binomial CD"}:
            x = _exact_nonnegative_integer(parameters.get("x"), "x") if "x" in parameters else _missing("x")
            trials = _exact_nonnegative_integer(parameters.get("N"), "N") if "N" in parameters else _missing("N")
            probability = _finite_parameter(parameters, "p")
            if not 0 <= probability <= 1:
                raise CalculatorError("Argument ERROR: p 0 ile 1 arasında olmalıdır")
            result = _stats().binom.pmf(x, trials, probability) if kind == "Binomial PD" else _stats().binom.cdf(x, trials, probability)
        elif kind in {"Poisson PD", "Poisson CD"}:
            x = _exact_nonnegative_integer(parameters.get("x"), "x") if "x" in parameters else _missing("x")
            rate = _finite_parameter(parameters, "lam")
            if rate < 0:
                raise CalculatorError("Argument ERROR: lambda negatif olamaz")
            result = _stats().poisson.pmf(x, rate) if kind == "Poisson PD" else _stats().poisson.cdf(x, rate)
        else:
            raise CalculatorError("Argument ERROR")
    except CalculatorError:
        raise
    except Exception as exc:
        raise CalculatorError("Math ERROR") from exc
    if not math.isfinite(float(result)):
        raise CalculatorError("Math ERROR: dağılım sonucu sonlu değil")
    return float(result)


def _missing(name: str) -> int:
    raise CalculatorError(f"Argument ERROR: {name}")
