"""A small, pure-Python SciPy compatibility shim for the Android port.

Chaquopy's wheel index only publishes SciPy up to Python 3.10, but this
application uses Python 3.12 (the engine uses ``enum.StrEnum`` and PEP 695
generics).  Instead of editing the engine, this package provides the exact
subset of ``scipy`` that the Scientific Calculator engine imports:

* ``scipy.stats.norm``    -> ``pdf``, ``cdf``, ``sf``, ``ppf``
* ``scipy.stats.binom``   -> ``pmf``, ``cdf``
* ``scipy.stats.poisson`` -> ``pmf``, ``cdf``
* ``scipy.integrate``     -> ``quad``, ``dblquad``, ``tplquad``,
  ``IntegrationWarning``

The implementations are pure Python: the normal distribution uses ``math.erf``
and the standard-library ``statistics.NormalDist``, and the integrators use
``mpmath`` (which ships as a SymPy dependency), so no native code is needed.
"""

__version__ = "0.0.0+scicalc-shim"
__all__ = ["stats", "integrate"]
