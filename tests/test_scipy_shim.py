"""Tests for the pure-Python SciPy compatibility shim.

These verify both the shim in isolation and that the real engine uses it for
numeric-only integrals, distributions, and normal-tail helpers.
"""
import json
import math
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "app/src/main/python"))

import scipy.integrate  # noqa: E402
from scipy import stats  # noqa: E402

import android_bridge as b  # noqa: E402


def call(op, **args):
    return json.loads(b.call(op, json.dumps(args)))


class NormTests(unittest.TestCase):
    def test_norm(self):
        self.assertAlmostEqual(stats.norm.cdf(0.0), 0.5, places=12)
        self.assertAlmostEqual(stats.norm.cdf(1.96), 0.97500210485, places=8)
        self.assertAlmostEqual(stats.norm.sf(1.96), 0.02499789515, places=8)
        self.assertAlmostEqual(stats.norm.pdf(0.0), 1 / math.sqrt(2 * math.pi), places=12)
        self.assertAlmostEqual(stats.norm.pdf(0.0, loc=1.0, scale=2.0), stats.norm.pdf(-0.5) / 2, places=12)
        self.assertAlmostEqual(stats.norm.ppf(0.975), 1.95996398454, places=8)
        for x in (-2.5, -0.3, 0.0, 0.7, 3.1):
            self.assertAlmostEqual(stats.norm.ppf(stats.norm.cdf(x)), x, places=7)


class DiscreteTests(unittest.TestCase):
    def test_binomial(self):
        self.assertAlmostEqual(stats.binom.pmf(2, 5, 0.5), 0.3125, places=12)
        self.assertAlmostEqual(stats.binom.cdf(2, 5, 0.5), 0.5, places=12)
        self.assertEqual(stats.binom.pmf(-1, 5, 0.5), 0.0)
        self.assertEqual(stats.binom.pmf(6, 5, 0.5), 0.0)

    def test_poisson(self):
        self.assertAlmostEqual(stats.poisson.pmf(2, 2.0), 2 * math.exp(-2), places=12)
        self.assertAlmostEqual(stats.poisson.cdf(2, 2.0), math.exp(-2) * (1 + 2 + 2), places=12)
        self.assertEqual(stats.poisson.pmf(0, 0.0), 1.0)


class IntegrateTests(unittest.TestCase):
    def test_quad(self):
        value, error = scipy.integrate.quad(lambda x: x * x, 0, 1)
        self.assertAlmostEqual(value, 1 / 3, places=10)
        self.assertTrue(math.isfinite(error))
        value, _ = scipy.integrate.quad(lambda x: 1 / math.sqrt(x), 0, 1)
        self.assertAlmostEqual(value, 2.0, places=8)
        value, _ = scipy.integrate.quad(math.sin, 0, math.pi)
        self.assertAlmostEqual(value, 2.0, places=10)
        value, _ = scipy.integrate.quad(lambda x: 1 / (x * x), 1, math.inf)
        self.assertAlmostEqual(value, 1.0, places=8)

    def test_divergent_quad_raises(self):
        with self.assertRaises(scipy.integrate.IntegrationWarning):
            scipy.integrate.quad(lambda x: 1 / x, 0, 1)

    def test_dblquad(self):
        value, _ = scipy.integrate.dblquad(lambda y, x: x * y, 0, 1, lambda x: 0, lambda x: 1)
        self.assertAlmostEqual(value, 0.25, places=8)
        value, _ = scipy.integrate.dblquad(lambda y, x: 1.0, 0, 1, lambda x: 0, lambda x: x)
        self.assertAlmostEqual(value, 0.5, places=8)

    def test_tplquad(self):
        value, _ = scipy.integrate.tplquad(lambda z, y, x: x * y * z, 0, 1, lambda x: 0, lambda x: 1, lambda x, y: 0, lambda x, y: 1)
        self.assertAlmostEqual(value, 0.125, places=7)


class EngineUsesShimTests(unittest.TestCase):
    def setUp(self):
        b.reset()

    def test_numeric_definite_integral(self):
        # x^x has no elementary antiderivative, forcing numeric quadrature.
        result = call("integral_definite", expr="x^x", lower="0", upper="1")
        self.assertTrue(result["ok"], result.get("error"))
        self.assertAlmostEqual(float(result["text"]), 0.7834305107, places=3)

    def test_numeric_double_integral(self):
        # A non-separable region and integrand that the exact nested path cannot close.
        result = call("integral_double", expr="exp(x*y)",
                      outer_lower="0", outer_upper="1", inner_lower="0", inner_upper="1")
        self.assertTrue(result["ok"], result.get("error"))
        self.assertAlmostEqual(float(result["text"]), 1.3179, places=3)

    def test_distributions_through_engine(self):
        normal = call("distribution", kind="Normal CD", lower=-1, upper=1, mu=0, sigma=1)
        self.assertTrue(normal["ok"])
        self.assertAlmostEqual(float(normal["text"]), 0.683, places=3)
        binomial = call("distribution", kind="Binomial PD", x=2, N=5, p=0.5)
        self.assertAlmostEqual(float(binomial["text"]), 0.313, delta=0.002)
        poisson = call("distribution", kind="Poisson PD", x=2, lam=2)
        self.assertAlmostEqual(float(poisson["text"]), 0.271, places=3)

    def test_normal_tails_through_engine(self):
        self.assertAlmostEqual(float(call("normal_p", t=0)["text"]), 0.5, places=3)
        self.assertAlmostEqual(float(call("normal_r", t=1.96)["text"]), 0.025, places=3)


if __name__ == "__main__":
    unittest.main()
