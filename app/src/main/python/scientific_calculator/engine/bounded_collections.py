"""Bounded materialization helpers shared by matrix, vector, and statistics APIs."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from itertools import islice
from typing import cast

import numpy as np

from ..errors import CalculatorError


def bounded_iterable(
    values: object,
    *,
    maximum: int,
    invalid_message: str,
    limit_message: str,
    array_maximum: int | None = None,
) -> list[object] | np.ndarray:
    """Materialize a finite API iterable without trusting its reported length."""
    if isinstance(values, np.ndarray):
        if values.ndim == 0:
            raise CalculatorError(invalid_message)
        if values.size > (maximum if array_maximum is None else array_maximum):
            raise CalculatorError(limit_message)
        return values
    try:
        materialized = list(islice(iter(cast(Iterable[object], values)), maximum + 1))
    except Exception as exc:
        raise CalculatorError(invalid_message) from exc
    if len(materialized) > maximum:
        raise CalculatorError(limit_message)
    return materialized


def bounded_mapping_items(
    values: object,
    *,
    maximum: int,
    invalid_message: str,
    limit_message: str,
) -> list[tuple[object, object]]:
    """Read mapping entries without allowing an endless custom mapping."""
    if not isinstance(values, Mapping):
        raise CalculatorError(invalid_message)
    try:
        raw_items = list(islice(iter(values.items()), maximum + 1))
    except Exception as exc:
        raise CalculatorError(invalid_message) from exc
    if len(raw_items) > maximum:
        raise CalculatorError(limit_message)
    if not all(isinstance(item, tuple) and len(item) == 2 for item in raw_items):
        raise CalculatorError(invalid_message)
    return cast(list[tuple[object, object]], raw_items)


def bounded_matrix_array(
    values: object,
    *,
    maximum_dimension: int,
    invalid_message: str,
    limit_message: str,
) -> np.ndarray:
    """Convert only a bounded matrix candidate to a numeric array."""
    raw: list[object] | np.ndarray
    if isinstance(values, np.ndarray) and values.ndim == 0:
        raw = values
    else:
        raw = bounded_iterable(
            values,
            maximum=maximum_dimension,
            invalid_message=invalid_message,
            limit_message=limit_message,
            array_maximum=maximum_dimension**2,
        )
    if isinstance(raw, np.ndarray):
        if raw.ndim == 2 and (raw.shape[0] > maximum_dimension or raw.shape[1] > maximum_dimension):
            raise CalculatorError(limit_message)
    else:
        raw = [
            bounded_iterable(
                row,
                maximum=maximum_dimension,
                invalid_message=invalid_message,
                limit_message=limit_message,
                array_maximum=maximum_dimension,
            )
            if isinstance(row, Iterable)
            and not isinstance(row, (str, bytes))
            and not (isinstance(row, np.ndarray) and row.ndim == 0)
            else row
            for row in raw
        ]
    try:
        return np.asarray(raw, dtype=float)
    except (TypeError, ValueError, OverflowError) as exc:
        raise CalculatorError(invalid_message) from exc


def bounded_vector_array(
    values: object,
    *,
    maximum_dimension: int,
    invalid_message: str,
    limit_message: str,
) -> np.ndarray:
    """Convert only a bounded vector candidate to a numeric array."""
    raw: list[object] | np.ndarray
    if isinstance(values, np.ndarray) and values.ndim == 0:
        raw = values
    else:
        raw = bounded_iterable(
            values,
            maximum=maximum_dimension,
            invalid_message=invalid_message,
            limit_message=limit_message,
            array_maximum=maximum_dimension,
        )
    try:
        return np.asarray(raw, dtype=float)
    except (TypeError, ValueError, OverflowError) as exc:
        raise CalculatorError(invalid_message) from exc
