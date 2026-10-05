"""Minimal, serializable entry points for isolated calculator operations."""
from __future__ import annotations

import copy
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .calculator_engine import CalculatorError, CalculatorSettings, ScientificCalculatorEngine
from .history import CalculationHistoryEntry


class CalculationOperation(StrEnum):
    """Engine operations that may cross the isolated worker boundary.

    Adding a public engine method does not make it remotely callable from the
    UI worker. It must be intentionally listed here and regression-tested.
    """

    EVALUATE = "evaluate"
    EVALUATE_WITH_VALUES = "evaluate_with_values"
    SOLVE = "solve"
    SUMMATION = "summation"
    COMPLEX_EVAL = "complex_eval"
    DEFINITE_INTEGRAL = "definite_integral"
    DEFINITE_INTEGRAL_RESULT = "definite_integral_result"
    COMPLEX_DEFINITE_INTEGRAL = "complex_definite_integral"
    SYMBOLIC_INTEGRAL = "symbolic_integral"
    DERIVATIVE = "derivative"
    SYMBOLIC_DERIVATIVE = "symbolic_derivative"
    DOUBLE_INTEGRAL = "double_integral"
    TRIPLE_INTEGRAL = "triple_integral"
    COMPLEX_DERIVATIVE_RESULT = "complex_derivative_result"
    COMPLEX_LIMIT_RESULT = "complex_limit_result"
    SOLVE_ODE = "solve_ode"


@dataclass(frozen=True, slots=True)
class EngineCalculationSnapshot:
    """The only mutable-engine values a foreground worker may receive."""

    settings: CalculatorSettings
    ans: Any
    memory: dict[str, Any]
    history: tuple[CalculationHistoryEntry, ...]

    @classmethod
    def from_engine(cls, engine: ScientificCalculatorEngine) -> EngineCalculationSnapshot:
        return cls(
            settings=copy.copy(engine.settings),
            ans=engine.ans,
            memory=dict(engine.memory),
            history=tuple(engine.history),
        )


@dataclass(frozen=True, slots=True)
class CalculationOperationRegistry:
    """Explicit worker permission registry; no dynamic engine dispatch exists."""

    handlers: Mapping[CalculationOperation, Callable[..., Any]]

    def resolve(self, operation: CalculationOperation) -> Callable[..., Any]:
        try:
            return self.handlers[operation]
        except KeyError as exc:
            raise CalculatorError("Argument ERROR: calculation operation is not allowed") from exc


CALCULATION_OPERATION_REGISTRY = CalculationOperationRegistry({
    CalculationOperation.EVALUATE: ScientificCalculatorEngine.evaluate,
    CalculationOperation.EVALUATE_WITH_VALUES: ScientificCalculatorEngine.evaluate_with_values,
    CalculationOperation.SOLVE: ScientificCalculatorEngine.solve,
    CalculationOperation.SUMMATION: ScientificCalculatorEngine.summation,
    CalculationOperation.COMPLEX_EVAL: ScientificCalculatorEngine.complex_eval,
    CalculationOperation.DEFINITE_INTEGRAL: ScientificCalculatorEngine.definite_integral,
    CalculationOperation.DEFINITE_INTEGRAL_RESULT: ScientificCalculatorEngine.definite_integral_result,
    CalculationOperation.COMPLEX_DEFINITE_INTEGRAL: ScientificCalculatorEngine.complex_definite_integral,
    CalculationOperation.SYMBOLIC_INTEGRAL: ScientificCalculatorEngine.symbolic_integral,
    CalculationOperation.DERIVATIVE: ScientificCalculatorEngine.derivative,
    CalculationOperation.SYMBOLIC_DERIVATIVE: ScientificCalculatorEngine.symbolic_derivative,
    CalculationOperation.DOUBLE_INTEGRAL: ScientificCalculatorEngine.double_integral,
    CalculationOperation.TRIPLE_INTEGRAL: ScientificCalculatorEngine.triple_integral,
    CalculationOperation.COMPLEX_DERIVATIVE_RESULT: ScientificCalculatorEngine.complex_derivative_result,
    CalculationOperation.COMPLEX_LIMIT_RESULT: ScientificCalculatorEngine.complex_limit_result,
    CalculationOperation.SOLVE_ODE: ScientificCalculatorEngine.solve_ode,
})


@dataclass(frozen=True, slots=True)
class CalculationRequest:
    """Only the calculator state needed by a foreground calculation.

    Matrix, vector, spreadsheet, and Tk state are deliberately excluded.  In
    addition to making spawning faster, that gives the calculation controller
    one clear process owner: the process created for this request.
    """

    operation: CalculationOperation
    args: tuple[Any, ...]
    kwargs: dict[str, Any]
    settings: CalculatorSettings
    ans: Any
    memory: dict[str, Any]
    history: tuple[CalculationHistoryEntry, ...]

    @property
    def snapshot(self) -> EngineCalculationSnapshot:
        """Provide a named snapshot while retaining the serialized wire layout."""
        return EngineCalculationSnapshot(self.settings, self.ans, self.memory, self.history)


@dataclass(slots=True)
class CalculationPayload:
    result: Any
    ans: Any
    history: list[CalculationHistoryEntry]
    memory: dict[str, Any]


def build_calculation_request(
    engine: ScientificCalculatorEngine,
    method: str,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> CalculationRequest:
    """Copy the small immutable-by-convention calculation boundary only."""
    return CalculationRequest(
        operation=CalculationOperation(method),
        args=args,
        kwargs=dict(kwargs),
        settings=(snapshot := EngineCalculationSnapshot.from_engine(engine)).settings,
        ans=snapshot.ans,
        memory=snapshot.memory,
        history=snapshot.history,
    )


def run_calculation(request: CalculationRequest) -> CalculationPayload:
    """Run a request in the controller-owned worker process.

    CAS calls run inline here: the controller can cancel this one process, so
    no descendant process can survive a cancelled UI operation.
    """
    snapshot = request.snapshot
    engine = ScientificCalculatorEngine(
        settings=copy.copy(snapshot.settings),
        ans=snapshot.ans,
        memory=dict(snapshot.memory),
        history=list(snapshot.history),
        cas_isolated=False,
        cas_timeout=None,
    )
    try:
        operation = CalculationOperation(request.operation)
    except ValueError as exc:
        raise CalculatorError("Argument ERROR: calculation operation is not allowed") from exc
    result = CALCULATION_OPERATION_REGISTRY.resolve(operation)(engine, *request.args, **request.kwargs)
    return CalculationPayload(result, engine.ans, list(engine.history), dict(engine.memory))
