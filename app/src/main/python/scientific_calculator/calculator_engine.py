from __future__ import annotations

import ast
import io
import math
import operator
import re
import tokenize
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any, cast

import numpy as np
import sympy as sp
from sympy.parsing.sympy_parser import (
    auto_symbol,
    convert_xor,
    implicit_multiplication_application,
    standard_transformations,
    stringify_expr,
)

from .calculation_errors import CalculationTimeout
from .cas_worker import CASExecutionMode, CASExecutionPolicy, CASWorkerError, run_cas
from .engine.angles import angle_to_radians, radians_to_angle
from .engine.base_n import base_operation as _base_operation
from .engine.base_n import evaluate_base as _evaluate_base
from .engine.base_n import format_base as _format_base
from .engine.base_n import parse_base_token as _parse_base_token
from .engine.bounded_collections import bounded_iterable as _bounded_iterable
from .engine.bounded_collections import bounded_mapping_items as _bounded_mapping_items
from .engine.bounded_collections import bounded_matrix_array as _bounded_matrix_array_service
from .engine.bounded_collections import bounded_vector_array as _bounded_vector_array_service
from .engine.complex_numbers import complex_argument as _complex_argument
from .engine.complex_numbers import from_polar as _from_polar
from .engine.complex_numbers import to_polar as _to_polar
from .engine.conversions import CONVERSIONS, convert_value
from .engine.distributions import distribution as _distribution
from .engine.equations import polynomial_roots as _polynomial_roots
from .engine.equations import solve_inequality as _solve_inequality
from .engine.equations import solve_ratio as _solve_ratio
from .engine.equations import solve_simultaneous as _solve_simultaneous
from .engine.expression_normalization import normalize_expression as _normalize_expression
from .engine.expression_normalization import percent_operand_start as _percent_operand_start_service
from .engine.expression_normalization import rewrite_postfix_percent as _rewrite_postfix_percent_service
from .engine.expression_parser import ExpressionSafetyLimits, RestrictedExpression
from .engine.expression_parser import evaluated_numeric_approx as _evaluated_numeric_approx
from .engine.expression_parser import exact_nonnegative_integer as _exact_nonnegative_integer
from .engine.expression_parser import require_estimated_digits as _parser_require_estimated_digits
from .engine.expression_parser import require_exact_digit_budget as _parser_require_exact_digit_budget
from .engine.linear_algebra import identity_matrix as _identity_matrix
from .engine.linear_algebra import matrix_operation as _matrix_operation
from .engine.linear_algebra import validate_matrix_definition as _validate_matrix_definition
from .engine.linear_algebra import validate_vector_definition as _validate_vector_definition
from .engine.linear_algebra import vector_operation as _vector_operation
from .engine.numeric_tools import decimal_from_dms as _decimal_from_dms
from .engine.numeric_tools import dms_from_decimal as _dms_from_decimal
from .engine.numeric_tools import prime_factorization as _prime_factorization
from .engine.numeric_tools import random_int as _random_int
from .engine.numeric_tools import random_number as _random_number
from .engine.outcomes import EngineOutcome
from .engine.regression import normal_p as _normal_p
from .engine.regression import normal_q as _normal_q
from .engine.regression import normal_r as _normal_r
from .engine.regression import regression_fit as _regression_fit
from .engine.result_formatter import ResultFormatter
from .engine.settings import CalculatorSettings
from .engine.state_defaults import default_matrices as _default_matrices
from .engine.state_defaults import default_memory as _default_memory
from .engine.state_defaults import default_vectors as _default_vectors
from .engine.state_defaults import reset_memory_values as _reset_memory_values
from .engine.statistics import one_variable_statistics as _one_variable_statistics
from .errors import CalculatorError
from .history import CalculationHistoryEntry, HistoryValue
from .numeric_validation import (
    finite_real_float as _finite_real_float,
)
from .numeric_validation import (
    require_finite_math_result as _require_finite_math_result,
)

SAFE_TRANSFORMS = tuple(t for t in standard_transformations if t is not auto_symbol) + (
    implicit_multiplication_application,
    convert_xor,
)

# SymPy's transformations need these numeric constructors. They are bindings for
# the restricted AST interpreter below; Python eval and builtins are never used.
SAFE_GLOBALS = {
    "__builtins__": {},
    "Integer": sp.Integer,
    "Float": sp.Float,
    "Rational": sp.Rational,
    "factorial": sp.factorial,
}

_ALLOWED_EXPR_CHARS = re.compile(r"^[0-9A-Za-z+\-*/().,!\s]*$")
# A repeated postfix ``!`` is not calculator syntax; see ``_safe_parse``.
_DOUBLE_FACTORIAL = re.compile(r"!\s*!")
_FORBIDDEN_WORDS = {
    "lambda",
    "import",
    "from",
    "eval",
    "exec",
    "compile",
    "open",
    "input",
    "globals",
    "locals",
    "getattr",
    "setattr",
    "delattr",
    "hasattr",
    "vars",
    "dir",
    "type",
    "object",
    "class",
    "for",
    "while",
    "if",
    "else",
    "try",
    "except",
    "finally",
    "with",
    "yield",
    "return",
    "raise",
    "assert",
    "pass",
    "break",
    "continue",
    "and",
    "or",
    "not",
    "is",
    "in",
    "True",
    "False",
    "None",
    "help",
    "memoryview",
    "bytearray",
    "bytes",
    "str",
    "int",
    "float",
}

_ALLOWED_CALL_NAMES = frozenset(
    {
        "Integer",
        "Float",
        "Rational",
        "factorial",
        "sqrt",
        "cbrt",
        "Abs",
        "abs",
        "ln",
        "log",
        "exp",
        "sin",
        "cos",
        "tan",
        "asin",
        "acos",
        "atan",
        "sinh",
        "cosh",
        "tanh",
        "asinh",
        "acosh",
        "atanh",
        "nPr",
        "nCr",
        "conj",
        "conjugate",
        "re",
        "im",
        "arg",
        "polar",
    }
)
_MAX_ADJACENT_PRODUCT_LETTERS = 64
_MAX_EXPRESSION_CHARS = 2_048
_MAX_BATCH_EXPRESSIONS = 10
_MAX_EXPANDED_STATS_SAMPLES = 1_000_000
_MAX_SUMMATION_TERMS = 1_000_000
_MAX_EXACT_STATISTICS_FREQUENCY = 2**53 - 1
_MAX_COLLECTION_ITEMS = 10_000
_MAX_SIMULTANEOUS_DIMENSION = 4
_MAX_POLYNOMIAL_COEFFICIENTS = 5
_MAX_EVALUATE_WITH_VALUES = 26
_MAX_MATRIX_DIMENSION = 4
_MAX_VECTOR_DIMENSION = 3


def _bounded_matrix_array(
    values: object,
    *,
    invalid_message: str,
    limit_message: str,
) -> np.ndarray:
    """Convert only a bounded matrix candidate to a numeric NumPy array."""
    return _bounded_matrix_array_service(
        values,
        maximum_dimension=_MAX_MATRIX_DIMENSION,
        invalid_message=invalid_message,
        limit_message=limit_message,
    )


def _bounded_vector_array(
    values: object,
    *,
    invalid_message: str,
    limit_message: str,
) -> np.ndarray:
    """Convert only a bounded vector candidate to a numeric NumPy array."""
    return _bounded_vector_array_service(
        values,
        maximum_dimension=_MAX_VECTOR_DIMENSION,
        invalid_message=invalid_message,
        limit_message=limit_message,
    )


# ``ExpressionSafetyLimits`` declares these bounds beside the parser that
# enforces them.  Restating them here would create a second source of truth
# that could drift silently; pass an explicit instance only to change policy.
_PARSER_LIMITS = ExpressionSafetyLimits()


def _require_exact_display_budget(value: object) -> None:
    _parser_require_exact_digit_budget(value, "Math ERROR: kesin sonuç görüntüleme sınırını aşıyor", _PARSER_LIMITS)


def _estimated_combinatoric_digits(n: int, r: int, *, permutation: bool) -> int:
    if r < 0 or r > n:
        return 1
    if permutation:
        logarithm = math.lgamma(n + 1) - math.lgamma(n - r + 1)
    else:
        logarithm = math.lgamma(n + 1) - math.lgamma(r + 1) - math.lgamma(n - r + 1)
    return max(1, int(logarithm / math.log(10)) + 1)


def _require_estimated_digits(digits: int) -> None:
    _parser_require_estimated_digits(digits, _PARSER_LIMITS)


class _RestrictedExpression(RestrictedExpression):
    """Bind the parser to this facade's call allowlist and safety limits."""

    def __init__(self, bindings: Mapping[str, object]):
        super().__init__(bindings, _ALLOWED_CALL_NAMES, _PARSER_LIMITS)


def _finite_exact_integer(value: object, message: str) -> int:
    """Return a finite, concrete integer without truncating a symbolic value."""
    try:
        if isinstance(value, bool):
            raise ValueError("boolean is not an integer bound")
        if isinstance(value, (int, np.integer)):
            return int(value)
        if isinstance(value, (float, np.floating)):
            if not math.isfinite(float(value)) or not float(value).is_integer():
                raise ValueError("non-integral float")
            return int(value)
        if (
            isinstance(value, sp.Basic)
            and not value.free_symbols
            and value.is_finite is True
            and value.is_integer is True
        ):
            return int(cast(Any, value))
    except (TypeError, ValueError, OverflowError) as exc:
        raise CalculatorError(message) from exc
    raise CalculatorError(message)


def _combinatoric(n, r, *, permutation: bool):
    """Apply calculator (not generalized SymPy) domain rules for nPr/nCr."""
    numeric_n, numeric_r = _evaluated_numeric_approx(n), _evaluated_numeric_approx(r)
    if (
        numeric_n is not None
        and numeric_r is not None
        and (
            not math.isfinite(numeric_n)
            or not math.isfinite(numeric_r)
            or not numeric_n.is_integer()
            or not numeric_r.is_integer()
            or numeric_n < 0
            or numeric_r < 0
            or numeric_r > numeric_n
        )
    ):
        raise CalculatorError("Math ERROR")
    exact_n, exact_r = _exact_nonnegative_integer(n), _exact_nonnegative_integer(r)
    if exact_n is not None and exact_r is not None:
        _require_estimated_digits(_estimated_combinatoric_digits(exact_n, exact_r, permutation=permutation))
    if permutation:
        return sp.factorial(n) / sp.factorial(n - r)
    return sp.binomial(n, r)


# Re-exported so the documented facade keeps every constants entry point.
from .calculus import CalculusMixin
from .constants_data import CONSTANTS_DATASET_LABEL as CONSTANTS_DATASET_LABEL
from .constants_data import CONSTANTS_DATASET_LABELS as CONSTANTS_DATASET_LABELS
from .constants_data import CURRENT_CONSTANTS as CURRENT_CONSTANTS
from .constants_data import CURRENT_CONSTANTS_DATASET_LABEL as CURRENT_CONSTANTS_DATASET_LABEL
from .constants_data import LEGACY_CONSTANTS as LEGACY_CONSTANTS
from .constants_data import LEGACY_CONSTANTS_DATASET_LABEL as LEGACY_CONSTANTS_DATASET_LABEL
from .constants_data import constants_for_dataset as constants_for_dataset


@dataclass
class ScientificCalculatorEngine(CalculusMixin):
    settings: CalculatorSettings = field(default_factory=CalculatorSettings)
    ans: sp.Expr = sp.Integer(0)
    memory: dict[str, sp.Expr] = field(default_factory=_default_memory)
    history: list[CalculationHistoryEntry] = field(default_factory=list)
    matrices: dict[str, np.ndarray | None] = field(default_factory=_default_matrices)
    mat_ans: np.ndarray | None = None
    vectors: dict[str, np.ndarray | None] = field(default_factory=_default_vectors)
    vct_ans: np.ndarray | None = None
    # Direct engine consumers get a bounded CAS process. The UI worker turns
    # this off so it remains the sole child process that cancellation owns.
    cas_isolated: bool = field(default=True, repr=False, compare=False)
    cas_timeout: float | None = field(default=30.0, repr=False, compare=False)

    def _run_cas(self, operation: str, payload: dict[str, object]):
        return run_cas(
            operation,
            payload,
            policy=CASExecutionPolicy(
                CASExecutionMode.ISOLATED if self.cas_isolated else CASExecutionMode.INLINE,
                self.cas_timeout,
            ),
        )

    def _run_cas_checked(self, operation: str, payload: dict[str, object]):
        """Run a CAS operation whose failure has one type in either mode.

        ``run_cas`` converts a SymPy failure into ``CASWorkerError`` only when
        the operation runs in a child process.  The desktop worker runs CAS
        inline, where the raw SymPy exception would escape instead and reach
        the LCD as ``Internal ERROR``.  Callers with a domain-level fallback
        use this wrapper so that fallback runs in both modes.
        """
        try:
            return self._run_cas(operation, payload)
        except (CalculatorError, CalculationTimeout, CASWorkerError):
            raise
        except Exception as exc:
            raise CASWorkerError(type(exc).__name__, str(exc)[:500]) from exc

    def _angle_to_rad(self, x):
        return angle_to_radians(x, self.settings.angle_unit)

    def _rad_to_angle(self, x):
        return radians_to_angle(x, self.settings.angle_unit)

    def locals(self, extra=None):
        d = {
            "pi": sp.pi,
            "e": sp.E,
            "i": sp.I,
            "I": sp.I,
            "Ans": self.ans,
            **self.memory,
            "sqrt": sp.sqrt,
            "cbrt": lambda x: sp.real_root(x, 3),
            "Abs": sp.Abs,
            "abs": sp.Abs,
            "ln": sp.log,
            "log": lambda x, b=10: sp.log(x, b),
            "exp": sp.exp,
            "sin": lambda x: sp.sin(self._angle_to_rad(x)),
            "cos": lambda x: sp.cos(self._angle_to_rad(x)),
            "tan": lambda x: sp.tan(self._angle_to_rad(x)),
            "asin": lambda x: self._rad_to_angle(sp.asin(x)),
            "acos": lambda x: self._rad_to_angle(sp.acos(x)),
            "atan": lambda x: self._rad_to_angle(sp.atan(x)),
            "sinh": sp.sinh,
            "cosh": sp.cosh,
            "tanh": sp.tanh,
            "asinh": sp.asinh,
            "acosh": sp.acosh,
            "atanh": sp.atanh,
            "factorial": sp.factorial,
            "nPr": lambda n, r: _combinatoric(n, r, permutation=True),
            "nCr": lambda n, r: _combinatoric(n, r, permutation=False),
            "conj": sp.conjugate,
            "conjugate": sp.conjugate,
            "re": sp.re,
            "im": sp.im,
            "arg": lambda z: self._rad_to_angle(sp.arg(z)),
            "polar": lambda r, th: r * (sp.cos(self._angle_to_rad(th)) + sp.I * sp.sin(self._angle_to_rad(th))),
        }
        if extra:
            for name, value in extra.items():
                if not isinstance(name, str) or len(name) != 1 or not name.isascii() or not name.isalpha():
                    raise CalculatorError("Syntax ERROR: Değişken tek harf olmalıdır")
                if (
                    isinstance(value, bool)
                    or callable(value)
                    or not isinstance(value, (sp.Basic, int, float, complex, Fraction, np.number))
                ):
                    raise CalculatorError("Syntax ERROR: Geçersiz değişken değeri")
            d.update(extra)
        return d

    @staticmethod
    def normalize(text: str) -> str:
        return _normalize_expression(text, maximum_length=_MAX_EXPRESSION_CHARS, allowed_call_names=_ALLOWED_CALL_NAMES)

    @staticmethod
    def _rewrite_postfix_percent(text: str) -> str:
        return _rewrite_postfix_percent_service(text, _ALLOWED_CALL_NAMES)

    @staticmethod
    def _percent_operand_start(prefix: str) -> int | None:
        return _percent_operand_start_service(prefix, _ALLOWED_CALL_NAMES)

    def _safe_parse(self, text: str, local_dict: dict[str, object]) -> sp.Expr:
        normalized = self.normalize(text)
        if not normalized.strip():
            raise CalculatorError("Syntax ERROR: Boş ifade")
        if not _ALLOWED_EXPR_CHARS.fullmatch(normalized):
            raise CalculatorError("Syntax ERROR: Matematik dışı karakter")
        if "__" in normalized or "//" in normalized or _DOUBLE_FACTORIAL.search(normalized):
            # ``factorial_notation`` rewrites a repeated ``!`` into a SymPy
            # ``factorial2`` call the user never typed.  Rejecting the syntax
            # here keeps that internal name out of the "unknown name" message.
            raise CalculatorError("Syntax ERROR: Geçersiz ifade")
        parenthesis_depth = 0
        for character in normalized:
            if character == "(":
                parenthesis_depth += 1
            elif character == ")":
                parenthesis_depth -= 1
                if parenthesis_depth < 0:
                    raise CalculatorError("Syntax ERROR: unmatched closing parenthesis")
        if parenthesis_depth:
            raise CalculatorError("Syntax ERROR: unmatched opening parenthesis")
        # Block attribute access (x.real, func.__class__, etc.) while preserving decimal points.
        if re.search(r"(?:[A-Za-z][A-Za-z0-9]*|\))\s*\.", normalized):
            raise CalculatorError("Syntax ERROR: Özellik erişimine izin verilmez")

        safe_locals = dict(local_dict)
        product_letters = {
            name
            for name, value in safe_locals.items()
            if len(name) == 1 and name.isascii() and name.isalpha() and not callable(value)
        }
        try:
            tokens = tokenize.generate_tokens(io.StringIO(normalized).readline)
            names = [tok.string for tok in tokens if tok.type == tokenize.NAME]
        except (tokenize.TokenError, IndentationError) as exc:
            raise CalculatorError("Syntax ERROR: Geçersiz ifade") from exc

        for name in names:
            if name in _FORBIDDEN_WORDS:
                raise CalculatorError("Syntax ERROR: Matematik dışı ifade")
            if name in safe_locals:
                continue
            if name in {"Integer", "Float", "Rational"}:
                # These constructors are emitted by trusted SymPy transforms
                # and are explicitly allowlisted below.  Expose them here as
                # well so safe symbolic input such as ``Rational(2, 3)`` can
                # be used in calculus expressions.
                safe_locals[name] = SAFE_GLOBALS[name]
                continue
            # Equation/SOLVE/Table/Sum variables are intentionally limited to simple
            # single-letter symbols. Longer names must be an explicitly whitelisted
            # calculator function or constant.
            if len(name) == 1 and name.isascii() and name.isalpha():
                safe_locals[name] = sp.Symbol(name)
                continue
            if len(name) > 1 and all(char in product_letters for char in name):
                if len(name) > _MAX_ADJACENT_PRODUCT_LETTERS:
                    raise CalculatorError("Syntax ERROR: Bitişik çarpım ifadesi çok karmaşık")
                product = sp.Integer(1)
                for char in name:
                    product *= safe_locals[char]
                safe_locals[name] = product
                continue
            raise CalculatorError(f"Syntax ERROR: Bilinmeyen ad: {name}")

        try:
            transformed = stringify_expr(
                normalized,
                local_dict=safe_locals,
                global_dict=SAFE_GLOBALS,
                transformations=SAFE_TRANSFORMS,
            )
            syntax_tree = ast.parse(transformed, mode="eval")
            bindings = {k: v for k, v in SAFE_GLOBALS.items() if k != "__builtins__"}
            bindings.update(safe_locals)
            # Numeric constructors are emitted by the trusted transformations and
            # may not be replaced by caller-provided locals.
            for name in ("Integer", "Float", "Rational"):
                bindings[name] = SAFE_GLOBALS[name]
            restricted = _RestrictedExpression(bindings)
            result = restricted.evaluate_checked(syntax_tree)
            if callable(result) or isinstance(result, (tuple, list, dict, set)):
                raise CalculatorError("Syntax ERROR: Matematiksel ifade bekleniyor")
            if not isinstance(result, sp.Basic):
                result = sp.sympify(result)
            if not isinstance(result, sp.Basic):
                raise CalculatorError("Syntax ERROR: Matematiksel ifade bekleniyor")
            # The restricted grammar (arithmetic, whitelisted calls, numeric
            # literals) never produces a non-``Expr`` ``Basic`` such as a
            # ``Boolean`` or ``Relational``; the cast records that invariant.
            return cast(sp.Expr, result)
        except CalculatorError:
            raise
        except Exception as exc:
            # ``exc`` is raised by SymPy, tokenize, or ast and its text is an
            # internal detail.  ``translate_error_message`` only sanitizes
            # Turkish wording, so interpolating an English internal message
            # here would put it on the LCD verbatim.  Report the stable
            # category instead and keep the cause for debugging.
            raise CalculatorError("Syntax ERROR: Geçersiz ifade") from exc

    def parse(self, text: str, extra=None) -> sp.Expr:
        return self._safe_parse(text, self.locals(extra))

    def symbolic_locals(self, extra=None):
        """CAS işlemleri için trigonometrik fonksiyonları standart radyan değişkeniyle yorumlar."""
        d = self.locals(extra)
        d.update(
            {
                "sin": sp.sin,
                "cos": sp.cos,
                "tan": sp.tan,
                "asin": sp.asin,
                "acos": sp.acos,
                "atan": sp.atan,
                "sinh": sp.sinh,
                "cosh": sp.cosh,
                "tanh": sp.tanh,
                "asinh": sp.asinh,
                "acosh": sp.acosh,
                "atanh": sp.atanh,
                # Symbolic calculus follows standard mathematical convention:
                # ``log`` and ``ln`` both mean the natural logarithm.  Interactive
                # calculator evaluation retains its base-10 ``log`` in ``locals``.
                "ln": sp.log,
                "log": sp.log,
                "exp": sp.exp,
            }
        )
        return d

    def parse_symbolic(self, text: str, extra=None) -> sp.Expr:
        return self._safe_parse(text, self.symbolic_locals(extra))

    def equation_symbols(self, equation: str, adjacent_letters=None):
        """Bellek değerlerine bakmadan denklemde yazılı değişkenleri bulur."""
        approved_adjacent = set(self.memory)
        for name in adjacent_letters or ():
            if isinstance(name, str) and len(name) == 1 and name.isascii() and name.isalpha():
                approved_adjacent.add(name)
        names = set()
        try:
            tokens = tokenize.generate_tokens(io.StringIO(self.normalize(equation)).readline)
            for token in tokens:
                if token.type != tokenize.NAME:
                    continue
                name = token.string
                if len(name) == 1 and name.isascii() and name.isalpha():
                    names.add(name)
                elif len(name) > 1 and all(char in approved_adjacent for char in name):
                    names.update(name)
        except (tokenize.TokenError, IndentationError):
            names.update(re.findall(r"(?<![A-Za-z_])[A-Za-z](?![A-Za-z_])", equation))
        # e, i gibi matematik sabitlerini değişken sayma. pi zaten iki harfli.
        names.difference_update({"e", "i", "I"})
        # Hesap makinesi bellek değişkenlerine öncelik ver; diğer tek harfleri de koru.
        symbols = {name: sp.Symbol(name) for name in names}
        parts = equation.split("=", 1)
        found = set()
        for part in parts:
            if not part.strip():
                continue
            try:
                expr = self.parse_symbolic(part, symbols)
                found.update(str(x) for x in expr.free_symbols)
            except CalculatorError:
                # Asıl SOLVE çağrısı daha açıklayıcı syntax hatasını üretecek.
                found.update(names)
        return sorted(found)

    def _remember_history(
        self, expression: str, result: str, *, kind: str = "legacy", metadata: dict[str, HistoryValue] | None = None
    ) -> None:
        self.history.append(
            CalculationHistoryEntry(str(expression), str(result), kind, {} if metadata is None else metadata)
        )
        del self.history[:-10]

    def _commit_outcome(self, outcome: EngineOutcome):
        """Commit a completed use case's state changes at one facade boundary."""
        if outcome.updates_ans:
            self.ans = cast(sp.Expr, outcome.ans)
        for name, value in outcome.memory_updates.items():
            self.memory[name] = cast(sp.Expr, value)
        self.history.extend(outcome.history)
        del self.history[:-10]
        return outcome.value

    def evaluate(self, text: str, exact: bool = True):
        if not isinstance(text, str):
            raise CalculatorError("Syntax ERROR: İfade metin olmalıdır")
        if len(text) > _MAX_EXPRESSION_CHARS:
            raise CalculatorError("Syntax ERROR: İfade çok uzun")
        raw_parts = text.split(":")
        if any(not part.strip() for part in raw_parts):
            raise CalculatorError("Syntax ERROR: Empty batch expression")
        parts = [part.strip() for part in raw_parts]
        if len(parts) > _MAX_BATCH_EXPRESSIONS:
            raise CalculatorError("Syntax ERROR: Çok fazla ardışık ifade")
        outputs = []
        pending_history = []
        # Ans must remain the value before the complete multi-expression
        # operation. Commit both it and history only once all parts succeed.
        saved_ans = self.ans
        try:
            for part in parts:
                if "=" in part:
                    raise CalculatorError("Denklem için SOLVE kullanın; kırmızı = yalnız denklem girdisidir.")
                expr = self.parse(part)
                if exact and self.settings.input_output in ("MathI/MathO", "LineI/LineO"):
                    val = self._run_cas("simplify", {"expression": expr})
                else:
                    val = sp.N(expr, 15)
                _require_finite_math_result(val)
                pending_history.append(CalculationHistoryEntry(part, self.format_result(val, approximate=not exact)))
                outputs.append(val)
                # Later colon-separated expressions can intentionally use
                # Ans, but history remains transactional until final commit.
                self.ans = val
        except Exception:
            self.ans = saved_ans
            raise
        return self._commit_outcome(EngineOutcome(outputs[-1], ans=outputs[-1], history=tuple(pending_history)))

    def evaluate_with_values(self, text: str, values: Mapping[str, object]):
        items = _bounded_mapping_items(
            values,
            maximum=_MAX_EVALUATE_WITH_VALUES,
            invalid_message="Argument ERROR: variable values must be a mapping",
            limit_message="Argument ERROR: too many variable values",
        )
        numeric_values: dict[str, float] = {}
        for key, value in items:
            if not isinstance(key, str) or len(key) != 1 or not key.isascii() or not key.isalpha():
                raise CalculatorError("Argument ERROR: variable names must be single letters")
            numeric_values[key] = _finite_real_float(value, "Math ERROR: variable values must be finite and real")
        extra = {key: sp.Float(value) for key, value in numeric_values.items()}
        expr = self.parse(text.split("=", 1)[0] if "=" in text else text, extra)
        val = sp.N(expr, 15)
        _require_finite_math_result(val)
        memory_updates = {key: sp.Float(value) for key, value in numeric_values.items() if key in self.memory}
        return self._commit_outcome(
            EngineOutcome(
                val,
                ans=val,
                memory_updates=memory_updates,
                history=(CalculationHistoryEntry(text, self.format_result(val, approximate=True)),),
            )
        )

    def solve(self, equation: str, variable="x", guess=0.0, known_values=None):
        known_items = (
            []
            if known_values is None
            else _bounded_mapping_items(
                known_values,
                maximum=_MAX_EVALUATE_WITH_VALUES,
                invalid_message="Argument ERROR: known values must be a mapping",
                limit_message="Argument ERROR: too many known values",
            )
        )
        numeric_known_items: list[tuple[str, float]] = []
        for key, value in known_items:
            if not isinstance(key, str):
                raise CalculatorError("Argument ERROR: known value names must be strings")
            numeric_known_items.append(
                (
                    key,
                    _finite_real_float(value, "Math ERROR: known values must be finite and real"),
                )
            )
        var = sp.Symbol(variable)
        guess_value = _finite_real_float(guess, "Cannot Solve: başlangıç tahmini sonlu reel olmalıdır")
        # Bütün denklem değişkenlerini önce sembol olarak tut; yalnız bilinenleri sonradan sayıya çevir.
        symbol_names = self.equation_symbols(equation, {variable, *(key for key, _ in numeric_known_items)})
        symbol_map = {name: sp.Symbol(name) for name in symbol_names}
        symbol_map[variable] = var
        if "=" in equation:
            l, r = equation.split("=", 1)
            f = self.parse_symbolic(l, symbol_map) - self.parse_symbolic(r, symbol_map)
        else:
            f = self.parse_symbolic(equation, symbol_map)
        if numeric_known_items:
            f = f.subs({sp.Symbol(key): sp.Float(value) for key, value in numeric_known_items})
        leftovers = sorted((s for s in f.free_symbols if s != var), key=lambda z: str(z))
        if leftovers:
            raise CalculatorError("Variable ERROR: Bilinen değer girilmeli: " + ", ".join(map(str, leftovers)))
        _require_finite_math_result(f, "Cannot Solve: denklem tanımsız")
        try:
            root = self._run_cas_checked(
                "nsolve",
                {"expression": f, "symbol": var, "guess": guess_value, "tol": 1e-14, "maxsteps": 100, "prec": 40},
            )
        except CASWorkerError:
            # nsolve başlangıç tahmininde zorlanırsa cebirsel çözümler arasından tahmine en yakın reel kökü seç.
            try:
                sols = self._run_cas_checked("solve", {"expression": f, "symbol": var})
                real_sols = []
                for sol in sols:
                    n = complex(sp.N(sol, 30))
                    if abs(n.imag) < 1e-10:
                        real_sols.append((abs(n.real - guess_value), n.real))
                if not real_sols:
                    raise ValueError
                root = sp.Float(min(real_sols)[1], 30)
            except Exception as exc:
                raise CalculatorError("Cannot Solve: Başlangıç tahminini değiştirin") from exc
        root_value = _finite_real_float(root, "Cannot Solve: sonlu reel kök bulunamadı")
        residual = sp.N(f.subs(var, root), 40)
        _finite_real_float(residual, "Cannot Solve: kök doğrulanamadı")
        if residual != 0:
            slope = sp.N(
                self._run_cas(
                    "differentiate_at_point",
                    {
                        "expression": f,
                        "symbol": var,
                        "point": root,
                    },
                ),
                40,
            )
            slope_value = _finite_real_float(slope, "Cannot Solve: kök doğrulanamadı")
            if slope_value == 0:
                raise CalculatorError("Cannot Solve: kök doğrulanamadı")
            correction = sp.N(residual / slope, 40)
            correction_value = abs(_finite_real_float(correction, "Cannot Solve: kök doğrulanamadı"))
            if correction_value > 1e-10 * max(1.0, abs(root_value)):
                raise CalculatorError("Cannot Solve: kök doğrulanamadı")
        residual_value = float(sp.re(residual))
        memory_updates = {variable: root} if variable in self.memory else {}
        return self._commit_outcome(
            EngineOutcome(
                (root_value, residual_value),
                ans=root,
                memory_updates=memory_updates,
                history=(
                    CalculationHistoryEntry(
                        f"solve {equation} for {variable}",
                        f"{variable}={root_value:.12g}; L-R={residual_value:.4g}",
                    ),
                ),
            )
        )

    def symbolic_integral(self, integrand, variable="x"):
        self._validate_calculus_variable(variable)
        x = sp.Symbol(variable)
        expr = self.parse_symbolic(integrand, {variable: x})
        try:
            result = self._run_cas("indefinite_integral", {"expression": expr, "symbol": x})
        except Exception as exc:
            raise CalculatorError("Math ERROR: sembolik integral alınamadı") from exc
        if self._has_unresolved_integral(result):
            raise CalculatorError("Math ERROR: integral kapalı biçimde bulunamadı")
        result = self._run_cas("simplify", {"expression": result})
        if self._has_unresolved_integral(result):
            raise CalculatorError("Math ERROR: integral kapalı biçimde bulunamadı")
        self.ans = result
        self._remember_history(
            f"∫ {integrand} d{variable}",
            f"{self.format_result(result)} + C",
            kind="integral_indefinite",
            metadata={"integrand": str(integrand), "variables": (variable,), "bounds": None},
        )
        return result

    def symbolic_derivative(self, expression, variable="x"):
        self._validate_calculus_variable(variable)
        x = sp.Symbol(variable)
        expr = self.parse_symbolic(expression, {variable: x})
        try:
            result = self._run_cas("differentiate", {"expression": expr, "symbol": x})
        except Exception as exc:
            raise CalculatorError("Math ERROR: sembolik türev alınamadı") from exc
        result = self._run_cas("simplify", {"expression": result})
        self.ans = result
        self._remember_history(
            f"d/d{variable} {expression}",
            self.format_result(result),
            kind="derivative",
            metadata={"expression": str(expression), "variable": variable, "order": 1, "evaluation_point": None},
        )
        return result

    def derivative(self, expression, point, variable="x", tol=1e-10):
        # Noktasal türev, mevcut açı birimini koruyan sayısal hesaplamadır.
        try:
            tolerance = float(tol)
        except (TypeError, ValueError) as exc:
            raise CalculatorError("Argument ERROR: türev toleransı pozitif sonlu sayı olmalıdır") from exc
        if not math.isfinite(tolerance) or not 0 < tolerance <= 1e-2:
            raise CalculatorError("Argument ERROR: türev toleransı pozitif sonlu sayı olmalıdır")
        x = sp.Symbol(variable)
        expr = self.parse(expression, {variable: x})
        point_expr = self.parse(point)
        a = _finite_real_float(point_expr, "Math ERROR: türev noktası sonlu reel olmalıdır")
        try:
            exact_at = self._run_cas(
                "differentiate_at_point",
                {
                    "expression": expr,
                    "symbol": x,
                    "point": point_expr,
                },
            )
            exact_at = self._run_cas("simplify", {"expression": exact_at})
            if isinstance(exact_at, sp.Basic) and exact_at.is_number is True:
                result = _finite_real_float(exact_at, "Math ERROR: türev bu noktada sonlu reel değil")
                self.ans = sp.Float(result)
                self._remember_history(
                    f"d/d{variable} {expression} | {variable}={point}",
                    self.format_result(result, approximate=True),
                    kind="derivative",
                    metadata={
                        "expression": str(expression),
                        "variable": variable,
                        "order": 1,
                        "evaluation_point": str(point),
                    },
                )
                return result
        except CalculatorError:
            raise
        except Exception:
            pass
        h = max(1e-7, min(1e-3, tolerance ** (1 / 3)) * max(1.0, abs(a)))
        try:
            fn = sp.lambdify(x, expr, modules=["math"])
            at_point = _finite_real_float(fn(a), "Math ERROR: fonksiyon türev noktasında tanımsız")
            result = None
            for _ in range(12):
                left = _finite_real_float(fn(a - h), "Math ERROR: türev örneklemi sonlu reel değil")
                right = _finite_real_float(fn(a + h), "Math ERROR: türev örneklemi sonlu reel değil")
                left_two = _finite_real_float(fn(a - 2 * h), "Math ERROR: türev örneklemi sonlu reel değil")
                right_two = _finite_real_float(fn(a + 2 * h), "Math ERROR: türev örneklemi sonlu reel değil")
                coarse_right = (-3 * at_point + 4 * right - right_two) / (2 * h)
                coarse_left = (3 * at_point - 4 * left + left_two) / (2 * h)
                half_h = h / 2
                left_half = _finite_real_float(fn(a - half_h), "Math ERROR: türev örneklemi sonlu reel değil")
                right_half = _finite_real_float(fn(a + half_h), "Math ERROR: türev örneklemi sonlu reel değil")
                left_two_half = _finite_real_float(fn(a - 2 * half_h), "Math ERROR: türev örneklemi sonlu reel değil")
                right_two_half = _finite_real_float(fn(a + 2 * half_h), "Math ERROR: türev örneklemi sonlu reel değil")
                fine_right = (-3 * at_point + 4 * right_half - right_two_half) / (2 * half_h)
                fine_left = (3 * at_point - 4 * left_half + left_two_half) / (2 * half_h)
                right_derivative = _finite_real_float(
                    fine_right + (fine_right - coarse_right) / 3,
                    "Math ERROR: türev sonucu sonlu reel değil",
                )
                left_derivative = _finite_real_float(
                    fine_left + (fine_left - coarse_left) / 3,
                    "Math ERROR: türev sonucu sonlu reel değil",
                )
                scale = max(1.0, abs(left_derivative), abs(right_derivative))
                if (
                    abs(right_derivative - fine_right) <= tolerance * scale
                    and abs(left_derivative - fine_left) <= tolerance * scale
                    and abs(right_derivative - left_derivative) <= tolerance * scale
                ):
                    result = (left_derivative + right_derivative) / 2
                    break
                h = half_h
            if result is None:
                raise CalculatorError("Math ERROR: türev istenen toleransa yakınsamadı")
        except CalculatorError:
            raise
        except Exception as exc:
            raise CalculatorError("Math ERROR: derivative could not be evaluated") from exc
        self.ans = sp.Float(result)
        self._remember_history(
            f"d/d{variable} {expression} | {variable}={point}",
            self.format_result(result, approximate=True),
            kind="derivative",
            metadata={"expression": str(expression), "variable": variable, "order": 1, "evaluation_point": str(point)},
        )
        return result

    def summation(self, expression, lower, upper, variable="x"):
        lower_value = self.parse(lower)
        upper_value = self.parse(upper)
        a = _finite_exact_integer(lower_value, "Argument ERROR: Σ sınırları tam sayı olmalıdır")
        b = _finite_exact_integer(upper_value, "Argument ERROR: Σ sınırları tam sayı olmalıdır")
        x = sp.Symbol(variable)
        expr = self.parse(expression, {variable: x})
        if max(0, b - a + 1) > _MAX_SUMMATION_TERMS and not expr.is_polynomial(x):
            raise CalculatorError("Math ERROR: Σ aralığı hesaplama sınırını aşıyor")
        try:
            val = self._run_cas_checked("summation", {"expression": expr, "symbol": x, "lower": a, "upper": b})
        except CASWorkerError as exc:
            raise CalculatorError("Math ERROR: Σ hesaplanamadı") from exc
        return self._commit_outcome(
            EngineOutcome(
                val,
                ans=val,
                history=(CalculationHistoryEntry(f"Σ {expression}, {variable}={lower}..{upper}", self.format_result(val)),),
            )
        )

    def pol(self, x, y):
        r = math.hypot(x, y)
        th = math.atan2(y, x)
        if self.settings.angle_unit == "DEG":
            th = math.degrees(th)
        elif self.settings.angle_unit == "GRA":
            th = th * 200 / math.pi
        return r, th

    def rec(self, r, theta):
        if self.settings.angle_unit == "DEG":
            theta = math.radians(theta)
        elif self.settings.angle_unit == "GRA":
            theta = theta * math.pi / 200
        return r * math.cos(theta), r * math.sin(theta)

    def dms_from_decimal(self, x):
        return _dms_from_decimal(x)

    def decimal_from_dms(self, d, m, s):
        return _decimal_from_dms(d, m, s)

    def prime_factorization(self, n: object):
        return _prime_factorization(n, self.parse)

    def random_number(self):
        return _random_number()

    def random_int(self, a: object, b: object):
        return _random_int(a, b, self.parse)

    def store(self, name, value=None):
        if name not in self.memory:
            raise CalculatorError("Argument ERROR: Geçersiz bellek")
        if value is None:
            candidate = self.ans
        else:
            try:
                candidate = self.parse(value) if isinstance(value, str) else sp.sympify(value)
            except CalculatorError:
                raise
            except Exception as exc:
                raise CalculatorError("Memory ERROR: invalid memory value") from exc
        try:
            stored = sp.sympify(candidate)
        except Exception as exc:
            raise CalculatorError("Memory ERROR: invalid memory value") from exc
        if not isinstance(stored, sp.Basic) or stored.free_symbols or stored.is_number is not True:
            raise CalculatorError("Memory ERROR: memory value must be finite")
        _require_finite_math_result(stored, "Memory ERROR: memory value must be finite")
        self.memory[name] = stored
        return stored

    def _update_memory(self, operation):
        """Apply a memory operation without allowing an invalid result to persist."""
        try:
            candidate = sp.N(operation(self.memory["M"], self.ans))
        except Exception as exc:
            raise CalculatorError("Memory ERROR: invalid memory value") from exc
        return self.store("M", candidate)

    def m_plus(self):
        return self._update_memory(operator.add)

    def m_minus(self):
        return self._update_memory(operator.sub)

    def reset_memory(self):
        self.ans = sp.Integer(0)
        _reset_memory_values(self.memory)

    def initialize_all(self):
        self.settings = CalculatorSettings()
        self.reset_memory()
        self.history.clear()
        self.matrices = _default_matrices()
        self.mat_ans = None
        self.vectors = _default_vectors()
        self.vct_ans = None

    # Complex
    def complex_eval(self, text):
        v = sp.N(self.parse(text), 15)
        _require_finite_math_result(v)
        self.ans = v
        self._remember_history(
            text,
            self.format_result(v),
            kind="complex_calculus",
            metadata={"operation": "evaluate", "expression": text},
        )
        return v

    def complex_argument(self, z):
        return _complex_argument(z, self.settings.angle_unit)

    def to_polar(self, z):
        return _to_polar(z, self.settings.angle_unit)

    def from_polar(self, r, theta):
        return _from_polar(r, theta, self.settings.angle_unit)

    # Base-N
    def parse_base_token(self, token, base):
        return _parse_base_token(token, base)

    def base_operation(self, a, b=None, op="and"):
        return _base_operation(a, b, op)

    def format_base(self, value, base):
        return _format_base(value, base)

    def evaluate_base(self, text: str, current_base: int = 10):
        return _evaluate_base(text, current_base)

    # Matrix
    def define_matrix(self, name, data):
        if not isinstance(name, str) or name not in self.matrices:
            raise CalculatorError("Argument ERROR: geçersiz matris adı")
        arr = _bounded_matrix_array(
            data,
            invalid_message="Argument ERROR: geçersiz matris verisi",
            limit_message="Dimension ERROR",
        )
        _validate_matrix_definition(arr, _MAX_MATRIX_DIMENSION)
        self.matrices[name] = arr.copy()
        return arr

    def matrix_op(self, op, a, b=None):
        try:
            A = (
                self.matrices.get(a)
                if isinstance(a, str)
                else _bounded_matrix_array(
                    a,
                    invalid_message="Argument ERROR: geçersiz matris verisi",
                    limit_message="Dimension ERROR",
                )
            )
            B = (
                self.matrices.get(b)
                if isinstance(b, str)
                else (
                    _bounded_matrix_array(
                        b,
                        invalid_message="Argument ERROR: geçersiz matris verisi",
                        limit_message="Dimension ERROR",
                    )
                    if b is not None
                    else None
                )
            )
        except (TypeError, ValueError, OverflowError) as exc:
            raise CalculatorError("Argument ERROR: geçersiz matris verisi") from exc
        if A is None:
            raise CalculatorError("Dimension ERROR: matris tanımsız")
        result = _matrix_operation(op, A, B, _MAX_MATRIX_DIMENSION)
        # Narrow on the positive ``ndarray`` case rather than negate
        # ``isinstance(result, float)``: PEP 484's int/float numeric-tower
        # promotion means excluding ``float`` cannot statically exclude
        # ``int`` from the declared ``ndarray | float`` return type.
        if not isinstance(result, np.ndarray):
            return result
        self.mat_ans = result
        return result

    def identity(self, n):
        self.mat_ans = np.asarray(_identity_matrix(n, _MAX_MATRIX_DIMENSION))
        return self.mat_ans

    # Vector
    def define_vector(self, name, data):
        if not isinstance(name, str) or name not in self.vectors:
            raise CalculatorError("Argument ERROR: geçersiz vektör adı")
        arr = _bounded_vector_array(
            data,
            invalid_message="Argument ERROR: geçersiz vektör verisi",
            limit_message="Dimension ERROR",
        )
        _validate_vector_definition(arr, _MAX_VECTOR_DIMENSION)
        self.vectors[name] = arr.copy()
        return arr

    def vector_op(self, op, a, b=None, scalar=None):
        try:
            A = (
                self.vectors.get(a)
                if isinstance(a, str)
                else _bounded_vector_array(
                    a,
                    invalid_message="Argument ERROR: geçersiz vektör verisi",
                    limit_message="Dimension ERROR",
                )
            )
            B = (
                self.vectors.get(b)
                if isinstance(b, str)
                else (
                    _bounded_vector_array(
                        b,
                        invalid_message="Argument ERROR: geçersiz vektör verisi",
                        limit_message="Dimension ERROR",
                    )
                    if b is not None
                    else None
                )
            )
        except (TypeError, ValueError, OverflowError) as exc:
            raise CalculatorError("Argument ERROR: geçersiz vektör verisi") from exc
        if A is None:
            raise CalculatorError("Dimension ERROR")
        result = _vector_operation(op, A, B, scalar, self.settings.angle_unit, _MAX_VECTOR_DIMENSION)
        if isinstance(result, float):
            return result
        self.vct_ans = np.atleast_1d(result)
        return result

    # Statistics & regression
    def one_var_stats(self, x: Iterable[float], freq: Iterable[float] | None = None):
        try:
            x = np.asarray(
                _bounded_iterable(
                    x,
                    maximum=_MAX_COLLECTION_ITEMS,
                    invalid_message="Argument ERROR: geçersiz veri",
                    limit_message="Argument ERROR: too many statistical values",
                ),
                dtype=float,
            )
        except CalculatorError:
            raise
        except (TypeError, ValueError, OverflowError) as exc:
            raise CalculatorError("Argument ERROR: geçersiz veri") from exc
        if x.ndim != 1:
            raise CalculatorError("Dimension ERROR")
        if x.size == 0:
            raise CalculatorError("Argument ERROR: veri yok")
        if not np.all(np.isfinite(x)):
            raise CalculatorError("Math ERROR: veriler sonlu olmalıdır")
        raw_freq = None
        if freq is not None:
            raw_freq = _bounded_iterable(
                freq,
                maximum=_MAX_COLLECTION_ITEMS,
                invalid_message="Argument ERROR: geçersiz frekans",
                limit_message="Argument ERROR: too many statistical frequencies",
            )
        return _one_variable_statistics(x, raw_freq, _MAX_EXACT_STATISTICS_FREQUENCY, _finite_exact_integer)

    def regression(self, x, y, kind="linear"):
        try:
            x = np.asarray(
                _bounded_iterable(
                    x,
                    maximum=_MAX_COLLECTION_ITEMS,
                    invalid_message="Argument ERROR: geçersiz regresyon verisi",
                    limit_message="Argument ERROR: too many regression values",
                ),
                dtype=float,
            )
            y = np.asarray(
                _bounded_iterable(
                    y,
                    maximum=_MAX_COLLECTION_ITEMS,
                    invalid_message="Argument ERROR: geçersiz regresyon verisi",
                    limit_message="Argument ERROR: too many regression values",
                ),
                dtype=float,
            )
        except CalculatorError:
            raise
        except (TypeError, ValueError, OverflowError) as exc:
            raise CalculatorError("Argument ERROR: geçersiz regresyon verisi") from exc
        if x.ndim != 1 or y.ndim != 1 or len(x) != len(y):
            raise CalculatorError("Dimension ERROR")
        if len(x) < 2:
            raise CalculatorError("Dimension ERROR")
        if not np.all(np.isfinite(x)) or not np.all(np.isfinite(y)):
            raise CalculatorError("Math ERROR: regresyon verileri sonlu olmalıdır")
        return _regression_fit(x, y, kind)

    @staticmethod
    def normal_P(t):
        return _normal_p(t)

    @staticmethod
    def normal_Q(t):
        return _normal_q(t)

    @staticmethod
    def normal_R(t):
        return _normal_r(t)

    # Distributions
    def distribution(self, kind, **kw):
        return _distribution(kind, kw)

    # Equation / inequality / ratio
    def simultaneous(self, A, b):
        return _solve_simultaneous(A, b, _MAX_SIMULTANEOUS_DIMENSION)

    def polynomial_roots(self, coeffs):
        return _polynomial_roots(coeffs, _MAX_POLYNOMIAL_COEFFICIENTS, self.settings.equation_complex)

    def inequality(self, coeffs, relation):
        return _solve_inequality(coeffs, relation, _MAX_POLYNOMIAL_COEFFICIENTS)

    def ratio(self, kind, **kw):
        return _solve_ratio(kind, kw)

    def convert(self, name, value):
        return convert_value(name, value, conversions=CONVERSIONS)

    def format_result(self, value, approximate=False):
        return ResultFormatter(
            self.settings,
            to_polar=self.to_polar,
            run_cas=self._run_cas,
            require_exact_display_budget=_require_exact_display_budget,
        ).format(value, approximate)


def __getattr__(name):
    """Expose ``stats`` without paying SciPy's import cost at startup."""
    if name == "stats":
        from scipy import stats

        return stats
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
