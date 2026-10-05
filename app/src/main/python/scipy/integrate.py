"""Pure-Python integrators backing the engine's ``import scipy.integrate``.

``mpmath`` (a SymPy dependency) provides tanh-sinh/Gauss-Legendre quadrature
that handles finite, infinite, and endpoint-singular intervals, so this module
only adapts its ``(value, error)`` contract to the ``scipy.integrate`` API the
engine calls.

Two SciPy-compat details matter for this engine:

* The engine lambdifies integrands with NumPy, which does not accept ``mpf``
  arguments, so quadrature nodes are converted to ``float`` before the
  integrand is called (NumPy/SciPy evaluate in double precision anyway).
* SciPy reports a non-convergent integral through ``IntegrationWarning``; a
  naive tanh-sinh pass would silently return a finite number for a divergent
  tail, so infinite intervals are checked for ``|f|`` decaying faster than
  ``1/x`` first.
"""

from __future__ import annotations

import math

import mpmath

_DEFAULT_EPS = 1.49e-8
# Absolute convergence requires the tail to decay faster than 1/x; a decade
# ratio >= 0.1 means slower-than-1/x decay (the integral then diverges).
_MIN_DECAY_RATIO = 0.1


class IntegrationWarning(UserWarning):
    """Raised when quadrature cannot meet the requested tolerance."""


def _precision(epsabs: float, epsrel: float) -> int:
    candidates = [abs(value) for value in (epsabs, epsrel) if value]
    tolerance = min(candidates) if candidates else _DEFAULT_EPS
    digits = max(1, int(math.ceil(-math.log10(tolerance))))
    return max(20, min(60, digits + 18))


def _as_float(value) -> float:
    return float(value)


def _tail_negligible(func, samples) -> bool:
    magnitudes = []
    for point in samples:
        try:
            magnitude = abs(complex(func(point)))
        except Exception:
            # If the integrand cannot even be sampled the engine's own symbolic
            # domain analysis governs; do not block the numeric attempt here.
            return True
        if not math.isfinite(magnitude):
            return False
        magnitudes.append(magnitude)
    if magnitudes[-1] == 0.0:
        return True
    if magnitudes[-2] == 0.0:
        return False
    return magnitudes[-1] / magnitudes[-2] < _MIN_DECAY_RATIO


def _infinite_tail_negligible(func, lower: float, upper: float) -> bool:
    if math.isinf(upper):
        base = 1.0 if math.isinf(lower) else max(1.0, abs(lower))
        if not _tail_negligible(func, [base * (10.0 ** k) for k in range(7)]):
            return False
    if math.isinf(lower):
        base = 1.0 if math.isinf(upper) else max(1.0, abs(upper))
        if not _tail_negligible(func, [-base * (10.0 ** k) for k in range(7)]):
            return False
    return True


def quad(func, a, b, args=(), epsabs=_DEFAULT_EPS, epsrel=_DEFAULT_EPS, limit=50, **kwargs):
    """Return ``(value, error)`` for ``integral(func, a, b)``."""
    lower, upper = float(a), float(b)
    if lower == upper:
        return 0.0, 0.0

    def integrand(t):
        value = func(_as_float(t), *args) if args else func(_as_float(t))
        return value

    if (math.isinf(lower) or math.isinf(upper)) and not _infinite_tail_negligible(integrand, lower, upper):
        raise IntegrationWarning("integral does not converge")

    try:
        with mpmath.workdps(_precision(epsabs, epsrel)):
            result, error = mpmath.quad(integrand, [lower, upper], error=True)
    except IntegrationWarning:
        raise
    except Exception as exc:  # mpmath raises its own convergence errors
        raise IntegrationWarning(str(exc)) from exc
    value = float(mpmath.re(result))
    estimated = abs(float(mpmath.re(error)))
    threshold = max(abs(epsabs), abs(epsrel) * abs(value))
    if not math.isfinite(value) or not math.isfinite(estimated) or (estimated > threshold and estimated > 1e-12):
        raise IntegrationWarning("quadrature did not converge")
    return value, estimated


def dblquad(func, a, b, gfun, hfun, args=(), epsabs=_DEFAULT_EPS, epsrel=_DEFAULT_EPS, **kwargs):
    """Return ``(value, error)`` for ``func(y, x)`` over a region.

    Matches SciPy's argument order: ``func(y, x)`` with the inner ``y`` bounds
    given by ``gfun``/``hfun`` (callables of ``x`` or constants).
    """
    def inner(x) -> float:
        x = _as_float(x)
        low = gfun(x) if callable(gfun) else gfun
        high = hfun(x) if callable(hfun) else hfun
        if low == high:
            return 0.0
        value, _ = quad(lambda y: func(y, x, *args), low, high, epsabs=epsabs, epsrel=epsrel)
        return value

    return quad(inner, a, b, epsabs=epsabs, epsrel=epsrel)


def tplquad(func, a, b, gfun, hfun, qfun, rfun, args=(), epsabs=_DEFAULT_EPS, epsrel=_DEFAULT_EPS, **kwargs):
    """Return ``(value, error)`` for ``func(z, y, x)`` over a 3-D region.

    Matches SciPy's argument order and its nested ``x``/``y``/``z`` bounds.
    """
    def middle(x) -> float:
        x = _as_float(x)
        low_y = gfun(x) if callable(gfun) else gfun
        high_y = hfun(x) if callable(hfun) else hfun
        if low_y == high_y:
            return 0.0

        def inner(x_value: float, y) -> float:
            y = _as_float(y)
            low_z = qfun(x_value, y) if callable(qfun) else qfun
            high_z = rfun(x_value, y) if callable(rfun) else rfun
            if low_z == high_z:
                return 0.0
            value, _ = quad(lambda z: func(z, y, x_value, *args), low_z, high_z, epsabs=epsabs, epsrel=epsrel)
            return value

        value, _ = quad(lambda y: inner(x, y), low_y, high_y, epsabs=epsabs, epsrel=epsrel)
        return value

    return quad(middle, a, b, epsabs=epsabs, epsrel=epsrel)


__all__ = ["quad", "dblquad", "tplquad", "IntegrationWarning"]
