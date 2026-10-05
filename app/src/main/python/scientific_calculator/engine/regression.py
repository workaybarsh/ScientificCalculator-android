"""Pure regression fitting and normal-distribution helper functions."""

from __future__ import annotations

import math
import warnings
from collections.abc import Callable
from typing import Any

import numpy as np

from ..errors import CalculatorError

RegressionResult = dict[str, float | None | Callable[[Any], Any]]


def _stats():
    """Import SciPy on first use: it costs about a second at startup."""
    from scipy import stats

    return stats


def regression_fit(x: np.ndarray, y: np.ndarray, kind: str) -> RegressionResult:
    """Fit a supported regression without relying on calculator state."""
    if kind not in {"linear", "quadratic", "log", "exp_e", "exp_b", "power", "inverse"}:
        raise CalculatorError("Argument ERROR")

    transformed_x = x
    transformed_y = y
    if kind in {"log", "power"}:
        if np.any(x <= 0):
            raise CalculatorError("Math ERROR")
        transformed_x = np.log(x)
    elif kind == "inverse":
        if np.any(x == 0):
            raise CalculatorError("Math ERROR")
        with np.errstate(over="ignore", divide="ignore", invalid="ignore"):
            transformed_x = 1 / x
    if kind in {"exp_e", "exp_b", "power"}:
        if np.any(y <= 0):
            raise CalculatorError("Math ERROR")
        transformed_y = np.log(y)
    if not np.all(np.isfinite(transformed_x)) or not np.all(np.isfinite(transformed_y)):
        raise CalculatorError("Math ERROR: dönüştürülmüş regresyon verileri sonlu olmalıdır")

    degree = 2 if kind == "quadratic" else 1
    if np.unique(transformed_x).size < degree + 1:
        raise CalculatorError("Math ERROR: bağımsız veri çeşitliliği yetersiz")
    rank_warning = getattr(getattr(np, "exceptions", np), "RankWarning", Warning)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", rank_warning)
            coefficients = np.polyfit(transformed_x, transformed_y, degree)
    except (ValueError, FloatingPointError, np.linalg.LinAlgError, rank_warning) as exc:
        raise CalculatorError("Math ERROR: regresyon hesaplanamadı") from exc
    if not np.all(np.isfinite(coefficients)):
        raise CalculatorError("Math ERROR: regresyon katsayıları sonlu değil")

    if kind == "quadratic":
        quadratic, linear, constant = coefficients
        return {
            "a": constant,
            "b": linear,
            "c": quadratic,
            "predict": lambda values: constant + linear * values + quadratic * values * values,
        }
    slope, intercept = coefficients
    if kind == "linear":
        with np.errstate(divide="ignore", invalid="ignore"):
            correlation = np.corrcoef(x, y)[0, 1]
        if not np.isfinite(correlation):
            correlation = None
        return {"a": intercept, "b": slope, "r": correlation, "predict": lambda values: intercept + slope * values}
    if kind == "log":
        return {"a": intercept, "b": slope, "predict": lambda values: intercept + slope * np.log(values)}
    if kind == "inverse":
        return {"a": intercept, "b": slope, "predict": lambda values: intercept + slope / values}
    with np.errstate(over="ignore", invalid="ignore"):
        scale = np.exp(intercept)
        base = np.exp(slope) if kind == "exp_b" else None
    if not math.isfinite(float(scale)) or (base is not None and not math.isfinite(float(base))):
        raise CalculatorError("Math ERROR: regresyon katsayıları sonlu değil")
    if kind == "exp_e":
        return {"a": scale, "b": slope, "predict": lambda values: scale * np.exp(slope * values)}
    if kind == "exp_b":
        return {"a": scale, "b": base, "predict": lambda values: scale * (base**values)}
    return {"a": scale, "b": slope, "predict": lambda values: scale * (values**slope)}


def normal_p(value: object) -> float:
    return float(_stats().norm.cdf(value))


def normal_q(value: object) -> float:
    return float(_stats().norm.cdf(value) - 0.5)


def normal_r(value: object) -> float:
    return float(_stats().norm.sf(value))
