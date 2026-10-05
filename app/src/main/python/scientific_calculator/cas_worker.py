"""Bounded SymPy operations used by direct engine callers.

The Tk application has a single, controller-owned calculation process. Its CAS
operations run inline in that process, avoiding an orphanable nested process.
Direct engine callers can still opt into a separate bounded process.
"""

from __future__ import annotations

import multiprocessing as mp
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from multiprocessing.connection import Connection
from typing import Any

import sympy as sp
from sympy.calculus.util import continuous_domain

from .calculation_errors import CalculationTimeout, WorkerCrashed


class CASError(RuntimeError):
    """Base class for isolated CAS execution failures."""


class CASWorkerError(CASError):
    """SymPy or the worker process did not complete normally."""

    def __init__(self, error_type: str, message: str = ""):
        super().__init__(f"{error_type}: {message}" if message else error_type)
        self.error_type = error_type
        self.worker_message = message


class CASTimeout(CalculationTimeout, CASError):
    """A direct, isolated CAS operation did not finish before its deadline."""


class CASOperation(StrEnum):
    """The bounded SymPy actions permitted through the CAS boundary."""

    SIMPLIFY = "simplify"
    DIFFERENTIATE = "differentiate"
    DIFFERENTIATE_AT_POINT = "differentiate_at_point"
    LIMIT = "limit"
    SINGULARITIES = "singularities"
    CONTINUOUS_DOMAIN = "continuous_domain"
    NSOLVE = "nsolve"
    SOLVE = "solve"
    DSOLVE = "dsolve"
    DEFINITE_INTEGRAL = "definite_integral"
    INDEFINITE_INTEGRAL = "indefinite_integral"
    SUMMATION = "summation"


class CASExecutionMode(StrEnum):
    """Whether the CAS call runs in this process or a bounded child process."""

    INLINE = "inline"
    ISOLATED = "isolated"


@dataclass(frozen=True, slots=True)
class CASExecutionPolicy:
    """Explicit timeout ownership for direct and controller-owned CAS calls."""

    mode: CASExecutionMode
    timeout: float | None = None


CASHandler = Callable[[dict[str, Any]], Any]


def _dsolve(payload: dict[str, Any]) -> Any:
    if payload.get("ics"):
        return sp.dsolve(payload["equation"], payload["function"], ics=payload["ics"])
    return sp.dsolve(payload["equation"], payload["function"])


CAS_OPERATION_REGISTRY: Mapping[CASOperation, CASHandler] = {
    CASOperation.SIMPLIFY: lambda payload: sp.simplify(payload["expression"]),
    CASOperation.DIFFERENTIATE: lambda payload: sp.diff(payload["expression"], payload["symbol"]),
    CASOperation.DIFFERENTIATE_AT_POINT: lambda payload: sp.diff(payload["expression"], payload["symbol"]).subs(
        payload["symbol"], payload["point"]
    ),
    CASOperation.LIMIT: lambda payload: sp.limit(
        payload["expression"], payload["symbol"], payload["point"], dir=payload.get("dir", "+")
    ),
    CASOperation.SINGULARITIES: lambda payload: sp.singularities(payload["expression"], payload["symbol"]),
    CASOperation.CONTINUOUS_DOMAIN: lambda payload: continuous_domain(
        payload["expression"], payload["symbol"], payload["domain"]
    ),
    CASOperation.NSOLVE: lambda payload: sp.nsolve(
        payload["expression"],
        payload["symbol"],
        payload["guess"],
        tol=payload.get("tol", 1e-14),
        maxsteps=payload.get("maxsteps", 100),
        prec=payload.get("prec", 40),
    ),
    CASOperation.SOLVE: lambda payload: sp.solve(sp.Eq(payload["expression"], 0), payload["symbol"]),
    CASOperation.DSOLVE: _dsolve,
    CASOperation.DEFINITE_INTEGRAL: lambda payload: sp.integrate(
        payload["expression"], (payload["symbol"], payload["lower"], payload["upper"])
    ),
    CASOperation.INDEFINITE_INTEGRAL: lambda payload: sp.integrate(payload["expression"], payload["symbol"]),
    CASOperation.SUMMATION: lambda payload: sp.summation(
        payload["expression"], (payload["symbol"], payload["lower"], payload["upper"])
    ),
}


def _dispatch(operation: CASOperation | str, payload: dict[str, Any]) -> Any:
    """Execute one allowlisted CAS operation without dynamic attribute access."""
    try:
        parsed_operation = CASOperation(operation)
    except ValueError as exc:
        raise ValueError(f"Unknown CAS operation: {operation}") from exc
    return CAS_OPERATION_REGISTRY[parsed_operation](payload)


def _worker_main(connection: Connection, operation: str, payload: dict[str, Any]) -> None:
    try:
        response = ("ok", _dispatch(operation, payload))
    except BaseException as exc:
        response = ("error", type(exc).__name__, str(exc)[:500])
    try:
        connection.send(response)
    except (BrokenPipeError, EOFError, OSError):
        # A direct caller may have timed out and closed its receive end.  The
        # response is no longer observable, so normal cleanup must not emit a
        # child-process traceback.
        pass
    finally:
        connection.close()


def _stop(process: Any) -> None:
    """Stop a direct CAS worker; this is never called by the Tk UI thread."""
    if process.is_alive():
        process.terminate()
        process.join(0.5)
    if process.is_alive() and hasattr(process, "kill"):
        process.kill()
        process.join(0.5)
    else:
        process.join(0.1)


def _run_isolated(operation: str, payload: dict[str, Any], timeout: float | None) -> Any:
    context = mp.get_context("spawn")
    parent, child = context.Pipe(duplex=False)
    process = context.Process(target=_worker_main, args=(child, operation, payload), daemon=True)
    try:
        process.start()
    except BaseException:
        parent.close()
        child.close()
        raise
    child.close()
    try:
        if not parent.poll(timeout):
            raise CASTimeout(f"CAS operation timed out: {operation}")
        response = parent.recv()
        process.join(1.0)
        if response and response[0] == "ok":
            return response[1]
        if response and response[0] == "error" and len(response) == 3:
            raise CASWorkerError(response[1], response[2])
        raise CASWorkerError("WorkerProtocolError", "invalid worker response")
    except EOFError as exc:
        raise WorkerCrashed(f"CAS worker exited with code {process.exitcode}") from exc
    finally:
        parent.close()
        if process.is_alive():
            _stop(process)


def run_cas(
    operation: str,
    payload: dict[str, Any],
    *,
    timeout: float | None = None,
    isolated: bool = False,
    policy: CASExecutionPolicy | None = None,
) -> Any:
    """Run a CAS operation with an optional hard timeout.

    ``isolated=False`` is for the existing controller-owned worker. It is
    intentionally process-free so cancelling the controller cannot leave a
    grandchild behind. Direct callers use ``isolated=True`` and receive a
    :class:`CASTimeout` when the deadline is reached.
    """
    active_policy = policy or CASExecutionPolicy(
        CASExecutionMode.ISOLATED if isolated else CASExecutionMode.INLINE, timeout
    )
    if active_policy.mode == CASExecutionMode.ISOLATED:
        return _run_isolated(operation, payload, active_policy.timeout)
    started = time.monotonic()
    result = _dispatch(operation, payload)
    # Inline execution cannot pre-empt SymPy safely. The controller provides
    # its hard deadline at the process boundary; this check preserves a useful
    # timeout signal for callers whose work completed just after a deadline.
    if active_policy.timeout is not None and time.monotonic() - started > active_policy.timeout:
        raise CASTimeout(f"CAS operation timed out: {operation}")
    return result
