"""Structured, UI-neutral semantic results for advanced mathematics."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class ResultStatus(StrEnum):
    SYSTEM_ERROR = "system_error"
    INVALID_INPUT = "invalid_input"
    DOMAIN_ERROR = "domain_error"
    MATHEMATICAL_NON_EXISTENCE = "mathematical_non_existence"
    RESOURCE_LIMIT = "resource_limit"
    TIMEOUT = "timeout"
    LIMIT_EXISTS = "limit_exists"
    LIMIT_POSITIVE_INFINITY = "limit_positive_infinity"
    LIMIT_NEGATIVE_INFINITY = "limit_negative_infinity"
    LIMIT_COMPLEX_INFINITY = "limit_complex_infinity"
    LIMIT_DOES_NOT_EXIST = "limit_does_not_exist"
    LIMIT_UNDETERMINED = "limit_undetermined"
    DERIVATIVE_EXISTS = "derivative_exists"
    DERIVATIVE_DOES_NOT_EXIST = "derivative_does_not_exist"
    DERIVATIVE_UNDEFINED_AT_POINT = "derivative_undefined_at_point"
    DERIVATIVE_UNDETERMINED = "derivative_undetermined"
    INTEGRAL_EXISTS = "integral_exists"
    INTEGRAL_DIVERGES = "integral_diverges"
    INTEGRAL_UNDEFINED = "integral_undefined"
    INTEGRAL_UNDETERMINED = "integral_undetermined"
    INTEGRAL_UNEVALUATED = "integral_unevaluated"
    INTEGRAL_NO_ELEMENTARY_FORM = "integral_no_elementary_form"


@dataclass(frozen=True, slots=True)
class CalculationResult[T]:
    """A value plus its mathematical meaning, independent of LCD wording."""

    status: ResultStatus
    value: T | None = None
    exact_value: object | None = None
    approx_value: object | None = None
    message_code: str = ""
    metadata: dict[str, object] = field(default_factory=dict)

    @property
    def exists(self) -> bool:
        return self.status in {
            ResultStatus.LIMIT_EXISTS,
            ResultStatus.LIMIT_POSITIVE_INFINITY,
            ResultStatus.LIMIT_NEGATIVE_INFINITY,
            ResultStatus.LIMIT_COMPLEX_INFINITY,
            ResultStatus.DERIVATIVE_EXISTS,
            ResultStatus.INTEGRAL_EXISTS,
            ResultStatus.INTEGRAL_NO_ELEMENTARY_FORM,
        }
