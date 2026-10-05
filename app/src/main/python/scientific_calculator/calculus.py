"""Bounded real and complex calculus operations for the calculator engine.

The mixin deliberately depends on the engine's safe parser, CAS boundary,
history formatter, and state.  Keeping those stateful concerns in the engine
while isolating calculus policy makes the numerical/symbolic behavior easier
to review and test without changing its public API.
"""
from __future__ import annotations

import cmath
import math
import re
import string
import warnings
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from itertools import islice
from typing import TYPE_CHECKING, Any, Literal, cast, overload

import numpy as np
import sympy as sp

from .calculation_result import CalculationResult, ResultStatus
from .engine.outcomes import NO_ANS_UPDATE, EngineOutcome
from .errors import CalculatorError
from .history import CalculationHistoryEntry
from .numeric_validation import finite_complex as _finite_complex
from .numeric_validation import finite_real_float as _finite_real_float


def _integrate():
    """Import SciPy's integrators on first use.

    Importing scipy at module import cost roughly a second of startup, for a
    calculator session that may never evaluate a numeric integral.
    """
    import scipy.integrate

    return scipy.integrate



_COMPLEX_SCALAR_FUNCTIONS = {
    "Abs": abs,
    "abs": abs,
    "conj": lambda value: complex(value).conjugate(),
    "conjugate": lambda value: complex(value).conjugate(),
    "arg": cmath.phase,
}


_MAX_ODE_INITIAL_CONDITIONS = 3


class IntegralKind(StrEnum):
    """The real-domain evaluation route, independent from LCD wording."""

    PROPER = "proper"
    IMPROPER = "improper"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class IntegralDomainAnalysis:
    """Conservative real-domain classification for a single integral."""

    kind: IntegralKind
    lower: sp.Expr
    upper: sp.Expr
    singularities: tuple[sp.Expr, ...] = ()
    endpoint_singularities: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    domain_undefined: bool = False
    analysis_complete: bool = True


class CalculusMixin:
    """Calculus behavior mixed into :class:`ScientificCalculatorEngine`."""

    if TYPE_CHECKING:
        # This mixin is never instantiated on its own; ``ScientificCalculatorEngine``
        # supplies every method below.  Declaring their shape here (skipped
        # entirely at runtime, since ``TYPE_CHECKING`` is always ``False``) lets
        # pyright check this file's calls to the safe parser, CAS boundary,
        # and state-commit facade without duplicating their real bodies.
        def parse(self, text: str, extra: object = None) -> sp.Expr: ...

        def parse_symbolic(self, text: str, extra: object = None) -> sp.Expr: ...

        def symbolic_locals(self, extra: object = None) -> dict[str, object]: ...

        def _safe_parse(self, text: str, local_dict: dict[str, object]) -> sp.Expr: ...

        @staticmethod
        def normalize(text: str) -> str: ...

        def _run_cas(self, operation: str, payload: dict[str, object]) -> Any: ...

        def _commit_outcome(self, outcome: EngineOutcome) -> Any: ...

        def format_result(self, value: object, approximate: bool = False) -> str: ...

    @staticmethod
    def _validate_calculus_variable(variable: str, *, label: str = "Değişken") -> None:
        if not isinstance(variable, str) or len(variable) != 1 or not variable.isascii() or not variable.isalpha():
            raise CalculatorError(f"Syntax ERROR: {label} tek harf olmalıdır")

    @staticmethod
    def _calculus_symbol_locals(allowed: dict[str, sp.Symbol]) -> dict[str, sp.Symbol]:
        """Keep calculus variables symbolic instead of reading calculator memory.

        A path such as ``x(t)`` must not silently substitute a saved calculator
        memory value called ``x``.  All ordinary one-letter names therefore
        remain symbols until the operation explicitly validates its variables.
        Euler's ``e`` and the imaginary unit ``i`` retain their normal parser
        meanings.
        """
        locals_ = {
            letter: sp.Symbol(letter)
            for letter in string.ascii_letters
            if letter not in {"e", "i", "I"}
        }
        locals_.update(allowed)
        return locals_

    def _calculus_history_outcome(
        self,
        value: object,
        *,
        expression: str,
        rendered: str,
        kind: str,
        metadata: dict | None = None,
        ans: object = NO_ANS_UPDATE,
    ) -> EngineOutcome:
        """Describe a completed calculus operation without mutating engine state.

        The facade commits this immutable description only after the operation
        has fully succeeded.  Keeping history and ``Ans`` together prevents a
        partial calculus operation from leaking state into a caller or worker.
        """
        return EngineOutcome(
            value,
            ans=ans,
            history=(CalculationHistoryEntry(expression, rendered, kind, {} if metadata is None else metadata),),
        )

    def _parse_integral_bound(self, bound: str) -> sp.Expr:
        if not isinstance(bound, str):
            raise CalculatorError("Math ERROR: integral sınırı metin olmalıdır")
        aliases = {
            "inf": sp.oo, "+inf": sp.oo, "infinity": sp.oo, "+infinity": sp.oo,
            "∞": sp.oo, "+∞": sp.oo, "oo": sp.oo, "+oo": sp.oo,
            "-inf": -sp.oo, "-infinity": -sp.oo, "-∞": -sp.oo, "-oo": -sp.oo,
        }
        # Bounds arrive from both the physical keyboard (``-``) and the
        # calculator keypad (Unicode ``−``).  Normalize before checking the
        # infinity aliases so ``−∞`` never falls through to expression parsing.
        normalized = bound.strip().lower().replace(" ", "").replace("−", "-")
        if normalized in aliases:
            return aliases[normalized]
        result = self.parse(bound)
        if result.free_symbols:
            raise CalculatorError("Math ERROR: integral sınırı sayısal olmalıdır")
        return result

    @staticmethod
    def _integral_bound_float(bound: sp.Expr) -> float:
        if bound == sp.oo:
            return math.inf
        if bound == -sp.oo:
            return -math.inf
        return _finite_real_float(bound, "Math ERROR: integral sınırları sonlu reel olmalıdır")

    def _integral_segments(self, expr: sp.Expr, symbol: sp.Symbol, lower: sp.Expr, upper: sp.Expr):
        """Split known interior singularities so a Cauchy principal value is never accepted."""
        lo, hi = self._integral_bound_float(lower), self._integral_bound_float(upper)
        try:
            singular_set = self._run_cas("singularities", {"expression": expr, "symbol": symbol})
        except Exception:
            singular_set = sp.S.EmptySet
        points: list[tuple[float, sp.Expr]] = []
        if isinstance(singular_set, sp.FiniteSet):
            low, high = sorted((lo, hi))
            for point in singular_set:
                try:
                    point_value = _finite_real_float(point, "Math ERROR")
                except CalculatorError:
                    continue
                if low < point_value < high:
                    # ``FiniteSet`` iterates its elements as ``sp.Basic``; every
                    # concrete singularity found here is a numeric expression.
                    points.append((point_value, cast(sp.Expr, point)))
        points.sort(key=lambda item: item[0], reverse=lo > hi)
        boundaries = [lower, *(point for _, point in points), upper]
        return list(zip(boundaries, boundaries[1:], strict=False)), bool(points)

    @staticmethod
    def _is_finite_real_expression(value: object) -> bool:
        """Return whether a CAS value is a concrete finite real number."""
        if not isinstance(value, sp.Basic) or value.free_symbols:
            return False
        try:
            _finite_real_float(value, "Math ERROR")
        except CalculatorError:
            return False
        return True

    @staticmethod
    def _is_divergent_integral_value(value: object) -> bool:
        return isinstance(value, sp.Basic) and value.has(sp.oo, -sp.oo, sp.zoo, sp.nan)

    def _boundary_is_problematic(self, expr: sp.Expr, symbol: sp.Symbol, point: sp.Expr, direction: str) -> bool | None:
        """Classify an endpoint without confusing a removable point for a pole."""
        if point in {sp.oo, -sp.oo}:
            return True
        try:
            direct = sp.simplify(expr.subs(symbol, point))
        except Exception:
            direct = sp.nan
        if self._is_finite_real_expression(direct):
            return False
        try:
            limit = self._run_cas(
                "limit", {"expression": expr, "symbol": symbol, "point": point, "dir": direction}
            )
        except Exception:
            return None
        if self._is_finite_real_expression(limit):
            return False
        if self._has_unresolved_integral(limit) or isinstance(limit, sp.Limit):
            return None
        return True

    @staticmethod
    def _finite_set_points(value: object) -> tuple[sp.Expr, ...] | None:
        if value == sp.S.EmptySet:
            return ()
        if isinstance(value, sp.FiniteSet):
            # Every element of a numeric ``FiniteSet`` here is a concrete
            # expression; ``FiniteSet`` itself only declares ``Basic`` members.
            return cast(tuple[sp.Expr, ...], tuple(sorted(value, key=lambda item: float(sp.N(item)))))
        return None

    def _analyze_integral_domain(
        self, expr: sp.Expr, symbol: sp.Symbol, lower: sp.Expr, upper: sp.Expr
    ) -> IntegralDomainAnalysis:
        """Conservatively separate proper, improper, undefined, and unknown inputs.

        A failed CAS query is deliberately *not* treated as an empty singularity
        set.  This keeps a later numerical approximation from accidentally
        proving convergence or accepting a principal value.
        """
        if lower > upper:
            lower, upper = upper, lower
        reasons: list[str] = []
        endpoint_reasons: list[str] = []
        try:
            domain = self._run_cas(
                "continuous_domain", {"expression": expr, "symbol": symbol, "domain": sp.S.Reals}
            )
            interval = sp.Interval.open(lower, upper)
            missing = sp.simplify(interval - domain)
            missing_points = self._finite_set_points(missing)
            if missing_points is None:
                pieces = missing.args if isinstance(missing, sp.Union) else (missing,)
                if any(isinstance(piece, sp.Interval) and piece.measure > 0 for piece in pieces):
                    return IntegralDomainAnalysis(
                        IntegralKind.UNKNOWN,
                        lower,
                        upper,
                        reasons=("outside_real_domain",),
                        domain_undefined=True,
                    )
        except Exception:
            return IntegralDomainAnalysis(
                IntegralKind.UNKNOWN, lower, upper, reasons=("real_domain_analysis_failed",), analysis_complete=False
            )
        try:
            singular_set = self._run_cas("singularities", {"expression": expr, "symbol": symbol})
            singular_points = self._finite_set_points(singular_set.intersect(interval))
        except Exception:
            if missing_points is None or not missing_points:
                return IntegralDomainAnalysis(
                    IntegralKind.UNKNOWN, lower, upper, reasons=("singularity_analysis_failed",), analysis_complete=False
                )
            singular_points = ()
        if singular_points is None:
            return IntegralDomainAnalysis(
                IntegralKind.UNKNOWN, lower, upper, reasons=("non_finite_singularity_set",), analysis_complete=False
            )
        if missing_points is None:
            # SymPy retains some periodic complements symbolically.  A finite
            # intersection with the requested interval is nevertheless a
            # complete, safe singularity description (for example tan(x) on
            # 0..pi has only pi/2).
            missing_points = singular_points
        candidates = set(missing_points) | set(singular_points)
        try:
            interior = tuple(
                sorted((point for point in candidates if lower < point < upper), key=lambda item: float(sp.N(item)))
            )
        except (TypeError, ValueError):
            return IntegralDomainAnalysis(
                IntegralKind.UNKNOWN, lower, upper, reasons=("non_real_singularity",), analysis_complete=False
            )
        problematic: list[sp.Expr] = []
        for point in interior:
            left = self._boundary_is_problematic(expr, symbol, point, "-")
            right = self._boundary_is_problematic(expr, symbol, point, "+")
            if left is None or right is None:
                return IntegralDomainAnalysis(
                    IntegralKind.UNKNOWN, lower, upper, reasons=("interior_limit_undetermined",), analysis_complete=False
                )
            if left or right:
                problematic.append(point)
                reasons.append("interior_singularity")
        lower_problem = self._boundary_is_problematic(expr, symbol, lower, "+")
        upper_problem = self._boundary_is_problematic(expr, symbol, upper, "-")
        if lower_problem is None or upper_problem is None:
            return IntegralDomainAnalysis(
                IntegralKind.UNKNOWN, lower, upper, reasons=("endpoint_limit_undetermined",), analysis_complete=False
            )
        if lower_problem:
            endpoint_reasons.append("lower_endpoint")
            reasons.append("infinite_lower_bound" if lower == -sp.oo else "endpoint_singularity")
        if upper_problem:
            endpoint_reasons.append("upper_endpoint")
            reasons.append("infinite_upper_bound" if upper == sp.oo else "endpoint_singularity")
        if problematic or lower_problem or upper_problem:
            return IntegralDomainAnalysis(
                IntegralKind.IMPROPER, lower, upper, tuple(problematic), tuple(endpoint_reasons), tuple(dict.fromkeys(reasons))
            )
        return IntegralDomainAnalysis(IntegralKind.PROPER, lower, upper)

    @staticmethod
    def _improper_split_point(lower: sp.Expr, upper: sp.Expr) -> sp.Expr:
        if lower == -sp.oo and upper == sp.oo:
            return sp.Integer(0)
        if lower == -sp.oo:
            return sp.simplify(upper - 1)
        if upper == sp.oo:
            return sp.simplify(lower + 1)
        return sp.simplify((lower + upper) / 2)

    def _has_absolute_tail_certificate(
        self, expr: sp.Expr, symbol: sp.Symbol, lower: sp.Expr, upper: sp.Expr
    ) -> bool:
        """Prove an infinite tail is absolutely integrable by comparison.

        A finite limit of ``x**2 * f(x)`` at either infinite endpoint gives
        ``f(x) = O(1/x**2)`` there, which is an absolute-convergence proof.
        This intentionally small rule is useful for exponentially decaying
        and rational tails without pretending to settle oscillatory cases.
        """
        if upper == sp.oo:
            point = sp.oo
        elif lower == -sp.oo:
            point = -sp.oo
        else:
            return False
        try:
            scaled = sp.simplify(symbol**2 * expr)
            limit = self._run_cas(
                "limit", {"expression": scaled, "symbol": symbol, "point": point, "dir": "-"}
            )
        except Exception:
            return False
        return self._is_finite_real_expression(limit)

    def _certified_improper_numeric_fallback(
        self,
        expr: sp.Expr,
        symbol: sp.Symbol,
        lower: sp.Expr,
        upper: sp.Expr,
        *,
        lower_problem: bool,
        upper_problem: bool,
        tol: float,
    ) -> CalculationResult[float] | None:
        """Numerically evaluate only a tail whose absolute convergence is proved."""
        has_only_infinite_tail = (
            upper == sp.oo and not lower_problem
        ) or (
            lower == -sp.oo and not upper_problem
        )
        if not has_only_infinite_tail or not self._has_absolute_tail_certificate(expr, symbol, lower, upper):
            return None
        try:
            numeric = self._numeric_integral(expr, symbol, [(lower, upper)], tol=tol, allow_complex=False)
        except CalculatorError:
            return None
        return CalculationResult(
            ResultStatus.INTEGRAL_EXISTS,
            numeric,
            approx_value=numeric,
            metadata={"approximate": True, "convergence_proof": "x^-2_tail_comparison"},
        )

    def _evaluate_improper_component(
        self,
        expr: sp.Expr,
        symbol: sp.Symbol,
        lower: sp.Expr,
        upper: sp.Expr,
        *,
        lower_problem: bool,
        upper_problem: bool,
        tol: float = 1e-10,
    ) -> CalculationResult[sp.Expr | float]:
        """Prove one component independently; symmetric cancellation is impossible here."""
        if lower_problem and upper_problem:
            split = self._improper_split_point(lower, upper)
            left = self._evaluate_improper_component(
                expr, symbol, lower, split, lower_problem=True, upper_problem=False, tol=tol
            )
            right = self._evaluate_improper_component(
                expr, symbol, split, upper, lower_problem=False, upper_problem=True, tol=tol
            )
            if ResultStatus.INTEGRAL_DIVERGES in {left.status, right.status}:
                return CalculationResult(ResultStatus.INTEGRAL_DIVERGES, message_code="IMPROPER_COMPONENT_DIVERGES")
            if not left.exists or not right.exists:
                return CalculationResult(ResultStatus.INTEGRAL_UNDETERMINED, message_code="IMPROPER_COMPONENT_UNDETERMINED")
            # ``sympify`` is typed to return ``Basic``; both operands here
            # are the numeric result of a proven-convergent integral component.
            value = sp.simplify(cast(sp.Expr, sp.sympify(left.value)) + cast(sp.Expr, sp.sympify(right.value)))
            approximate = left.approx_value is not None or right.approx_value is not None
            return CalculationResult(
                ResultStatus.INTEGRAL_EXISTS,
                value,
                exact_value=None if approximate else value,
                approx_value=float(value) if approximate else None,
                metadata={"approximate": approximate},
            )
        try:
            direct = self._run_cas(
                "definite_integral", {"expression": expr, "symbol": symbol, "lower": lower, "upper": upper}
            )
            if not self._has_unresolved_integral(direct) and self._is_finite_real_expression(direct):
                exact = sp.sympify(direct)
                return CalculationResult(ResultStatus.INTEGRAL_EXISTS, exact, exact_value=exact)
        except Exception:
            pass
        # A generic symbolic definite integral can report ``oo`` even when a
        # removable endpoint or an oscillatory tail makes the actual improper
        # integral finite.  Only the one-sided truncated-limit calculation
        # below is accepted as a divergence proof.
        numeric = self._certified_improper_numeric_fallback(
            expr, symbol, lower, upper, lower_problem=lower_problem, upper_problem=upper_problem, tol=tol
        )
        if numeric is not None:
            return numeric
        parameter = sp.Dummy("t", positive=True)
        try:
            if lower_problem:
                moving_lower = -parameter if lower == -sp.oo else lower + parameter
                limit_point = sp.oo if lower == -sp.oo else sp.Integer(0)
                partial = self._run_cas(
                    "definite_integral", {"expression": expr, "symbol": symbol, "lower": moving_lower, "upper": upper}
                )
                if self._has_unresolved_integral(partial):
                    return CalculationResult(ResultStatus.INTEGRAL_UNDETERMINED, message_code="IMPROPER_COMPONENT_UNDETERMINED")
                value = self._run_cas(
                    "limit", {"expression": partial, "symbol": parameter, "point": limit_point, "dir": "-" if lower == -sp.oo else "+"}
                )
            else:
                moving_upper = parameter if upper == sp.oo else upper - parameter
                limit_point = sp.oo if upper == sp.oo else sp.Integer(0)
                partial = self._run_cas(
                    "definite_integral", {"expression": expr, "symbol": symbol, "lower": lower, "upper": moving_upper}
                )
                if self._has_unresolved_integral(partial):
                    return CalculationResult(ResultStatus.INTEGRAL_UNDETERMINED, message_code="IMPROPER_COMPONENT_UNDETERMINED")
                value = self._run_cas(
                    # For a finite upper endpoint we integrate only up to
                    # ``upper - t``.  The truncation parameter must approach
                    # zero from the positive side; approaching from the
                    # negative side would cross the singular endpoint and can
                    # turn a valid one-sided improper integral into a wrong
                    # limit.  At ``+oo`` SymPy's conventional left approach
                    # remains the appropriate tail limit.
                    "limit", {
                        "expression": partial,
                        "symbol": parameter,
                        "point": limit_point,
                        "dir": "-" if upper == sp.oo else "+",
                    }
                )
        except Exception:
            return CalculationResult(ResultStatus.INTEGRAL_UNDETERMINED, message_code="IMPROPER_COMPONENT_UNDETERMINED")
        if self._is_divergent_integral_value(value):
            return CalculationResult(ResultStatus.INTEGRAL_DIVERGES, message_code="IMPROPER_COMPONENT_DIVERGES")
        if self._has_unresolved_integral(value) or isinstance(value, sp.Limit) or not self._is_finite_real_expression(value):
            return CalculationResult(ResultStatus.INTEGRAL_UNDETERMINED, message_code="IMPROPER_COMPONENT_UNDETERMINED")
        exact = cast(sp.Expr, sp.sympify(value))
        return CalculationResult(ResultStatus.INTEGRAL_EXISTS, exact, exact_value=exact)

    def _evaluate_proper_integral(
        self, expr: sp.Expr, symbol: sp.Symbol, lower: sp.Expr, upper: sp.Expr, *, tol: float
    ) -> CalculationResult[sp.Expr | float]:
        try:
            exact = self._run_cas(
                "definite_integral", {"expression": expr, "symbol": symbol, "lower": lower, "upper": upper}
            )
            value = self._exact_integral_value(exact, allow_complex=False)
            if value is not None:
                return CalculationResult(ResultStatus.INTEGRAL_EXISTS, value, exact_value=value)
        except Exception:
            pass
        try:
            numeric = self._numeric_integral(expr, symbol, [(lower, upper)], tol=tol, allow_complex=False)
        except CalculatorError:
            return CalculationResult(ResultStatus.INTEGRAL_UNDETERMINED, message_code="PROPER_INTEGRAL_UNDETERMINED")
        return CalculationResult(ResultStatus.INTEGRAL_EXISTS, numeric, approx_value=numeric, metadata={"approximate": True})

    def definite_integral_result(
        self, integrand: str, lower: str, upper: str, variable: str = "x", tol: float = 1e-10
    ) -> CalculationResult[sp.Expr | float]:
        """Typed real-integral API with automatic proper/improper classification."""
        self._validate_calculus_variable(variable)
        symbol = sp.Symbol(variable)
        # Calculus uses conventional symbolic notation: ``log`` is natural
        # logarithm and trigonometric arguments are radians, independently of
        # the calculator's interactive angle/base-display settings.
        expr = self.parse_symbolic(integrand, {variable: symbol})
        lower_value, upper_value = self._parse_integral_bound(lower), self._parse_integral_bound(upper)
        self._integral_bound_float(lower_value)
        self._integral_bound_float(upper_value)
        if expr.free_symbols - {symbol}:
            raise CalculatorError("Math ERROR: integralde bilinmeyen değişken var")
        orientation = 1
        if lower_value > upper_value:
            lower_value, upper_value = upper_value, lower_value
            orientation = -1
        analysis = self._analyze_integral_domain(expr, symbol, lower_value, upper_value)
        metadata = {
            "kind": analysis.kind.value,
            "reasons": analysis.reasons,
            "singularities": analysis.singularities,
            "analysis_complete": analysis.analysis_complete,
        }
        if analysis.domain_undefined:
            return CalculationResult(ResultStatus.INTEGRAL_UNDEFINED, message_code="INTEGRAL_OUTSIDE_REAL_DOMAIN", metadata=metadata)
        if analysis.kind is IntegralKind.UNKNOWN:
            return CalculationResult(ResultStatus.INTEGRAL_UNDETERMINED, message_code="INTEGRAL_CONVERGENCE_UNDETERMINED", metadata=metadata)
        if analysis.kind is IntegralKind.PROPER:
            result = self._evaluate_proper_integral(expr, symbol, lower_value, upper_value, tol=tol)
        else:
            boundaries = (lower_value, *analysis.singularities, upper_value)
            components = []
            for index, (component_lower, component_upper) in enumerate(zip(boundaries, boundaries[1:], strict=False)):
                components.append(self._evaluate_improper_component(
                    expr,
                    symbol,
                    component_lower,
                    component_upper,
                    lower_problem=index > 0 or component_lower == -sp.oo or (index == 0 and "lower_endpoint" in analysis.endpoint_singularities),
                    upper_problem=index + 1 < len(boundaries) - 1 or component_upper == sp.oo or (index == len(boundaries) - 2 and "upper_endpoint" in analysis.endpoint_singularities),
                    tol=tol,
                ))
            if any(component.status is ResultStatus.INTEGRAL_DIVERGES for component in components):
                result = CalculationResult(ResultStatus.INTEGRAL_DIVERGES, message_code="IMPROPER_INTEGRAL_DIVERGES")
            elif not all(component.exists for component in components):
                result = CalculationResult(ResultStatus.INTEGRAL_UNDETERMINED, message_code="IMPROPER_INTEGRAL_UNDETERMINED")
            else:
                value = sp.simplify(sum((sp.sympify(component.value) for component in components), sp.Integer(0)))
                approximate = any(component.approx_value is not None for component in components)
                result = CalculationResult(
                    ResultStatus.INTEGRAL_EXISTS,
                    value,
                    exact_value=None if approximate else value,
                    approx_value=float(value) if approximate else None,
                    metadata={"approximate": approximate},
                )
        result_metadata = dict(metadata)
        result_metadata.update(result.metadata)
        if result.exists and result.value is not None:
            value = sp.simplify(orientation * cast(sp.Expr, sp.sympify(result.value)))
            exact = (
                result.exact_value
                if result.exact_value is None
                else sp.simplify(orientation * cast(sp.Expr, sp.sympify(result.exact_value)))
            )
            result = CalculationResult(
                result.status, value, exact_value=exact,
                approx_value=None if result.approx_value is None else orientation * cast(float, result.approx_value),
                message_code=result.message_code, metadata=result_metadata,
            )
            self._commit_definite_integral(
                f"∫{lower}→{upper} {integrand} d{variable}",
                value,
                approximate=result.approx_value is not None,
                kind="integral_single",
                metadata={
                    "integrand": integrand,
                    "variables": [variable],
                    "bounds": [{"variable": variable, "lower": lower, "upper": upper}],
                    "integral_kind": analysis.kind.value,
                    "convergence": "convergent",
                    "result_exact": None if exact is None else str(exact),
                },
            )
        else:
            result = CalculationResult(
                result.status, message_code=result.message_code, metadata=result_metadata
            )
        return result

    @staticmethod
    def _has_unresolved_integral(value: object) -> bool:
        """Recognize an unevaluated Integral even when it is nested in another expression."""
        return isinstance(value, sp.Basic) and value.has(sp.Integral)

    @staticmethod
    def _exact_integral_value(value: object, *, allow_complex: bool) -> sp.Expr | None:
        if CalculusMixin._has_unresolved_integral(value):
            return None
        if isinstance(value, sp.Basic) and value.free_symbols:
            raise CalculatorError("Math ERROR: integral sayısal sonuç vermedi")
        if allow_complex:
            _finite_complex(value, "Math ERROR: integral sonlu karmaşık değil")
            return cast(sp.Expr, value if isinstance(value, sp.Basic) else sp.sympify(value))
        _finite_real_float(value, "Math ERROR: integral sonlu reel değil")
        return cast(sp.Expr, value if isinstance(value, sp.Basic) else sp.sympify(value))

    @overload
    def _numeric_integral(
        self, expr: sp.Expr, symbol: sp.Symbol, segments, *, tol: float, allow_complex: Literal[False]
    ) -> float: ...
    @overload
    def _numeric_integral(
        self, expr: sp.Expr, symbol: sp.Symbol, segments, *, tol: float, allow_complex: Literal[True]
    ) -> complex: ...
    @overload
    def _numeric_integral(
        self, expr: sp.Expr, symbol: sp.Symbol, segments, *, tol: float, allow_complex: bool
    ) -> float | complex: ...
    def _numeric_integral(self, expr: sp.Expr, symbol: sp.Symbol, segments, *, tol: float, allow_complex: bool):
        if expr.free_symbols - {symbol}:
            raise CalculatorError("Math ERROR: integralde bilinmeyen değişken var")
        try:
            tolerance = float(tol)
        except (TypeError, ValueError) as exc:
            raise CalculatorError("Argument ERROR: integral toleransı pozitif sonlu sayı olmalıdır") from exc
        if not math.isfinite(tolerance) or not 0 < tolerance <= 1e-2:
            raise CalculatorError("Argument ERROR: integral toleransı pozitif sonlu sayı olmalıdır")
        # Complex quadrature is scalar. ``numpy.sqrt`` returns NaN for a
        # negative real argument, whereas ``cmath.sqrt`` returns the required
        # principal complex value. Keep NumPy only on the real path.
        modules = [_COMPLEX_SCALAR_FUNCTIONS, "cmath", "math"] if allow_complex else ["numpy", "math"]
        try:
            fn = sp.lambdify(symbol, expr, modules=modules)
            total = 0j if allow_complex else 0.0
            with warnings.catch_warnings(), np.errstate(over="ignore", under="ignore"):
                warnings.simplefilter("error", _integrate().IntegrationWarning)
                warnings.simplefilter("error", RuntimeWarning)
                for lower, upper in segments:
                    lo, hi = self._integral_bound_float(lower), self._integral_bound_float(upper)
                    if allow_complex:
                        real, real_error = _integrate().quad(
                            lambda value: float(np.real(fn(value))), lo, hi,
                            epsabs=tolerance, epsrel=tolerance, limit=300,
                        )
                        imag, imag_error = _integrate().quad(
                            lambda value: float(np.imag(fn(value))), lo, hi,
                            epsabs=tolerance, epsrel=tolerance, limit=300,
                        )
                        if not (math.isfinite(real_error) and math.isfinite(imag_error)):
                            raise CalculatorError("Math ERROR: integral hata tahmini sonlu değil")
                        total += complex(real, imag)
                    else:
                        value, error = _integrate().quad(fn, lo, hi, epsabs=tolerance, epsrel=tolerance, limit=300)
                        if not math.isfinite(float(error)):
                            raise CalculatorError("Math ERROR: integral hata tahmini sonlu değil")
                        total += value
        except CalculatorError:
            raise
        except Exception as exc:
            raise CalculatorError("Math ERROR: integral could not be evaluated") from exc
        if allow_complex:
            return _finite_complex(total, "Math ERROR: integral sonucu sonlu karmaşık değil")
        return _finite_real_float(total, "Math ERROR: integral sonucu sonlu reel değil")

    @staticmethod
    def _select_complex_integral_result(exact: object, numeric: complex, *, tol: float):
        """Keep an exact complex answer only when principal-branch quadrature agrees."""
        exact_value = _finite_complex(exact, "Math ERROR: integral sonlu karmaşık değil")
        comparison_tolerance = max(1e-8, min(1e-6, 100 * float(tol)))
        if abs(exact_value - numeric) <= comparison_tolerance * max(1.0, abs(exact_value), abs(numeric)):
            return exact, False
        return numeric, True

    def _definite_integral_expression(
        self, expr: sp.Expr, lower: sp.Expr, upper: sp.Expr, symbol: sp.Symbol, *, tol: float, allow_complex: bool,
    ):
        if expr.free_symbols - {symbol}:
            raise CalculatorError("Math ERROR: integralde bilinmeyen değişken var")
        segments, has_interior_singularity = self._integral_segments(expr, symbol, lower, upper)
        exact_result = None
        exact_values = []
        try:
            for segment_lower, segment_upper in segments:
                exact = self._run_cas("definite_integral", {
                    "expression": expr, "symbol": symbol, "lower": segment_lower, "upper": segment_upper,
                })
                value = self._exact_integral_value(exact, allow_complex=allow_complex)
                if value is None:
                    exact_values = []
                    break
                exact_values.append(value)
            if exact_values:
                exact_result = sum(exact_values, sp.Integer(0))
                if allow_complex:
                    _finite_complex(exact_result, "Math ERROR: integral sonlu karmaşık değil")
                else:
                    return _finite_real_float(exact_result, "Math ERROR: integral sonlu reel değil"), True
        except CalculatorError:
            if has_interior_singularity:
                raise CalculatorError("Math ERROR: integral iç tekilliği yakınsak değil") from None
            raise
        except Exception:
            pass
        try:
            numeric = self._numeric_integral(
                expr, symbol, segments, tol=tol, allow_complex=allow_complex,
            )
        except CalculatorError:
            if has_interior_singularity:
                raise CalculatorError("Math ERROR: integral iç tekilliği yakınsak değil") from None
            if allow_complex and exact_result is not None:
                return exact_result, False
            raise
        if allow_complex and exact_result is not None:
            return self._select_complex_integral_result(exact_result, numeric, tol=tol)
        return numeric, True

    def _commit_definite_integral(
        self, expression: str, result, *, approximate: bool, kind: str = "legacy", metadata: dict | None = None
    ) -> None:
        answer = result if isinstance(result, sp.Basic) else sp.sympify(result)
        self._commit_outcome(self._calculus_history_outcome(
            result,
            ans=answer,
            expression=expression,
            rendered=self.format_result(result, approximate=approximate),
            kind=kind,
            metadata=metadata,
        ))

    def definite_integral(self, integrand, lower, upper, variable="x", tol=1e-10):
        """Backward-compatible value wrapper around :meth:`definite_integral_result`.

        Callers that need to present divergence or an undetermined proof use
        the typed method.  The historical value API continues to raise a
        controlled calculator error for non-values.
        """
        result = self.definite_integral_result(integrand, lower, upper, variable, tol)
        if result.exists:
            return result.value
        messages = {
            ResultStatus.INTEGRAL_DIVERGES: "Math ERROR: integral diverges",
            ResultStatus.INTEGRAL_UNDEFINED: "Math ERROR: integral outside real domain",
            ResultStatus.INTEGRAL_UNDETERMINED: "Math ERROR: integral convergence is undetermined",
        }
        raise CalculatorError(messages.get(result.status, "Math ERROR: integral could not be evaluated"))

    def complex_definite_integral(self, integrand, lower, upper, variable="z", tol=1e-10):
        """Complex-valued definite integral over a real parameter interval."""
        self._validate_calculus_variable(variable)
        z = sp.Symbol(variable)
        expr = self.parse_symbolic(integrand, {variable: z})
        lo_expr, hi_expr = self._parse_integral_bound(lower), self._parse_integral_bound(upper)
        result, approximate = self._definite_integral_expression(
            expr, lo_expr, hi_expr, z, tol=tol, allow_complex=True,
        )
        self._commit_definite_integral(
            f"∫{lower}→{upper} {integrand} d{variable}",
            result,
            approximate=approximate,
            kind="complex_calculus",
            metadata={
                "operation": "integral",
                "integrand": integrand,
                "variable": variable,
                "lower": lower,
                "upper": upper,
            },
        )
        return result

    def complex_derivative_result(
        self, expression: str, variable: str = "z", point: str | None = None,
    ) -> CalculationResult[sp.Expr]:
        """Classify complex differentiability with Cauchy--Riemann equations.

        ``sympy.diff`` alone is not a holomorphicity test: it produces formal
        derivatives for expressions such as ``conjugate(z)``.  The method
        therefore expands ``z = x + iy`` and checks both Cauchy--Riemann
        residuals before returning any derivative.
        """
        self._validate_calculus_variable(variable, label="Karmaşık değişken")
        def commit(result: CalculationResult[sp.Expr]) -> CalculationResult[sp.Expr]:
            location = "" if point is None else f" | {variable}={point}"
            value = result.value
            rendered = self.format_result(value) if value is not None else result.message_code.replace("_", " ")
            self._commit_outcome(self._calculus_history_outcome(
                result,
                ans=value if value is not None else NO_ANS_UPDATE,
                expression=f"d/d{variable} {expression}{location}",
                rendered=rendered,
                kind="complex_calculus",
                metadata={"operation": "derivative", "expression": expression, "variable": variable, "point": point},
            ))
            return result

        z = sp.Symbol(variable)
        expr = self.parse_symbolic(expression, {variable: z})
        if expr.free_symbols - {z}:
            raise CalculatorError("Math ERROR: complex derivative contains an unknown variable")
        x, y = sp.symbols("x y", real=True)
        cartesian = sp.expand_complex(expr.subs(z, x + sp.I * y))
        real_part, imaginary_part = sp.re(cartesian), sp.im(cartesian)
        first = sp.simplify(sp.diff(real_part, x) - sp.diff(imaginary_part, y))
        second = sp.simplify(sp.diff(real_part, y) + sp.diff(imaginary_part, x))
        if point is None:
            if first == 0 and second == 0:
                derivative = sp.simplify(sp.diff(expr, z))
                return commit(CalculationResult(
                    ResultStatus.DERIVATIVE_EXISTS,
                    derivative,
                    exact_value=derivative,
                    message_code="COMPLEX_DERIVATIVE_EXISTS",
                    metadata={"holomorphic": True},
                ))
            return commit(CalculationResult(
                ResultStatus.DERIVATIVE_DOES_NOT_EXIST,
                message_code="COMPLEX_NOT_HOLOMORPHIC",
                metadata={"cauchy_riemann": (first, second), "holomorphic": False},
            ))
        point_value = self.parse_symbolic(point, {variable: z})
        if point_value.free_symbols:
            raise CalculatorError("Argument ERROR: complex derivative point must be numeric")
        at_point = sp.simplify(expr.subs(z, point_value))
        if at_point.has(sp.zoo, sp.oo, -sp.oo, sp.nan):
            return commit(CalculationResult(
                ResultStatus.DERIVATIVE_UNDEFINED_AT_POINT,
                message_code="COMPLEX_DERIVATIVE_UNDEFINED",
                metadata={"point": point_value},
            ))
        substitutions = {x: sp.re(point_value), y: sp.im(point_value)}
        first_at_point, second_at_point = sp.simplify(first.subs(substitutions)), sp.simplify(second.subs(substitutions))
        if first_at_point != 0 or second_at_point != 0:
            return commit(CalculationResult(
                ResultStatus.DERIVATIVE_DOES_NOT_EXIST,
                message_code="COMPLEX_DERIVATIVE_DOES_NOT_EXIST",
                metadata={"point": point_value, "cauchy_riemann": (first_at_point, second_at_point)},
            ))
        derivative = sp.simplify((sp.diff(real_part, x) + sp.I * sp.diff(imaginary_part, x)).subs(substitutions))
        return commit(CalculationResult(
            ResultStatus.DERIVATIVE_EXISTS,
            derivative,
            exact_value=derivative,
            message_code="COMPLEX_DERIVATIVE_EXISTS_AT_POINT",
            metadata={"point": point_value},
        ))

    def complex_limit_result(self, expression: str, point: str, variable: str = "z") -> CalculationResult[sp.Expr]:
        """Classify a complex limit without mistaking sampled paths for proof."""
        self._validate_calculus_variable(variable, label="Karmaşık değişken")
        z = sp.Symbol(variable)
        expr = self.parse_symbolic(expression, {variable: z})
        point_value = self.parse_symbolic(point, {variable: z})
        if expr.free_symbols - {z} or point_value.free_symbols:
            raise CalculatorError("Argument ERROR: complex limit requires one variable and a numeric point")
        t = sp.Symbol("t", real=True)
        values: list[sp.Expr] = []
        try:
            for direction in (sp.Integer(1), sp.I, sp.Integer(1) + sp.I):
                values.append(sp.simplify(sp.limit(expr.subs(z, point_value + direction * t), t, 0, dir="+")))
        except Exception:
            return CalculationResult(
                ResultStatus.LIMIT_UNDETERMINED,
                message_code="COMPLEX_LIMIT_UNDETERMINED",
                metadata={"point": point_value},
            )
        if any(value.has(sp.zoo, sp.nan) for value in values):
            return CalculationResult(
                ResultStatus.LIMIT_UNDETERMINED,
                message_code="COMPLEX_LIMIT_UNDETERMINED",
                metadata={"point": point_value, "paths": tuple(values)},
            )
        if not all(sp.simplify(value - values[0]) == 0 for value in values[1:]):
            return CalculationResult(
                ResultStatus.LIMIT_DOES_NOT_EXIST,
                message_code="COMPLEX_LIMIT_DOES_NOT_EXIST",
                metadata={"point": point_value, "paths": tuple(values)},
            )
        forbidden = (sp.conjugate, sp.re, sp.im, sp.Abs, sp.arg)
        direct = sp.simplify(expr.subs(z, point_value))
        if not expr.has(*forbidden) and self._is_finite_real_expression(sp.re(direct)) and self._is_finite_real_expression(sp.im(direct)):
            return CalculationResult(
                ResultStatus.LIMIT_EXISTS,
                direct,
                exact_value=direct,
                message_code="COMPLEX_LIMIT_EXISTS",
                metadata={"point": point_value},
            )
        return CalculationResult(
            ResultStatus.LIMIT_UNDETERMINED,
            message_code="COMPLEX_LIMIT_UNDETERMINED",
            metadata={"point": point_value, "paths": tuple(values)},
        )

    @classmethod
    def _validate_distinct_calculus_variables(cls, *variables: str) -> None:
        for variable in variables:
            cls._validate_calculus_variable(variable)
        if len(set(variables)) != len(variables):
            raise CalculatorError("Syntax ERROR: integral değişkenleri farklı olmalıdır")

    def _parse_finite_multivariate_bound(
        self, bound: str, allowed_symbols: tuple[sp.Symbol, ...] = (), *, label: str = "integral sınırı",
    ) -> sp.Expr:
        """Parse a real finite bound which may depend only on outer variables."""
        if not isinstance(bound, str):
            raise CalculatorError(f"Math ERROR: {label} metin olmalıdır")
        aliases = {"inf", "+inf", "infinity", "+infinity", "∞", "+∞", "oo", "+oo", "-inf", "-infinity", "-∞", "-oo"}
        if bound.strip().lower().replace(" ", "") in aliases:
            raise CalculatorError("Math ERROR: çoklu integral sınırları sonlu reel olmalıdır")
        locals_ = self._calculus_symbol_locals({str(symbol): symbol for symbol in allowed_symbols})
        result = self.parse_symbolic(bound, locals_)
        if result.free_symbols - set(allowed_symbols):
            raise CalculatorError(f"Math ERROR: {label} yalnız dış integral değişkenlerini içerebilir")
        if result.has(sp.oo, -sp.oo, sp.zoo, sp.nan):
            raise CalculatorError("Math ERROR: çoklu integral sınırları sonlu reel olmalıdır")
        return result

    @staticmethod
    def _numeric_real_callable(expression: sp.Expr, symbols: tuple[sp.Symbol, ...], *, label: str):
        try:
            raw = sp.lambdify(symbols, expression, modules=["numpy", "math"])
        except Exception as exc:
            raise CalculatorError(f"Math ERROR: {label} sayısal hesaplamaya hazırlanamadı") from exc

        def evaluate(*values: float) -> float:
            try:
                return _finite_real_float(raw(*values), f"Math ERROR: {label} sonlu reel olmalıdır")
            except CalculatorError:
                raise
            except Exception as exc:
                raise CalculatorError(f"Math ERROR: {label} hesaplanamadı") from exc

        return evaluate

    @overload
    def _try_exact_nested_integral(
        self, expression: sp.Expr, specifications: tuple[tuple[sp.Symbol, sp.Expr, sp.Expr], ...], *,
        allow_complex: Literal[False] = False,
    ) -> float | None: ...
    @overload
    def _try_exact_nested_integral(
        self, expression: sp.Expr, specifications: tuple[tuple[sp.Symbol, sp.Expr, sp.Expr], ...], *,
        allow_complex: Literal[True],
    ) -> complex | None: ...
    def _try_exact_nested_integral(
        self, expression: sp.Expr, specifications: tuple[tuple[sp.Symbol, sp.Expr, sp.Expr], ...], *,
        allow_complex: bool = False,
    ) -> object | None:
        """Return a closed nested integral, preserving an exact complex result."""
        result = expression
        try:
            for symbol, lower, upper in reversed(specifications):
                result = self._run_cas("definite_integral", {
                    "expression": result, "symbol": symbol, "lower": lower, "upper": upper,
                })
                if self._has_unresolved_integral(result):
                    return None
            if allow_complex:
                _finite_complex(result, "Math ERROR: integral sonlu karmaşık değil")
                return result
            return _finite_real_float(result, "Math ERROR: integral sonlu reel değil")
        except Exception:
            return None

    @staticmethod
    def _finish_numeric_multivariate(value: object, error: object) -> float:
        result = _finite_real_float(value, "Math ERROR: çoklu integral sonucu sonlu reel değil")
        estimated_error = _finite_real_float(error, "Math ERROR: çoklu integral hata tahmini sonlu değil")
        if estimated_error < 0:
            raise CalculatorError("Math ERROR: çoklu integral hata tahmini geçersiz")
        return result

    def _numeric_double_integral(
        self, expression: sp.Expr, outer: sp.Symbol, inner: sp.Symbol,
        outer_lower: sp.Expr, outer_upper: sp.Expr, inner_lower: sp.Expr, inner_upper: sp.Expr, *, tol: float,
    ) -> float:
        try:
            tolerance = float(tol)
        except (TypeError, ValueError) as exc:
            raise CalculatorError("Argument ERROR: integral toleransı pozitif sonlu sayı olmalıdır") from exc
        if not math.isfinite(tolerance) or not 0 < tolerance <= 1e-2:
            raise CalculatorError("Argument ERROR: integral toleransı pozitif sonlu sayı olmalıdır")
        outer_lo = _finite_real_float(outer_lower, "Math ERROR: integral sınırları sonlu reel olmalıdır")
        outer_hi = _finite_real_float(outer_upper, "Math ERROR: integral sınırları sonlu reel olmalıdır")
        integrand = self._numeric_real_callable(expression, (outer, inner), label="integrand")
        lower = self._numeric_real_callable(inner_lower, (outer,), label="iç integral sınırı")
        upper = self._numeric_real_callable(inner_upper, (outer,), label="iç integral sınırı")
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", _integrate().IntegrationWarning)
                warnings.simplefilter("error", RuntimeWarning)
                # ``dblquad``'s inferred return type spans its ``full_output``
                # overloads; it is called here without that flag and always
                # returns the plain (value, error) pair.
                value, error = cast(tuple[float, float], _integrate().dblquad(
                    lambda inner_value, outer_value: integrand(outer_value, inner_value),
                    outer_lo, outer_hi, lower, upper, epsabs=tolerance, epsrel=tolerance,
                ))
        except CalculatorError:
            raise
        except Exception as exc:
            raise CalculatorError("Math ERROR: çift katlı integral hesaplanamadı") from exc
        return self._finish_numeric_multivariate(value, error)

    @staticmethod
    def _numeric_complex_callable(expression: sp.Expr, symbols: tuple[sp.Symbol, ...], *, label: str):
        try:
            raw = sp.lambdify(symbols, expression, modules=[_COMPLEX_SCALAR_FUNCTIONS, "cmath", "math"])
        except Exception as exc:
            raise CalculatorError(f"Math ERROR: {label} sayısal hesaplamaya hazırlanamadı") from exc

        def evaluate(*values: float) -> complex:
            try:
                return _finite_complex(raw(*values), f"Math ERROR: {label} sonlu karmaşık olmalıdır")
            except CalculatorError:
                raise
            except Exception as exc:
                raise CalculatorError(f"Math ERROR: {label} hesaplanamadı") from exc

        return evaluate

    def _numeric_complex_double_integral(
        self, expression: sp.Expr, outer: sp.Symbol, inner: sp.Symbol,
        outer_lower: sp.Expr, outer_upper: sp.Expr, inner_lower: sp.Expr, inner_upper: sp.Expr, *, tol: float,
    ) -> complex:
        try:
            tolerance = float(tol)
        except (TypeError, ValueError) as exc:
            raise CalculatorError("Argument ERROR: integral toleransı pozitif sonlu sayı olmalıdır") from exc
        if not math.isfinite(tolerance) or not 0 < tolerance <= 1e-2:
            raise CalculatorError("Argument ERROR: integral toleransı pozitif sonlu sayı olmalıdır")
        outer_lo = _finite_real_float(outer_lower, "Math ERROR: integral sınırları sonlu reel olmalıdır")
        outer_hi = _finite_real_float(outer_upper, "Math ERROR: integral sınırları sonlu reel olmalıdır")
        integrand = self._numeric_complex_callable(expression, (outer, inner), label="integrand")
        lower = self._numeric_real_callable(inner_lower, (outer,), label="iç integral sınırı")
        upper = self._numeric_real_callable(inner_upper, (outer,), label="iç integral sınırı")
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", _integrate().IntegrationWarning)
                warnings.simplefilter("error", RuntimeWarning)
                real, real_error = cast(tuple[float, float], _integrate().dblquad(
                    lambda inner_value, outer_value: float(np.real(integrand(outer_value, inner_value))),
                    outer_lo, outer_hi, lower, upper, epsabs=tolerance, epsrel=tolerance,
                ))
                imag, imag_error = cast(tuple[float, float], _integrate().dblquad(
                    lambda inner_value, outer_value: float(np.imag(integrand(outer_value, inner_value))),
                    outer_lo, outer_hi, lower, upper, epsabs=tolerance, epsrel=tolerance,
                ))
        except CalculatorError:
            raise
        except Exception as exc:
            raise CalculatorError("Math ERROR: karmaşık çift katlı integral hesaplanamadı") from exc
        self._finish_numeric_multivariate(real, real_error)
        self._finish_numeric_multivariate(imag, imag_error)
        return _finite_complex(complex(real, imag), "Math ERROR: karmaşık çift katlı integral sonucu sonlu değil")

    def _numeric_triple_integral(
        self, expression: sp.Expr, outer: sp.Symbol, middle: sp.Symbol, inner: sp.Symbol,
        outer_lower: sp.Expr, outer_upper: sp.Expr,
        middle_lower: sp.Expr, middle_upper: sp.Expr,
        inner_lower: sp.Expr, inner_upper: sp.Expr, *, tol: float,
    ) -> float:
        try:
            tolerance = float(tol)
        except (TypeError, ValueError) as exc:
            raise CalculatorError("Argument ERROR: integral toleransı pozitif sonlu sayı olmalıdır") from exc
        if not math.isfinite(tolerance) or not 0 < tolerance <= 1e-2:
            raise CalculatorError("Argument ERROR: integral toleransı pozitif sonlu sayı olmalıdır")
        outer_lo = _finite_real_float(outer_lower, "Math ERROR: integral sınırları sonlu reel olmalıdır")
        outer_hi = _finite_real_float(outer_upper, "Math ERROR: integral sınırları sonlu reel olmalıdır")
        integrand = self._numeric_real_callable(expression, (outer, middle, inner), label="integrand")
        middle_lo = self._numeric_real_callable(middle_lower, (outer,), label="orta integral sınırı")
        middle_hi = self._numeric_real_callable(middle_upper, (outer,), label="orta integral sınırı")
        inner_lo = self._numeric_real_callable(inner_lower, (outer, middle), label="iç integral sınırı")
        inner_hi = self._numeric_real_callable(inner_upper, (outer, middle), label="iç integral sınırı")
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", _integrate().IntegrationWarning)
                warnings.simplefilter("error", RuntimeWarning)
                value, error = cast(tuple[float, float], _integrate().tplquad(
                    lambda inner_value, middle_value, outer_value: integrand(outer_value, middle_value, inner_value),
                    outer_lo, outer_hi,
                    middle_lo, middle_hi,
                    inner_lo, inner_hi,
                    epsabs=tolerance, epsrel=tolerance,
                ))
        except CalculatorError:
            raise
        except Exception as exc:
            raise CalculatorError("Math ERROR: üç katlı integral hesaplanamadı") from exc
        return self._finish_numeric_multivariate(value, error)

    def _commit_multivariate_integral(self, expression: str, result: float, *, kind: str, metadata: dict) -> None:
        self._commit_outcome(self._calculus_history_outcome(
            result,
            ans=sp.Float(result),
            expression=expression,
            rendered=self.format_result(result, approximate=True),
            kind=kind,
            metadata=metadata,
        ))

    def double_integral(
        self, integrand: str,
        outer_lower: str, outer_upper: str, inner_lower: str, inner_upper: str,
        outer_variable: str = "x", inner_variable: str = "y", tol: float = 1e-8,
    ) -> float:
        """Evaluate ``∫x ∫y f(x,y) dy dx`` over finite, optionally nested bounds."""
        self._validate_distinct_calculus_variables(outer_variable, inner_variable)
        outer, inner = sp.Symbol(outer_variable), sp.Symbol(inner_variable)
        expression = self.parse_symbolic(
            integrand, self._calculus_symbol_locals({outer_variable: outer, inner_variable: inner}),
        )
        if expression.free_symbols - {outer, inner}:
            raise CalculatorError("Math ERROR: çift katlı integralde bilinmeyen değişken var")
        outer_lo = self._parse_finite_multivariate_bound(outer_lower)
        outer_hi = self._parse_finite_multivariate_bound(outer_upper)
        inner_lo = self._parse_finite_multivariate_bound(inner_lower, (outer,))
        inner_hi = self._parse_finite_multivariate_bound(inner_upper, (outer,))
        result = self._try_exact_nested_integral(
            expression, ((outer, outer_lo, outer_hi), (inner, inner_lo, inner_hi)),
        )
        if result is None:
            result = self._numeric_double_integral(
                expression, outer, inner, outer_lo, outer_hi, inner_lo, inner_hi, tol=tol,
            )
        self._commit_multivariate_integral(
            f"∫{outer_lower}→{outer_upper} ∫{inner_lower}→{inner_upper} {integrand} d{inner_variable} d{outer_variable}", result,
            kind="integral_double",
            metadata={
                "integrand": integrand,
                "integration_order": [inner_variable, outer_variable],
                "bounds": [
                    {"variable": outer_variable, "lower": outer_lower, "upper": outer_upper},
                    {"variable": inner_variable, "lower": inner_lower, "upper": inner_upper},
                ],
            },
        )
        return result

    def complex_double_integral(
        self, integrand: str,
        outer_lower: str, outer_upper: str, inner_lower: str, inner_upper: str,
        outer_variable: str = "x", inner_variable: str = "y", tol: float = 1e-8,
    ):
        """Evaluate a finite nested complex double integral over real bounds."""
        self._validate_distinct_calculus_variables(outer_variable, inner_variable)
        outer, inner = sp.Symbol(outer_variable), sp.Symbol(inner_variable)
        expression = self.parse_symbolic(
            integrand, self._calculus_symbol_locals({outer_variable: outer, inner_variable: inner}),
        )
        if expression.free_symbols - {outer, inner}:
            raise CalculatorError("Math ERROR: karmaşık çift katlı integralde bilinmeyen değişken var")
        outer_lo = self._parse_finite_multivariate_bound(outer_lower)
        outer_hi = self._parse_finite_multivariate_bound(outer_upper)
        inner_lo = self._parse_finite_multivariate_bound(inner_lower, (outer,))
        inner_hi = self._parse_finite_multivariate_bound(inner_upper, (outer,))
        exact_result = self._try_exact_nested_integral(
            expression, ((outer, outer_lo, outer_hi), (inner, inner_lo, inner_hi)), allow_complex=True,
        )
        try:
            numeric_result = self._numeric_complex_double_integral(
                expression, outer, inner, outer_lo, outer_hi, inner_lo, inner_hi, tol=tol,
            )
        except CalculatorError:
            if exact_result is None:
                raise
            result, approximate = exact_result, False
        else:
            if exact_result is None:
                result, approximate = numeric_result, True
            else:
                result, approximate = self._select_complex_integral_result(exact_result, numeric_result, tol=tol)
        self._commit_definite_integral(
            f"∫{outer_lower}→{outer_upper} ∫{inner_lower}→{inner_upper} {integrand} d{inner_variable} d{outer_variable}",
            result,
            approximate=approximate,
            kind="complex_calculus",
            metadata={
                "operation": "double_integral",
                "integrand": integrand,
                "integration_order": [inner_variable, outer_variable],
                "bounds": [
                    {"variable": outer_variable, "lower": outer_lower, "upper": outer_upper},
                    {"variable": inner_variable, "lower": inner_lower, "upper": inner_upper},
                ],
            },
        )
        return result

    def triple_integral(
        self, integrand: str,
        outer_lower: str, outer_upper: str,
        middle_lower: str, middle_upper: str,
        inner_lower: str, inner_upper: str,
        outer_variable: str = "x", middle_variable: str = "y", inner_variable: str = "z", tol: float = 1e-7,
    ) -> float:
        """Evaluate ``∫x ∫y ∫z f(x,y,z) dz dy dx`` on finite nested bounds."""
        self._validate_distinct_calculus_variables(outer_variable, middle_variable, inner_variable)
        outer, middle, inner = sp.Symbol(outer_variable), sp.Symbol(middle_variable), sp.Symbol(inner_variable)
        expression = self.parse_symbolic(integrand, self._calculus_symbol_locals({
            outer_variable: outer, middle_variable: middle, inner_variable: inner,
        }))
        if expression.free_symbols - {outer, middle, inner}:
            raise CalculatorError("Math ERROR: üç katlı integralde bilinmeyen değişken var")
        outer_lo = self._parse_finite_multivariate_bound(outer_lower)
        outer_hi = self._parse_finite_multivariate_bound(outer_upper)
        middle_lo = self._parse_finite_multivariate_bound(middle_lower, (outer,))
        middle_hi = self._parse_finite_multivariate_bound(middle_upper, (outer,))
        inner_lo = self._parse_finite_multivariate_bound(inner_lower, (outer, middle))
        inner_hi = self._parse_finite_multivariate_bound(inner_upper, (outer, middle))
        result = self._try_exact_nested_integral(
            expression,
            ((outer, outer_lo, outer_hi), (middle, middle_lo, middle_hi), (inner, inner_lo, inner_hi)),
        )
        if result is None:
            result = self._numeric_triple_integral(
                expression, outer, middle, inner,
                outer_lo, outer_hi, middle_lo, middle_hi, inner_lo, inner_hi, tol=tol,
            )
        self._commit_multivariate_integral(
            f"∫{outer_lower}→{outer_upper} ∫{middle_lower}→{middle_upper} ∫{inner_lower}→{inner_upper} "
            f"{integrand} d{inner_variable} d{middle_variable} d{outer_variable}", result,
            kind="integral_triple",
            metadata={
                "integrand": integrand,
                "integration_order": [inner_variable, middle_variable, outer_variable],
                "bounds": [
                    {"variable": outer_variable, "lower": outer_lower, "upper": outer_upper},
                    {"variable": middle_variable, "lower": middle_lower, "upper": middle_upper},
                    {"variable": inner_variable, "lower": inner_lower, "upper": inner_upper},
                ],
            },
        )
        return result

    @classmethod
    def _validate_ode_variables(cls, dependent_variable: str, independent_variable: str) -> None:
        cls._validate_calculus_variable(dependent_variable, label="Bağımlı değişken")
        cls._validate_calculus_variable(independent_variable, label="Bağımsız değişken")
        if dependent_variable == independent_variable:
            raise CalculatorError("Syntax ERROR: bağımlı ve bağımsız değişken farklı olmalıdır")
        if {dependent_variable, independent_variable} & {"d", "e", "i", "I"}:
            raise CalculatorError("Syntax ERROR: ODE değişkeni d, e veya i olamaz")

    @staticmethod
    def _reject_pde_notation(equation: str, dependent_variable: str) -> None:
        """Reject common partial-derivative spellings before safe ODE parsing.

        The calculator intentionally solves scalar ODEs only.  Detecting these
        forms here gives a stable, actionable error instead of a later generic
        parser failure.
        """
        if "∂" in equation:
            raise CalculatorError("Syntax ERROR: PDEs are not supported")
        compact = re.sub(r"\s+", "", equation)
        dependent = re.escape(dependent_variable)
        if re.search(rf"(?<![A-Za-z0-9]){dependent}\([^()]*,[^()]*\)", compact):
            raise CalculatorError("Syntax ERROR: PDEs are not supported")
        mixed_derivative = re.compile(
            rf"d(?:(?:\^|\*\*)?\d+)?{dependent}/\(?d[A-Za-z](?:(?:\^|\*\*)?\d+)?"
            rf"(?:\*?d[A-Za-z](?:(?:\^|\*\*)?\d+)?)+\)?"
        )
        if mixed_derivative.search(compact):
            raise CalculatorError("Syntax ERROR: PDEs are not supported")
        directions = {
            match.group("direction")
            for match in re.finditer(
                rf"d(?:(?:\^|\*\*)?\d+)?{dependent}/\(?d(?P<direction>[A-Za-z])",
                compact,
            )
        }
        if len(directions) > 1:
            raise CalculatorError("Syntax ERROR: PDEs are not supported")

    def _ode_locals(
        self, independent: sp.Symbol, dependent_function: sp.Expr,
    ) -> dict[str, object]:
        """Create symbolic parser locals without leaking calculator memory."""
        locals_ = self.symbolic_locals()
        locals_.update(self._calculus_symbol_locals({str(independent): independent}))
        locals_.update({
            "ODEVALUE": dependent_function,
            "ODEDERIVATIVEONE": sp.diff(dependent_function, independent),
            "ODEDERIVATIVETWO": sp.diff(dependent_function, independent, 2),
        })
        return locals_

    @staticmethod
    def _ode_replace_derivative_notation(
        equation: str, dependent_variable: str, independent_variable: str,
    ) -> tuple[str, int]:
        """Turn calculator-friendly derivative notation into safe parser markers."""
        dependent = re.escape(dependent_variable)
        independent = re.escape(independent_variable)
        beginning, ending = r"(?<![A-Za-z0-9])", r"(?![A-Za-z0-9])"
        text = equation.replace("\u2032", "'").replace("\u2019", "'")
        order_pattern = re.compile(
            rf"{beginning}d\s*(?P<numerator>(?:(?:\^|\*\*)?\s*\d+)?)\s*{dependent}\s*/\s*"
            rf"d\s*{independent}\s*(?P<denominator>(?:(?:\^|\*\*)?\s*\d+)?){ending}"
        )

        def derivative_order(token: str) -> int:
            compact = re.sub(r"\s+", "", token)
            return 1 if not compact else int(compact.removeprefix("**").removeprefix("^"))

        for match in order_pattern.finditer(text):
            if max(
                derivative_order(match.group("numerator")),
                derivative_order(match.group("denominator")),
            ) > 2:
                raise CalculatorError("Syntax ERROR: yalnız birinci ve ikinci dereceden ODE desteklenir")
        second_fraction = (
            rf"{beginning}d\s*(?:\^|\*\*)?\s*2\s*{dependent}\s*/\s*"
            rf"d\s*{independent}\s*(?:\^|\*\*)?\s*2{ending}"
        )
        first_fraction = rf"{beginning}d\s*{dependent}\s*/\s*d\s*{independent}{ending}"
        second_prime = rf"{beginning}{dependent}\s*''(?!['A-Za-z0-9])"
        first_prime = rf"{beginning}{dependent}\s*'(?!['A-Za-z0-9])"
        text, second_count = re.subn(second_fraction, "ODEDERIVATIVETWO", text)
        text, second_prime_count = re.subn(second_prime, "ODEDERIVATIVETWO", text)
        text, first_count = re.subn(first_fraction, "ODEDERIVATIVEONE", text)
        text, first_prime_count = re.subn(first_prime, "ODEDERIVATIVEONE", text)
        if "'" in text:
            raise CalculatorError("Syntax ERROR: yalnız birinci ve ikinci dereceden türevler desteklenir")
        return text, second_count + second_prime_count + first_count + first_prime_count

    @staticmethod
    def _validate_second_order_linearity(
        expression: sp.Expr, dependent_function: sp.Expr, independent: sp.Symbol,
    ) -> None:
        """Accept only linear second-order ODEs, which have predictable CAS behavior."""
        unknowns = [
            dependent_function,
            sp.diff(dependent_function, independent),
            sp.diff(dependent_function, independent, 2),
        ]
        try:
            sp.linear_eq_to_matrix([expression], unknowns)
        except ValueError as exc:
            raise CalculatorError("Math ERROR: nonlinear second-order ODEs are not supported") from exc

    def _parse_ode_equation(
        self, equation: str, dependent_variable: str, independent_variable: str,
    ) -> tuple[sp.Equality, int, sp.Expr, sp.Symbol]:
        self._validate_ode_variables(dependent_variable, independent_variable)
        normalized = self.normalize(equation)
        self._reject_pde_notation(normalized, dependent_variable)
        if normalized.count("=") > 1:
            raise CalculatorError("Syntax ERROR: diferansiyel denklem yalnız bir = içerebilir")
        if re.search(r"\bODE(?:VALUE|DERIVATIVEONE|DERIVATIVETWO)\b", normalized, flags=re.IGNORECASE):
            raise CalculatorError("Syntax ERROR: ODE ayrılmış ifade adını kullanamaz")
        transformed, derivative_count = self._ode_replace_derivative_notation(
            normalized, dependent_variable, independent_variable,
        )
        if derivative_count == 0:
            foreign = re.search(
                rf"(?<![A-Za-z0-9])d\s*{re.escape(dependent_variable)}\s*/\s*d\s*[A-Za-z](?![A-Za-z0-9])",
                transformed,
            )
            if foreign:
                raise CalculatorError("Syntax ERROR: ODE türevi seçilen bağımsız değişkeni kullanmalıdır")
            raise CalculatorError("Syntax ERROR: ODE birinci veya ikinci türev içermelidir")
        dependent = re.escape(dependent_variable)
        transformed = re.sub(
            rf"(?<![A-Za-z0-9]){dependent}(?![A-Za-z0-9])", "ODEVALUE", transformed,
        )
        if "=" in transformed:
            left_text, right_text = transformed.split("=", 1)
            if not left_text.strip() or not right_text.strip():
                raise CalculatorError("Syntax ERROR: ODE denkleminin iki tarafı da gerekli")
        else:
            left_text, right_text = transformed, "0"
        independent = sp.Symbol(independent_variable)
        dependent_function = sp.Function(dependent_variable)(independent)
        locals_ = self._ode_locals(independent, dependent_function)
        left = self._safe_parse(left_text, locals_)
        right = self._safe_parse(right_text, locals_)
        expression = left - right
        derivatives = expression.atoms(sp.Derivative)
        if not derivatives:
            raise CalculatorError("Syntax ERROR: ODE birinci veya ikinci türev içermelidir")
        orders = []
        for derivative in derivatives:
            if derivative.expr != dependent_function or any(symbol != independent for symbol in derivative.variables):
                raise CalculatorError("Syntax ERROR: yalnız seçilen fonksiyonun türevi desteklenir")
            orders.append(len(derivative.variables))
        order = max(orders)
        if order not in {1, 2}:
            raise CalculatorError("Syntax ERROR: yalnız birinci ve ikinci dereceden ODE desteklenir")
        if order == 2:
            self._validate_second_order_linearity(expression, dependent_function, independent)
        # ``evaluate=False`` always yields a genuine ``Equality`` here; only
        # sympy's general-purpose stub admits the wider comparison-result union.
        return cast(sp.Equality, sp.Eq(left, right, evaluate=False)), order, dependent_function, independent

    @staticmethod
    def _validate_expected_ode_order(expected_order: int | None) -> None:
        """Validate the optional UI-selected order without changing direct-engine defaults."""
        if expected_order is None:
            return
        if isinstance(expected_order, bool) or not isinstance(expected_order, int) or expected_order not in (1, 2):
            raise CalculatorError("Argument ERROR: expected ODE order must be 1 or 2")

    @staticmethod
    def _ode_initial_key(
        key: object, dependent_variable: str, independent_variable: str,
    ) -> tuple[str, str | None]:
        if not isinstance(key, str):
            raise CalculatorError("Argument ERROR: başlangıç koşulu adı metin olmalıdır")
        compact = key.replace(" ", "").replace("\u2032", "'").replace("\u2019", "'").lower()
        dependent, independent = dependent_variable.lower(), independent_variable.lower()
        if compact in {"x0", f"{independent}0", "point"}:
            return "point", None
        if compact in {"y0", f"{dependent}0", "value"}:
            return "value", None
        if compact in {
            "dy0", f"d{dependent}0", f"d{dependent}/d{independent}0", f"{dependent}'0", "derivative", "slope",
        }:
            return "derivative", None
        value_match = re.fullmatch(rf"{re.escape(dependent)}\((.+)\)", compact)
        if value_match:
            return "value", value_match.group(1)
        derivative_match = re.fullmatch(
            rf"(?:d{re.escape(dependent)}/d{re.escape(independent)}|{re.escape(dependent)}')\((.+)\)", compact,
        )
        if derivative_match:
            return "derivative", derivative_match.group(1)
        raise CalculatorError("Argument ERROR: başlangıç koşulu x0, y0 veya dy0 olmalıdır")

    def _parse_ode_initial_value(self, value: object, locals_: dict[str, object], *, label: str) -> sp.Expr:
        if isinstance(value, bool):
            raise CalculatorError(f"Argument ERROR: {label} geçersiz")
        if isinstance(value, str):
            result = self._safe_parse(value, locals_)
        elif isinstance(value, (sp.Basic, int, float, complex, np.number)):
            result = cast(sp.Expr, sp.sympify(value))
        else:
            raise CalculatorError(f"Argument ERROR: {label} metin veya sayı olmalıdır")
        if result.has(sp.oo, -sp.oo, sp.zoo, sp.nan):
            raise CalculatorError(f"Math ERROR: {label} sonlu olmalıdır")
        return result

    @staticmethod
    def _split_ode_initial_condition_entries(text: str) -> list[str]:
        """Split compact conditions without breaking function argument lists.

        Condition pairs are separated by a top-level comma or semicolon, but
        the safe expression grammar also permits function calls such as
        ``log(8,2)``.  Splitting every comma would reject that valid input
        before it reaches the expression parser.
        """
        entries: list[str] = []
        start = 0
        depth = 0
        for index, character in enumerate(text):
            if character == "(":
                depth += 1
            elif character == ")" and depth > 0:
                depth -= 1
            elif character in {",", ";"} and depth == 0:
                entry = text[start:index].strip()
                if entry:
                    entries.append(entry)
                start = index + 1
        entry = text[start:].strip()
        if entry:
            entries.append(entry)
        return entries

    def _ode_initial_conditions(
        self,
        initial_conditions: Mapping[object, object] | str | None,
        *,
        order: int,
        dependent_variable: str,
        independent_variable: str,
        dependent_function: sp.Expr,
        independent: sp.Symbol,
    ) -> tuple[dict[sp.Expr, sp.Expr] | None, str]:
        if initial_conditions is None or (isinstance(initial_conditions, str) and not initial_conditions.strip()):
            return None, ""
        if isinstance(initial_conditions, str):
            pieces = self._split_ode_initial_condition_entries(initial_conditions)
            if not pieces or any("=" not in piece for piece in pieces):
                raise CalculatorError("Argument ERROR: başlangıç koşulları x0=…, y0=… biçiminde olmalıdır")
            # ``str.split(..., 1)`` returns a variable-length ``list[str]`` to a type
            # checker even though the ``"=" in piece`` guard above guarantees exactly
            # two parts; unpacking into named halves keeps the tuple's arity precise.
            entries: list[tuple[object, object]] = []
            for piece in pieces:
                key, value = piece.split("=", 1)
                entries.append((key, value))
        elif isinstance(initial_conditions, Mapping):
            try:
                entries = list(islice(initial_conditions.items(), _MAX_ODE_INITIAL_CONDITIONS + 1))
            except Exception as exc:
                raise CalculatorError("Argument ERROR: initial conditions could not be read") from exc
            if len(entries) > _MAX_ODE_INITIAL_CONDITIONS:
                raise CalculatorError("Argument ERROR: at most three initial conditions are allowed")
        else:
            raise CalculatorError("Argument ERROR: başlangıç koşulları metin veya eşleme olmalıdır")
        locals_ = self._ode_locals(independent, dependent_function)
        parsed: dict[str, sp.Expr] = {}
        for raw_key, raw_value in entries:
            key, point_from_key = self._ode_initial_key(raw_key, dependent_variable, independent_variable)
            if key in parsed:
                raise CalculatorError("Argument ERROR: başlangıç koşulu birden fazla verildi")
            parsed[key] = self._parse_ode_initial_value(raw_value, locals_, label=f"başlangıç {key} değeri")
            if point_from_key is not None:
                point = self._parse_ode_initial_value(point_from_key, locals_, label="başlangıç noktası")
                if "point" in parsed and sp.simplify(parsed["point"] - point) != 0:
                    raise CalculatorError("Argument ERROR: başlangıç koşulları farklı noktalara ait")
                parsed["point"] = point
        if {"point", "value"} - set(parsed):
            raise CalculatorError("Argument ERROR: başlangıç koşulları x0 ve y0 birlikte gerektirir")
        if order == 1 and "derivative" in parsed:
            raise CalculatorError("Argument ERROR: birinci dereceden ODE için y'(x0) girilmez")
        if order == 2 and "derivative" not in parsed:
            raise CalculatorError("Argument ERROR: ikinci dereceden ODE için dy0 gereklidir")
        point = parsed["point"]
        _finite_real_float(point, "Math ERROR: başlangıç noktası sonlu reel olmalıdır")
        for key, value in parsed.items():
            if key != "point" and (value.has(independent) or value.has(dependent_function)):
                raise CalculatorError("Math ERROR: başlangıç değeri bağımsız veya bağımlı değişken içeremez")
        conditions = {dependent_function.subs(independent, point): parsed["value"]}
        if order == 2:
            conditions[sp.diff(dependent_function, independent).subs(independent, point)] = parsed["derivative"]
        shown = ", ".join(f"{key}={value}" for key, value in parsed.items())
        return conditions, shown

    def solve_ode(
        self, equation: str, dependent_variable: str = "y", independent_variable: str = "x",
        initial_conditions: Mapping[object, object] | str | None = None,
        expected_order: int | None = None,
    ) -> sp.Equality:
        """Solve a scalar first/second-order symbolic ODE with optional initial data.

        Calculator notation accepts ``dy/dx``/``d2y/dx2`` as well as
        ``y'``/``y''``.  Initial data is either a mapping or compact text such
        as ``x0=0, y0=1, dy0=0``.  ``expected_order`` is an optional UI guard;
        omitted callers retain the direct-engine behavior of accepting either
        supported equation order.
        """
        self._validate_expected_ode_order(expected_order)
        ode, order, dependent_function, independent = self._parse_ode_equation(
            equation, dependent_variable, independent_variable,
        )
        if expected_order is not None and order != expected_order:
            raise CalculatorError(
                f"Argument ERROR: selected ODE order {expected_order} does not match equation order {order}"
            )
        conditions, condition_text = self._ode_initial_conditions(
            initial_conditions,
            order=order,
            dependent_variable=dependent_variable,
            independent_variable=independent_variable,
            dependent_function=dependent_function,
            independent=independent,
        )
        try:
            result = self._run_cas("dsolve", {
                "equation": ode, "function": dependent_function, "ics": conditions,
            })
        except Exception as exc:
            raise CalculatorError("Math ERROR: diferansiyel denklem kapalı biçimde çözülemedi") from exc
        if isinstance(result, (list, tuple)):
            if len(result) != 1:
                raise CalculatorError("Math ERROR: diferansiyel denklem tek bir çözüm vermedi")
            result = result[0]
        if not isinstance(result, sp.Equality) or result.has(sp.Integral):
            raise CalculatorError("Math ERROR: diferansiyel denklem kapalı biçimde çözülemedi")
        history_expression = f"ODE {equation}; {dependent_variable}({independent_variable})"
        if condition_text:
            history_expression += f"; {condition_text}"
        self._commit_outcome(self._calculus_history_outcome(
            result,
            ans=result,
            expression=history_expression,
            rendered=self.format_result(result),
            kind="ode",
            metadata={
                "equation": equation,
                "independent_variable": independent_variable,
                "dependent_function": dependent_variable,
                "initial_conditions": condition_text,
            },
        ))
        return result
