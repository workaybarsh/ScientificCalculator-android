"""Pure, bounded matrix and vector operations for the calculator engine."""

from __future__ import annotations

import math
from typing import Any, cast

import numpy as np

from ..errors import CalculatorError
from ..numeric_validation import finite_real_float


def validate_matrix_definition(matrix: np.ndarray, maximum_dimension: int) -> np.ndarray:
    """Validate a newly materialized matrix before it enters engine state."""
    if matrix.ndim != 2 or not (
        1 <= matrix.shape[0] <= maximum_dimension and 1 <= matrix.shape[1] <= maximum_dimension
    ):
        raise CalculatorError("Dimension ERROR")
    if not np.all(np.isfinite(matrix)):
        raise CalculatorError("Math ERROR: matris verileri sonlu olmalıdır")
    return matrix


def _validate_matrix_operand(matrix: object, maximum_dimension: int) -> np.ndarray:
    if (
        not isinstance(matrix, np.ndarray)
        or matrix.ndim != 2
        or not (1 <= matrix.shape[0] <= maximum_dimension and 1 <= matrix.shape[1] <= maximum_dimension)
        or not np.all(np.isfinite(matrix))
    ):
        raise CalculatorError("Math ERROR: matris verileri geçersiz")
    return matrix


def matrix_operation(
    operation: str, left: object, right: object | None, maximum_dimension: int
) -> np.ndarray | float:
    """Evaluate one matrix operation without mutating calculator state."""
    left_matrix = _validate_matrix_operand(left, maximum_dimension)
    binary = operation in {"+", "-", "*"}
    if binary and right is None:
        raise CalculatorError("Dimension ERROR: ikinci matris tanımsız")
    right_matrix = cast(
        np.ndarray,
        _validate_matrix_operand(right, maximum_dimension) if right is not None else None,
    )
    if operation in {"+", "-"} and left_matrix.shape != right_matrix.shape:
        raise CalculatorError("Dimension ERROR")
    if operation == "*" and left_matrix.shape[1] != right_matrix.shape[0]:
        raise CalculatorError("Dimension ERROR")
    if operation in {"det", "inv"} and left_matrix.shape[0] != left_matrix.shape[1]:
        raise CalculatorError("Dimension ERROR: matrix must be square")
    try:
        if operation == "+":
            result: np.ndarray | float = left_matrix + right_matrix
        elif operation == "-":
            result = left_matrix - right_matrix
        elif operation == "*":
            result = left_matrix @ right_matrix
        elif operation == "det":
            result = float(np.linalg.det(left_matrix))
        elif operation == "inv":
            result = np.linalg.inv(left_matrix)
        elif operation == "trn":
            result = left_matrix.T
        elif operation == "square":
            result = left_matrix @ left_matrix
        elif operation == "cube":
            result = left_matrix @ left_matrix @ left_matrix
        elif operation == "abs":
            result = np.abs(left_matrix)
        else:
            raise CalculatorError("Argument ERROR")
    except CalculatorError:
        raise
    except np.linalg.LinAlgError as exc:
        raise CalculatorError("Math ERROR: tekil matris") from exc
    except (TypeError, ValueError) as exc:
        raise CalculatorError("Dimension ERROR") from exc
    if not np.all(np.isfinite(result)):
        raise CalculatorError("Math ERROR: matris sonucu sonlu değil")
    return result


def identity_matrix(value: object, maximum_dimension: int) -> np.ndarray:
    """Return a permitted identity matrix."""
    dimension = int(cast(Any, value))
    if not 1 <= dimension <= maximum_dimension:
        raise CalculatorError("Dimension ERROR")
    return np.asarray(np.eye(dimension))


def validate_vector_definition(vector: np.ndarray, maximum_dimension: int) -> np.ndarray:
    """Validate a newly materialized vector before it enters engine state."""
    if vector.ndim != 1 or len(vector) not in (2, maximum_dimension):
        raise CalculatorError("Dimension ERROR")
    if not np.all(np.isfinite(vector)):
        raise CalculatorError("Math ERROR: vektör verileri sonlu olmalıdır")
    return vector


def _validate_vector_operand(vector: object, maximum_dimension: int) -> np.ndarray:
    if not isinstance(vector, np.ndarray) or vector.ndim != 1 or len(vector) not in (2, maximum_dimension):
        raise CalculatorError("Math ERROR: vektör verileri geçersiz")
    if not np.all(np.isfinite(vector)):
        raise CalculatorError("Math ERROR: vektör verileri geçersiz")
    return vector


def vector_operation(
    operation: str,
    left: object,
    right: object | None,
    scalar: object,
    angle_unit: str,
    maximum_dimension: int,
) -> np.ndarray | float:
    """Evaluate one vector operation without mutating calculator state."""
    left_vector = _validate_vector_operand(left, maximum_dimension)
    binary = operation in {"+", "-", "dot", "cross", "angle"}
    if binary and right is None:
        raise CalculatorError("Dimension ERROR: ikinci vektör tanımsız")
    right_vector = cast(
        np.ndarray,
        _validate_vector_operand(right, maximum_dimension) if right is not None else None,
    )
    if binary and left_vector.shape != right_vector.shape:
        raise CalculatorError("Dimension ERROR")
    try:
        if operation == "+":
            result: np.ndarray | float = left_vector + right_vector
        elif operation == "-":
            result = left_vector - right_vector
        elif operation == "scale":
            result = finite_real_float(scalar, "Math ERROR: skaler sonlu reel olmalıdır") * left_vector
        elif operation == "dot":
            result = float(np.dot(left_vector, right_vector))
        elif operation == "cross":
            result = np.cross(left_vector, right_vector)
        elif operation == "abs":
            result = float(np.linalg.norm(left_vector))
        elif operation == "unit":
            norm = np.linalg.norm(left_vector)
            if not math.isfinite(float(norm)) or norm == 0:
                raise CalculatorError("Math ERROR")
            result = left_vector / norm
        elif operation == "angle":
            left_norm = float(np.linalg.norm(left_vector))
            right_norm = float(np.linalg.norm(right_vector))
            if not math.isfinite(left_norm) or not math.isfinite(right_norm) or left_norm == 0 or right_norm == 0:
                raise CalculatorError("Math ERROR: sıfır vektörün açısı tanımsızdır")
            cosine = max(-1, min(1, float(np.dot(left_vector, right_vector) / (left_norm * right_norm))))
            result = math.acos(cosine)
            if angle_unit == "DEG":
                result = math.degrees(result)
            elif angle_unit == "GRA":
                result = result * 200 / math.pi
        else:
            raise CalculatorError("Argument ERROR")
    except CalculatorError:
        raise
    except (TypeError, ValueError) as exc:
        raise CalculatorError("Dimension ERROR") from exc
    if not np.all(np.isfinite(result)):
        raise CalculatorError("Math ERROR: vektör sonucu sonlu değil")
    return result
