"""Independent restricted evaluator for calculator Base-N expressions."""

from __future__ import annotations

import ast
import operator
import re
from typing import Any, cast

from ..errors import CalculatorError

SUPPORTED_BASES = frozenset({2, 8, 10, 16})
_SOURCE_LIMIT = 2_048


def to_32bit(value: int) -> int:
    """Wrap an integer into the calculator's unsigned 32-bit register."""
    return value & 0xFFFFFFFF


def signed32(value: int) -> int:
    """Interpret one calculator register as a signed 32-bit integer."""
    value &= 0xFFFFFFFF
    return value - 0x100000000 if value & 0x80000000 else value


def _truncating_integer_division(left: int, right: int) -> int:
    """Divide integer registers with calculator-style truncation toward zero."""
    if right == 0:
        raise ZeroDivisionError("division by zero")
    quotient = abs(left) // abs(right)
    return -quotient if (left < 0) ^ (right < 0) else quotient


def _require_base(base: object) -> int:
    if base not in SUPPORTED_BASES:
        raise CalculatorError("Argument ERROR: Geçersiz taban")
    # ``base`` is one of ``SUPPORTED_BASES`` by construction here, so this
    # cannot raise; the cast only tells pyright what the membership check
    # already guarantees at runtime.
    return int(cast(Any, base))


def parse_base_token(token: object, base: object) -> int:
    """Parse one explicit Base-N token and apply signed-register semantics."""
    checked_base = _require_base(base)
    try:
        value = int(str(token).strip().upper(), checked_base)
    except (TypeError, ValueError) as exc:
        raise CalculatorError("Syntax ERROR: geçersiz tabanlı sayı") from exc
    return signed32(value) if checked_base != 10 else value


def base_operation(left: object, right: object | None = None, operation: str = "and") -> int:
    """Apply one logical 32-bit register operation."""
    first = to_32bit(int(cast(Any, left)))
    second = to_32bit(int(cast(Any, right or 0)))
    if operation == "and":
        result = first & second
    elif operation == "or":
        result = first | second
    elif operation == "xor":
        result = first ^ second
    elif operation == "xnor":
        result = ~(first ^ second)
    elif operation == "Not":
        result = ~first
    elif operation == "Neg":
        result = -signed32(first)
    else:
        raise CalculatorError("Argument ERROR")
    return signed32(result)


def format_base(value: object, base: object) -> str:
    """Format one register in a calculator Base-N display representation."""
    checked_base = _require_base(base)
    register = to_32bit(int(cast(Any, value)))
    if checked_base == 10:
        return str(signed32(register))
    if checked_base == 16:
        return f"{register:08X}" if signed32(register) < 0 else f"{register:X}"
    if checked_base == 8:
        return f"{register:011o}" if signed32(register) < 0 else f"{register:o}"
    return f"{register:032b}" if signed32(register) < 0 else f"{register:b}"


def evaluate_base(text: object, current_base: object = 10) -> int:
    """Evaluate a bounded Base-N expression with a dedicated AST whitelist."""
    checked_base = _require_base(current_base)
    source = str(text).strip().replace("×", "*").replace("÷", "/").replace("−", "-")
    if not source:
        raise CalculatorError("Syntax ERROR")
    if len(source) > _SOURCE_LIMIT:
        raise CalculatorError("Syntax ERROR: Base-N ifadesi çok uzun")
    if "@" in source:
        raise CalculatorError("Syntax ERROR: geçersiz Base-N ifadesi")
    prefix_bases = {"d": 10, "h": 16, "b": 2, "o": 8}
    logical_words = {"and", "or", "xor", "xnor", "not", "neg"}
    base_patterns = {
        2: re.compile(r"^[01]+$", re.I),
        8: re.compile(r"^[0-7]+$", re.I),
        10: re.compile(r"^[0-9]+$", re.I),
        16: re.compile(r"^[0-9A-F]+$", re.I),
    }

    def numeric_token(match: re.Match[str]) -> str:
        token = match.group(0)
        lower = token.lower()
        if lower in logical_words:
            return token
        if len(token) > 1 and lower[0] in prefix_bases:
            explicit_base = prefix_bases[lower[0]]
            payload = token[1:]
            if base_patterns[explicit_base].fullmatch(payload):
                return str(parse_base_token(payload, explicit_base))
        if base_patterns[checked_base].fullmatch(token):
            return str(parse_base_token(token, checked_base))
        raise CalculatorError("Syntax ERROR: geçersiz Base-N ifadesi")

    source = re.sub(r"(?<![A-Za-z0-9_])[A-Za-z0-9_]+(?![A-Za-z0-9_])", numeric_token, source)
    # MatMult is an internal sentinel with multiplicative precedence. Raw '@'
    # input was rejected before only the xnor keyword reaches this AST node.
    source = re.sub(r"\bxnor\b", "@", source, flags=re.I)
    source = re.sub(r"\bxor\b", "^", source, flags=re.I)
    source = re.sub(r"\band\b", "&", source, flags=re.I)
    source = re.sub(r"\bor\b", "|", source, flags=re.I)
    source = re.sub(r"\bNot\s*\(", "~(", source, flags=re.I)
    source = re.sub(r"\bNeg\s*\(", "-(", source, flags=re.I)
    operations = {
        ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
        ast.Div: _truncating_integer_division, ast.BitAnd: operator.and_,
        ast.BitOr: operator.or_, ast.BitXor: operator.xor,
        ast.MatMult: lambda first, second: ~(first ^ second),
        ast.Invert: operator.invert, ast.USub: operator.neg,
    }

    def evaluate_node(node: ast.AST) -> int:
        if isinstance(node, ast.Expression):
            return evaluate_node(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, int) and not isinstance(node.value, bool):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in operations:
            return operations[type(node.op)](evaluate_node(node.left), evaluate_node(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in operations:
            return operations[type(node.op)](evaluate_node(node.operand))
        raise CalculatorError("Syntax ERROR: geçersiz Base-N ifadesi")

    try:
        result = evaluate_node(ast.parse(source, mode="eval"))
    except ZeroDivisionError as exc:
        raise CalculatorError("Math ERROR: division by zero") from exc
    except CalculatorError:
        raise
    except (SyntaxError, TypeError, ValueError) as exc:
        raise CalculatorError("Syntax ERROR: geçersiz Base-N ifadesi") from exc
    return signed32(result)
