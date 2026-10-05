"""Pure-Python implementations of the ``scipy.stats`` distributions the engine uses.

Only the methods referenced by ``engine/distributions.py`` and
``engine/regression.py`` are provided.  Results match `scipy.stats` to double
precision for the calculator's input range.
"""

from __future__ import annotations

import math
from statistics import NormalDist

_TWO = 2.0
_SQRT2 = math.sqrt(_TWO)
_SQRT_2PI = math.sqrt(_TWO * math.pi)


class _Norm:
    @staticmethod
    def pdf(x: float, loc: float = 0.0, scale: float = 1.0) -> float:
        z = (x - loc) / scale
        if math.isinf(z):
            return 0.0
        return math.exp(-0.5 * z * z) / (scale * _SQRT_2PI)

    @staticmethod
    def cdf(x: float, loc: float = 0.0, scale: float = 1.0) -> float:
        return 0.5 * math.erfc(-(x - loc) / (scale * _SQRT2))

    @staticmethod
    def sf(x: float, loc: float = 0.0, scale: float = 1.0) -> float:
        return 0.5 * math.erfc((x - loc) / (scale * _SQRT2))

    @staticmethod
    def ppf(q: float, loc: float = 0.0, scale: float = 1.0) -> float:
        return NormalDist(mu=loc, sigma=scale).inv_cdf(q)


class _Binom:
    @staticmethod
    def pmf(k: float, n: float, p: float) -> float:
        k = int(k)
        n = int(n)
        if k < 0 or k > n:
            return 0.0
        if p <= 0.0:
            return 1.0 if k == 0 else 0.0
        if p >= 1.0:
            return 1.0 if k == n else 0.0
        log_probability = (
            math.lgamma(n + 1)
            - math.lgamma(k + 1)
            - math.lgamma(n - k + 1)
            + k * math.log(p)
            + (n - k) * math.log1p(-p)
        )
        return math.exp(log_probability)

    @staticmethod
    def cdf(k: float, n: float, p: float) -> float:
        k = int(k)
        n = int(n)
        if k < 0:
            return 0.0
        if k >= n:
            return 1.0
        return math.fsum(_Binom.pmf(i, n, p) for i in range(k + 1))


class _Poisson:
    @staticmethod
    def pmf(k: float, mu: float) -> float:
        k = int(k)
        if k < 0:
            return 0.0
        if mu == 0.0:
            return 1.0 if k == 0 else 0.0
        return math.exp(-mu + k * math.log(mu) - math.lgamma(k + 1))

    @staticmethod
    def cdf(k: float, mu: float) -> float:
        k = int(k)
        if k < 0:
            return 0.0
        return math.fsum(_Poisson.pmf(i, mu) for i in range(k + 1))


norm = _Norm()
binom = _Binom()
poisson = _Poisson()

__all__ = ["norm", "binom", "poisson"]
