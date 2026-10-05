"""State-free statistical summary calculations."""

from __future__ import annotations

import bisect
import math
from collections.abc import Callable, Sequence

import numpy as np

from ..errors import CalculatorError

IntegerValidator = Callable[[object, str], int]


def one_variable_statistics(
    values: np.ndarray,
    frequencies: Sequence[object] | np.ndarray | None,
    maximum_frequency: int,
    integer_validator: IntegerValidator,
) -> dict[str, float | int]:
    """Summarize finite values, optionally using exact bounded frequencies."""
    if frequencies is not None:
        if len(frequencies) != len(values):
            raise CalculatorError("Dimension ERROR")
        weights = []
        for value in frequencies:
            weight = integer_validator(value, "Argument ERROR: frekanslar negatif olmayan tam sayı olmalıdır")
            if weight < 0 or weight > maximum_frequency:
                raise CalculatorError("Argument ERROR: frekanslar güvenli tam sayı aralığında olmalıdır")
            weights.append(weight)
        total = sum(weights)
        if total <= 0:
            raise CalculatorError("Argument ERROR: toplam frekans pozitif olmalıdır")
        if total > maximum_frequency:
            raise CalculatorError("Argument ERROR: toplam frekans güvenli tam sayı aralığında olmalıdır")
        weight_array = np.asarray(weights, dtype=float)
        mean = float(np.sum(values * weight_array) / total)
        variance = float(np.sum(weight_array * (values - mean) ** 2) / total)
        sample_variance = (
            float(np.sum(weight_array * (values - mean) ** 2) / (total - 1)) if total > 1 else float("nan")
        )
        order = np.argsort(values)
        sorted_values = values[order]
        cumulative = []
        running = 0
        for position in order:
            running += weights[int(position)]
            cumulative.append(running)

        def weighted_value(position: int) -> float:
            return float(sorted_values[bisect.bisect_left(cumulative, position)])

        def midpoint_percentile(percent: int) -> float:
            position = (total - 1) * percent / 100
            return (weighted_value(math.floor(position) + 1) + weighted_value(math.ceil(position) + 1)) / 2

        q1, median, q3 = (midpoint_percentile(percent) for percent in (25, 50, 75))
        result: dict[str, float | int] = {
            "n": total,
            "Σx": float(np.sum(values * weight_array)),
            "Σx²": float(np.sum(values * values * weight_array)),
            "x̄": mean,
            "σx²": variance,
            "σx": math.sqrt(variance),
            "sx²": sample_variance,
            "sx": math.sqrt(sample_variance) if total > 1 else float("nan"),
            "min(x)": float(values.min()),
            "Q1": q1,
            "Med": median,
            "Q3": q3,
            "max(x)": float(values.max()),
        }
    else:
        with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
            q1, median, q3 = np.percentile(values, [25, 50, 75], method="midpoint")
            result = {
                "n": len(values),
                "Σx": values.sum(),
                "Σx²": np.sum(values * values),
                "x̄": values.mean(),
                "σx²": values.var(ddof=0),
                "σx": values.std(ddof=0),
                "sx²": values.var(ddof=1) if len(values) > 1 else float("nan"),
                "sx": values.std(ddof=1) if len(values) > 1 else float("nan"),
                "min(x)": values.min(),
                "Q1": q1,
                "Med": median,
                "Q3": q3,
                "max(x)": values.max(),
            }
    for name, value in result.items():
        if name in {"sx²", "sx"} and result["n"] == 1 and math.isnan(float(value)):
            continue
        if not math.isfinite(float(value)):
            raise CalculatorError("Math ERROR: istatistik sonucu sonlu değil")
    return result
