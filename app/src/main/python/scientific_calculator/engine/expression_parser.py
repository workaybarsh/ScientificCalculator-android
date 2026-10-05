"""Restricted AST evaluation for calculator expressions.

This module deliberately does not parse source text or resolve calculator state.
The compatibility facade owns lexical normalization and trusted bindings, while
this boundary accepts only an already-transformed Python expression AST and a
fixed binding map.  It never calls ``eval`` or exposes Python builtins.
"""

from __future__ import annotations

import ast
import math
import operator
import re
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass
from fractions import Fraction
from typing import Any, cast

import numpy as np
import sympy as sp

from ..errors import CalculatorError

_TRANSFORMED_NUMBER = re.compile(r"^[+-]?(?:(?:\d+(?:\.\d*)?)|(?:\.\d+))(?:[eE][+-]?\d+)?$")
_ALLOWED_BINARY_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
}
_ALLOWED_UNARY_OPERATORS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


@dataclass(frozen=True, slots=True)
class ExpressionSafetyLimits:
    """Resource bounds enforced before a safe AST operation is evaluated."""

    max_ast_nodes: int = 1_024
    max_ast_depth: int = 64
    max_abs_numeric_exponent: int = 10_000
    max_factorial_input: int = 10_000
    max_combinatoric_input: int = 10_000
    max_exact_decimal_digits: int = 4_096


def _decimal_digit_upper_bound(value: object) -> int:
    integer = abs(int(cast(Any, value)))
    if integer < 10:
        return 1
    # Avoids decimal-string conversion for enormous Python integers.
    return max(1, math.ceil(integer.bit_length() * math.log10(2)))


def require_exact_digit_budget(value: object, message: str, limits: ExpressionSafetyLimits) -> None:
    """Reject a SymPy exact value whose rational atoms exceed the display budget."""
    if not isinstance(value, sp.Basic):
        return
    digits = 0
    for atom in value.atoms(sp.Rational):
        if isinstance(atom, sp.Integer):
            digits += _decimal_digit_upper_bound(atom)
        else:
            digits += _decimal_digit_upper_bound(atom.p)
            digits += _decimal_digit_upper_bound(atom.q)
        if digits > limits.max_exact_decimal_digits:
            raise CalculatorError(message)


def require_exact_resource_budget(value: object, limits: ExpressionSafetyLimits) -> None:
    """Bound exact intermediate results before later operations amplify them."""
    require_exact_digit_budget(value, "Math ERROR: kesin sonuç hesaplama sınırını aşıyor", limits)


def exact_nonnegative_integer(value: object) -> int | None:
    """Return a concrete non-negative integer without coercing symbolic values."""
    try:
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, sp.Integer)):
            result = int(cast(Any, value))
            return result if result >= 0 else None
        if isinstance(value, sp.Basic) and not value.free_symbols and value.is_integer is True:
            result = int(cast(Any, value))
            return result if result >= 0 else None
    except (TypeError, ValueError, OverflowError):
        return None
    return None


def estimated_factorial_digits(value: int) -> int:
    """Return a conservative decimal-digit count for ``value!``."""
    if value < 2:
        return 1
    return int(math.lgamma(value + 1) / math.log(10)) + 1


def require_estimated_digits(digits: int, limits: ExpressionSafetyLimits) -> None:
    """Reject a prospective exact result before SymPy materializes it."""
    if digits > limits.max_exact_decimal_digits:
        raise CalculatorError("Math ERROR: sayısal sonuç görüntüleme sınırını aşıyor")


def preflight_factorial(value: object, limits: ExpressionSafetyLimits) -> None:
    """Check an exact factorial result before calling its trusted binding."""
    integer = exact_nonnegative_integer(value)
    if integer is not None:
        require_estimated_digits(estimated_factorial_digits(integer), limits)


def preflight_power(base: object, exponent: object, limits: ExpressionSafetyLimits) -> None:
    """Reject oversized exact integer or rational powers before creating them."""
    try:
        if isinstance(base, bool) or not isinstance(base, (int, Fraction, sp.Rational)):
            return
        if not isinstance(exponent, (int, sp.Integer)) or isinstance(exponent, bool):
            return
        exponent_value = int(exponent)
        if exponent_value == 0:
            return
        if isinstance(base, Fraction):
            numerator, denominator = base.numerator, base.denominator
        elif isinstance(base, sp.Rational):
            numerator, denominator = int(base.p), int(base.q)
        else:
            numerator, denominator = int(base), 1
        if numerator == 0:
            return
        if exponent_value < 0:
            numerator, denominator = denominator, numerator
            exponent_value = -exponent_value
        digits = 0
        for component in (numerator, denominator):
            magnitude = abs(component)
            if magnitude not in {0, 1}:
                digits += int(exponent_value * math.log10(magnitude)) + 1
        require_estimated_digits(max(1, digits), limits)
    except OverflowError:
        raise CalculatorError("Math ERROR: üs sonucu çok büyük") from None


def constant_numeric_approx(node: ast.AST) -> float | None:
    """Return a bounded-cost numeric approximation, or ``None`` for symbols."""
    try:
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool):
                return None
            if isinstance(node.value, (int, float)):
                return float(node.value)
            if isinstance(node.value, str) and _TRANSFORMED_NUMBER.fullmatch(node.value):
                return float(node.value)
            return None
        if isinstance(node, ast.UnaryOp) and type(node.op) in _ALLOWED_UNARY_OPERATORS:
            value = constant_numeric_approx(node.operand)
            return None if value is None else _ALLOWED_UNARY_OPERATORS[type(node.op)](value)
        if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_BINARY_OPERATORS:
            left = constant_numeric_approx(node.left)
            right = constant_numeric_approx(node.right)
            if left is None or right is None:
                return None
            if isinstance(node.op, ast.Pow):
                try:
                    return math.pow(left, right)
                except OverflowError:
                    return math.inf
                except ValueError:
                    # Legitimate complex expressions are not resource amplification.
                    return None
            return float(_ALLOWED_BINARY_OPERATORS[type(node.op)](left, right))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            name = node.func.id
            args = [constant_numeric_approx(argument) for argument in node.args]
            if any(argument is None for argument in args):
                return None
            numeric_args = cast(list[float], args)
            if name in {"Integer", "Float"} and len(args) == 1:
                return float(numeric_args[0])
            if name == "Rational" and len(args) == 2 and numeric_args[1] != 0:
                return float(numeric_args[0] / numeric_args[1])
            if name == "factorial" and len(args) == 1:
                value = numeric_args[0]
                if value < 0 or not value.is_integer():
                    return None
                if value > 170:
                    return math.inf
                return float(math.factorial(int(value)))
            if name in {"nPr", "nCr"} and len(args) == 2:
                count, selection = numeric_args
                if count < 0 or selection < 0 or not count.is_integer() or not selection.is_integer():
                    return None
                if selection > count:
                    return None
                operation = math.perm if name == "nPr" else math.comb
                return float(operation(int(count), int(selection)))
    except (OverflowError, ZeroDivisionError):
        return math.inf
    except (TypeError, ValueError):
        return None
    return None


def evaluated_numeric_approx(value: object) -> float | None:
    """Return a numeric approximation after safe child evaluation, if concrete."""
    try:
        if isinstance(value, bool):
            return None
        if isinstance(value, (complex, np.complexfloating)):
            real = float(value.real)
            imaginary = float(value.imag)
            if not math.isfinite(real) or not math.isfinite(imaginary):
                return math.inf
            return math.hypot(real, imaginary)
        if isinstance(value, (int, float, Fraction, np.number)):
            try:
                return float(value)
            except OverflowError:
                return math.inf
        if not isinstance(value, sp.Basic) or value.free_symbols:
            return None
        if value in (sp.oo, -sp.oo, sp.zoo, sp.nan):
            return math.inf
        if value.is_number is not True:
            return None
        try:
            numeric = sp.N(value, 18)
            if numeric.is_finite is False:
                return math.inf
            if numeric.is_real is True:
                return float(numeric)
            as_complex = complex(numeric)
            if not math.isfinite(as_complex.real) or not math.isfinite(as_complex.imag):
                return math.inf
            return math.hypot(as_complex.real, as_complex.imag)
        except OverflowError:
            return math.inf
    except (TypeError, ValueError):
        return None


class RestrictedExpression:
    """Validate and interpret only a fixed whitelist of arithmetic AST nodes.

    ``bindings`` are supplied by the caller's trusted facade.  Names are never
    resolved from Python globals and a binding is callable only when both its
    name and AST shape have passed the explicit allowlist.
    """

    def __init__(
        self,
        bindings: Mapping[str, object],
        allowed_call_names: Collection[str],
        limits: ExpressionSafetyLimits | None = None,
    ) -> None:
        self.bindings = dict(bindings)
        self.allowed_call_names = frozenset(allowed_call_names)
        self.limits = limits or ExpressionSafetyLimits()
        self.node_count = 0

    def validate(self, node: ast.AST, depth: int = 0) -> None:
        """Reject every syntax shape and resource amplification outside policy."""
        self.node_count += 1
        if self.node_count > self.limits.max_ast_nodes or depth > self.limits.max_ast_depth:
            raise CalculatorError("Syntax ERROR: İfade çok karmaşık")

        if isinstance(node, ast.Expression):
            self.validate(node.body, depth + 1)
            return
        if isinstance(node, ast.BinOp):
            if type(node.op) not in _ALLOWED_BINARY_OPERATORS:
                raise CalculatorError("Syntax ERROR: İşleme izin verilmez")
            if isinstance(node.op, ast.Pow):
                exponent = constant_numeric_approx(node.right)
                if exponent is not None and (
                    not math.isfinite(exponent) or abs(exponent) > self.limits.max_abs_numeric_exponent
                ):
                    raise CalculatorError("Math ERROR: Üs çok büyük")
            self.validate(node.left, depth + 1)
            self.validate(node.right, depth + 1)
            return
        if isinstance(node, ast.UnaryOp):
            if type(node.op) not in _ALLOWED_UNARY_OPERATORS:
                raise CalculatorError("Syntax ERROR: İşleme izin verilmez")
            self.validate(node.operand, depth + 1)
            return
        if isinstance(node, ast.Call):
            function_name = node.func.id if isinstance(node.func, ast.Name) else None
            if (
                function_name is None
                or function_name not in self.allowed_call_names
                or function_name not in self.bindings
                or not callable(self.bindings[function_name])
                or node.keywords
            ):
                raise CalculatorError("Syntax ERROR: Fonksiyona izin verilmez")
            if function_name == "factorial" and node.args:
                argument = constant_numeric_approx(node.args[0])
                if argument is not None and (
                    not math.isfinite(argument) or argument > self.limits.max_factorial_input
                ):
                    raise CalculatorError("Math ERROR: Faktöriyel girdisi çok büyük")
            if function_name in {"nPr", "nCr"}:
                for argument_node in node.args:
                    argument = constant_numeric_approx(argument_node)
                    if argument is not None and (
                        not math.isfinite(argument) or abs(argument) > self.limits.max_combinatoric_input
                    ):
                        raise CalculatorError("Math ERROR: Kombinatorik girdi çok büyük")
            for argument_node in node.args:
                self.validate(argument_node, depth + 1)
            return
        if isinstance(node, ast.Name):
            if node.id not in self.bindings or node.id == "__builtins__":
                raise CalculatorError(f"Syntax ERROR: Bilinmeyen ad: {node.id}")
            return
        if isinstance(node, ast.Constant):
            value = node.value
            if isinstance(value, bool) or value is None or value is Ellipsis:
                raise CalculatorError("Syntax ERROR: Matematik dışı sabit")
            if isinstance(value, (int, float)):
                return
            # Trusted SymPy transformations emit numeric strings only for Float.
            if isinstance(value, str) and _TRANSFORMED_NUMBER.fullmatch(value):
                return
            raise CalculatorError("Syntax ERROR: Matematik dışı sabit")
        # Attribute, collections, subscripts, comprehensions, and statements
        # are rejected even if future lexical changes make them reachable.
        raise CalculatorError("Syntax ERROR: İfade yapısına izin verilmez")

    def evaluate(self, node: ast.AST) -> object:
        """Interpret a previously validated AST using only trusted bindings."""
        if isinstance(node, ast.Expression):
            return self.evaluate(node.body)
        if isinstance(node, ast.BinOp):
            operation = _ALLOWED_BINARY_OPERATORS[type(node.op)]
            left = self.evaluate(node.left)
            right = self.evaluate(node.right)
            if isinstance(node.op, ast.Pow):
                exponent = evaluated_numeric_approx(right)
                if exponent is not None and (
                    not math.isfinite(exponent) or abs(exponent) > self.limits.max_abs_numeric_exponent
                ):
                    raise CalculatorError("Math ERROR: Üs çok büyük")
                preflight_power(left, right, self.limits)
            result = operation(left, right)
            require_exact_resource_budget(result, self.limits)
            return result
        if isinstance(node, ast.UnaryOp):
            return _ALLOWED_UNARY_OPERATORS[type(node.op)](self.evaluate(node.operand))
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name):
                raise CalculatorError("Syntax ERROR: Fonksiyona izin verilmez")
            function_name = node.func.id
            function = cast(Callable[..., object], self.bindings[function_name])
            arguments = tuple(self.evaluate(argument_node) for argument_node in node.args)
            if function_name == "factorial" and arguments:
                argument = evaluated_numeric_approx(arguments[0])
                if argument is not None and (
                    not math.isfinite(argument) or argument > self.limits.max_factorial_input
                ):
                    raise CalculatorError("Math ERROR: Faktöriyel girdisi çok büyük")
                preflight_factorial(arguments[0], self.limits)
            if function_name in {"nPr", "nCr"}:
                for argument_value in arguments:
                    argument = evaluated_numeric_approx(argument_value)
                    if argument is not None and (
                        not math.isfinite(argument) or abs(argument) > self.limits.max_combinatoric_input
                    ):
                        raise CalculatorError("Math ERROR: Kombinatorik girdi çok büyük")
            return function(*arguments)
        if isinstance(node, ast.Name):
            return self.bindings[node.id]
        if isinstance(node, ast.Constant):
            return node.value
        raise CalculatorError("Syntax ERROR: İfade yapısına izin verilmez")

    def evaluate_checked(self, node: ast.AST) -> object:
        """Validate then evaluate one AST without relying on caller sequencing."""
        self.validate(node)
        return self.evaluate(node)


__all__ = [
    "ExpressionSafetyLimits",
    "RestrictedExpression",
    "constant_numeric_approx",
    "evaluated_numeric_approx",
    "exact_nonnegative_integer",
    "estimated_factorial_digits",
    "preflight_factorial",
    "preflight_power",
    "require_estimated_digits",
    "require_exact_digit_budget",
    "require_exact_resource_budget",
]
