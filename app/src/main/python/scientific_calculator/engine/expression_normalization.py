"""Pure lexical normalization for the restricted expression parser."""

from __future__ import annotations

import re
from collections.abc import Collection

from ..errors import CalculatorError


def normalize_expression(text: object, *, maximum_length: int, allowed_call_names: Collection[str]) -> str:
    """Normalize calculator notation before AST validation, preserving limits."""
    if not isinstance(text, str):
        raise CalculatorError("Syntax ERROR: İfade metin olmalıdır")
    if len(text) > maximum_length:
        raise CalculatorError("Syntax ERROR: İfade çok uzun")
    normalized = text.strip().replace("×", "*").replace("÷", "/").replace("−", "-")
    normalized = normalized.replace("π", "pi").replace("√", "sqrt")
    normalized = normalized.replace("^", "**").replace("²", "**2").replace("³", "**3")
    normalized = rewrite_postfix_percent(normalized, allowed_call_names)
    normalized = re.sub(r"(sin|cos|tan)([A-FMxy])", r"\1(\2)", normalized)
    normalized = re.sub(r"(sin|cos|tan)(pi)\b", r"\1(\2)", normalized)
    if "∠" in normalized:
        left, right = normalized.split("∠", 1)
        normalized = f"polar(({left}),({right}))"
    if len(normalized) > maximum_length:
        raise CalculatorError("Syntax ERROR: İfade çok uzun")
    return normalized


def rewrite_postfix_percent(text: str, allowed_call_names: Collection[str]) -> str:
    """Rewrite calculator postfix percent while retaining the operand boundary."""
    result = text
    while "%" in result:
        index = result.index("%")
        prefix = result[:index]
        if not prefix.rstrip():
            raise CalculatorError("Syntax ERROR: yüzde için sol değer gerekli")
        end = len(prefix.rstrip())
        start = percent_operand_start(prefix[:end], allowed_call_names)
        if start is None:
            raise CalculatorError("Syntax ERROR: yüzde için geçerli sol değer gerekli")
        result = f"{prefix[:start]}({prefix[start:end]}/100){result[index + 1 :]}"
    return result


def percent_operand_start(prefix: str, allowed_call_names: Collection[str]) -> int | None:
    """Locate the primary expression immediately left of a percent sign."""
    end = len(prefix)
    if end == 0:
        return None
    if prefix[-1] == ")":
        depth = 0
        for position in range(end - 1, -1, -1):
            if prefix[position] == ")":
                depth += 1
            elif prefix[position] == "(":
                depth -= 1
                if depth == 0:
                    start = position
                    name_match = re.search(r"[A-Za-z]+$", prefix[:start])
                    if name_match and name_match.group() in allowed_call_names:
                        start = name_match.start()
                    return start
        return None
    if prefix[-1] == "!":
        return percent_operand_start(prefix[:-1], allowed_call_names)
    number = re.search(r"(?i)(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?$", prefix)
    if number:
        return number.start()
    name = re.search(r"[A-Za-z]+$", prefix)
    return name.start() if name else None
