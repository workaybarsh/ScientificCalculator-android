"""Presentation-safe formatting for calculator values.

The formatter owns no calculator state.  The compatibility facade supplies the
small trusted callbacks needed for polar conversion and bounded CAS simplify
work, keeping UI-specific settings out of the calculation core.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from decimal import Decimal
from typing import Any, Protocol, cast

import numpy as np
import sympy as sp

from ..errors import CalculatorError


class ResultFormatSettings(Protocol):
    decimal_mark: str
    number_format: str
    number_digits: int
    engineer_symbol: bool
    digit_separator: bool
    complex_format: str
    input_output: str


PolarConverter = Callable[[complex], tuple[float, float]]
CASRunner = Callable[[str, dict[str, object]], object]
ExactBudgetChecker = Callable[[object], None]


class ResultFormatter:
    """Render numeric and symbolic results from an immutable settings view."""

    def __init__(
        self,
        settings: ResultFormatSettings,
        *,
        to_polar: PolarConverter,
        run_cas: CASRunner,
        require_exact_display_budget: ExactBudgetChecker,
    ) -> None:
        self._settings = settings
        self._to_polar = to_polar
        self._run_cas = run_cas
        self._require_exact_display_budget = require_exact_display_budget

    def _exact_scalar(self, value: object) -> str:
        self._require_exact_display_budget(value)
        return str(value).replace("sqrt", "√").replace("**", "^")

    def _localize_numeric_text(self, text: str, *, group_integer: bool) -> str:
        """Apply output locale without confusing grouping and decimal marks."""
        sign = ""
        if text[:1] in "+-":
            sign, text = text[:1], text[1:]
        exponent_index = next((index for index, character in enumerate(text) if character in "eE"), -1)
        if exponent_index >= 0:
            coefficient, exponent = text[:exponent_index], text[exponent_index:]
        else:
            coefficient, exponent = text, ""
        integer, separator, fraction = coefficient.partition(".")
        if group_integer:
            grouping_mark = "." if self._settings.decimal_mark == "Comma" else ","
            integer = f"{int(integer):,}".replace(",", grouping_mark)
        decimal_mark = "," if self._settings.decimal_mark == "Comma" else "."
        return sign + integer + (decimal_mark + fraction if separator else "") + exponent

    def _standard_numeric_text(self, value: float, *, engineering: bool = False) -> str:
        mode = self._settings.number_format
        digits = self._settings.number_digits
        if value == 0:
            return "0"
        if mode != "Sci" and abs(value) < 1e-6:
            return format(Decimal(str(value)), "f")
        if mode == "Fix":
            return f"{value:.{digits}f}"
        if mode == "Sci" and not engineering:
            return f"{value:.{max(0, digits - 1)}e}"
        if mode == "Sci":
            return f"{value:.{max(1, digits)}g}"
        return f"{value:.12g}"

    def _numeric_part(self, value: object) -> str:
        numeric = float(cast(Any, value))
        if not math.isfinite(numeric):
            raise CalculatorError("Math ERROR: sayısal sonuç görüntüleme aralığını aşıyor")

        if numeric and self._settings.engineer_symbol:
            exponent = 3 * math.floor(math.log10(abs(numeric)) / 3)
            if -15 <= exponent <= 18:
                scaled = numeric / (10**exponent)
                text = self._standard_numeric_text(scaled, engineering=True)
                if abs(float(text)) >= 1000 and exponent < 18:
                    exponent += 3
                    text = self._standard_numeric_text(numeric / (10**exponent), engineering=True)
                prefix = {
                    -15: "f", -12: "p", -9: "n", -6: "μ", -3: "m", 0: "",
                    3: "k", 6: "M", 9: "G", 12: "T", 15: "P", 18: "E",
                }[exponent]
                return self._localize_numeric_text(text, group_integer=False) + prefix

        text = self._standard_numeric_text(numeric)
        return self._localize_numeric_text(
            text,
            group_integer=self._settings.digit_separator and "e" not in text.lower(),
        )

    def format(self, value: object, approximate: bool = False) -> str:
        """Format a finite numeric, symbolic, complex, or matrix result."""
        if isinstance(value, np.ndarray):
            separator = "; " if self._settings.decimal_mark == "Comma" else ", "
            return np.array2string(
                value,
                separator=separator,
                formatter={"float_kind": self._numeric_part, "int_kind": self._numeric_part},
            )

        if isinstance(value, complex):
            if abs(value.imag) < 1e-12:
                value = value.real
            else:
                if self._settings.complex_format == "r∠θ":
                    radius, angle = self._to_polar(value)
                    return f"{self._numeric_part(radius)}∠{self._numeric_part(angle)}"
                imaginary = self._numeric_part(abs(value.imag))
                if abs(value.real) < 1e-12:
                    return f"{'-' if value.imag < 0 else ''}{imaginary}i"
                real = self._numeric_part(value.real)
                sign = "+" if value.imag >= 0 else "-"
                return f"{real}{sign}{imaginary}i"

        if isinstance(value, sp.Basic):
            if isinstance(value, sp.Equality):
                return f"{self._exact_scalar(value.lhs)} = {self._exact_scalar(value.rhs)}"
            if value.has(sp.I):
                if not approximate and self._settings.input_output in ("MathI/MathO", "LineI/LineO"):
                    real = self._run_cas("simplify", {"expression": sp.re(value)})
                    imaginary = self._run_cas("simplify", {"expression": sp.im(value)})
                    if isinstance(imaginary, sp.Basic) and imaginary.is_zero is True:
                        return self._exact_scalar(real)
                    if not isinstance(real, sp.Basic) or not isinstance(imaginary, sp.Basic):
                        raise CalculatorError("Math ERROR: karmaşık sonuç sadeleştirilemedi")
                    real_is_zero = real.is_zero is True
                    if imaginary.is_nonnegative is True:
                        sign, imaginary_absolute = ("" if real_is_zero else "+"), imaginary
                    elif imaginary.is_negative is True:
                        sign, imaginary_absolute = "-", sp.Mul(-1, cast(sp.Expr, imaginary))
                    else:
                        return re.sub(r"\bI\b", "i", self._exact_scalar(value))
                    real_text = "" if real_is_zero else self._exact_scalar(real)
                    imaginary_absolute = self._run_cas("simplify", {"expression": imaginary_absolute})
                    imaginary_text = "i" if imaginary_absolute == 1 else self._exact_scalar(imaginary_absolute) + "i"
                    return f"{real_text}{sign}{imaginary_text}"
                return self.format(complex(sp.N(value, 15)))
            if approximate or self._settings.input_output in ("MathI/DecimalO", "LineI/DecimalO"):
                value = float(sp.N(value, 15))
            else:
                return self._exact_scalar(value)

        try:
            numeric = float(cast(Any, value))
            if not math.isfinite(numeric):
                raise CalculatorError("Math ERROR: sayısal sonuç görüntüleme aralığını aşıyor")
            return self._numeric_part(numeric)
        except CalculatorError:
            raise
        except Exception:
            return str(value)


__all__ = ["ResultFormatter"]
