"""Host-side tests for the Kotlin<->Python bridge.

Run from the project root::

    python -m unittest discover -s tests

Needs sympy, numpy and scipy installed on the host.  These tests exercise every
operation the Kotlin UI can call, the settings policy, English error boundary,
cancellation, and the SQLite persistence round-trip.
"""
import json
import pathlib
import shutil
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "app/src/main/python"))
import android_bridge as b  # noqa: E402


def call(opname, **args):
    return json.loads(b.call(opname, json.dumps(args)))


def ok(test, opname, **args):
    result = call(opname, **args)
    test.assertTrue(result["ok"], f"{opname} failed: {result.get('error')}")
    return result


class BridgeTestCase(unittest.TestCase):
    def setUp(self):
        b.reset()


class CoreTests(BridgeTestCase):
    def test_ping_and_unknown_operation(self):
        self.assertEqual(call("ping")["text"], "pong")
        self.assertFalse(call("no_such_op")["ok"])
        self.assertFalse(json.loads(b.call(123))["ok"])

    def test_evaluate_and_history(self):
        r = ok(self, "evaluate", expr="2+2")
        self.assertEqual(r["text"], "4")
        self.assertEqual(r["history"][-1]["expression"], "2+2")
        self.assertEqual(r["history"][-1]["result"], "4")

    def test_approx(self):
        self.assertEqual(call("approx", expr="1/3")["text"], "0.333")

    def test_evaluate_with_values(self):
        r = ok(self, "evaluate_with_values", expr="x^2+y", values={"x": 3, "y": 1})
        self.assertEqual(r["text"], "10.000")

    def test_summation_and_tools(self):
        self.assertEqual(ok(self, "summation", expr="x^2", lower="1", upper="5")["text"], "55")
        self.assertEqual(ok(self, "prime_factorization", n=360)["text"], "2^3 × 3^2 × 5")
        value = call("random_int", lower=1, upper=6)["text"]
        self.assertTrue(1 <= int(value) <= 6)
        self.assertTrue(call("random_number")["ok"])

    def test_dms_pol_rec(self):
        self.assertEqual(ok(self, "decimal_to_dms", x=1.5)["text"], "1° 30' 0\"")
        self.assertEqual(ok(self, "dms_to_decimal", d=1, m=30, s=0)["text"], "1.500")
        self.assertIn("r=", ok(self, "pol", x=1, y=1)["text"])
        self.assertTrue(call("rec", r=1, theta=0)["ok"])

    def test_table(self):
        r = ok(self, "table", expr="x^2", start="1", end="3", step="1")
        self.assertEqual(r["rows"], [
            {"x": 1.0, "y": "1.000"},
            {"x": 2.0, "y": "4.000"},
            {"x": 3.0, "y": "9.000"},
        ])
        self.assertFalse(call("table", expr="1/x", start="1", end="2", step="0")["ok"])

    def test_memory(self):
        self.assertEqual(ok(self, "memory_store", name="A", value="7")["text"], "7")
        self.assertEqual(ok(self, "memory_recall", name="A")["text"], "7")
        self.assertTrue(call("memory_add")["ok"])
        self.assertTrue(call("memory_sub")["ok"])
        self.assertFalse(call("memory_recall", name="Z")["ok"])

    def test_history_recall_and_clear(self):
        ok(self, "evaluate", expr="2+2")
        self.assertEqual(ok(self, "history_recall", index=0)["text"], "2+2")
        self.assertTrue(call("history_clear")["ok"])
        self.assertEqual(call("history")["history"], [])
        self.assertFalse(call("history_recall", index=5)["ok"])


class CalculusTests(BridgeTestCase):
    def test_calculus(self):
        self.assertEqual(ok(self, "integral_definite", expr="x^2", lower="0", upper="3")["text"], "9")
        self.assertEqual(ok(self, "integral_definite", expr="1/x^2", lower="1", upper="inf")["text"], "1")
        self.assertTrue(ok(self, "integral", expr="x*exp(x)")["text"].endswith("+ C"))
        self.assertEqual(ok(self, "derivative", expr="x^3")["text"], "3*x^2")
        self.assertEqual(ok(self, "derivative_at", expr="x^3", point="2")["text"], "12.000")

    def test_multivariate(self):
        self.assertEqual(ok(self, "integral_double", expr="x*y",
                            outer_lower="0", outer_upper="1",
                            inner_lower="0", inner_upper="1")["text"], "0.250")
        self.assertEqual(ok(self, "integral_triple", expr="x+y+z",
                            outer_lower="0", outer_upper="1",
                            middle_lower="0", middle_upper="1",
                            inner_lower="0", inner_upper="1")["text"], "1.500")

    def test_solve_and_ode(self):
        r = ok(self, "solve", equation="x^2-4=0")
        self.assertEqual(r["root"], 2.0)
        self.assertEqual(r["text"], "x = 2")
        self.assertEqual(ok(self, "ode", equation="y'=y", conditions="x0=0, y0=1")["text"], "y(x) = exp(x)")

    def test_typed_integral_status(self):
        r = ok(self, "integral_definite", expr="1/x", lower="-1", upper="1")
        self.assertNotEqual(r["status"], "integral_exists")


class ComplexTests(BridgeTestCase):
    def test_complex_eval_and_polar(self):
        self.assertTrue(call("complex_eval", expr="(1+i)^2")["ok"])
        polar = ok(self, "to_polar", z="1+i")
        self.assertAlmostEqual(polar["r"], 2 ** 0.5, places=10)
        self.assertAlmostEqual(polar["theta"], 3.141592653589793 / 4, places=10)
        self.assertTrue(call("from_polar", r="1", theta="0")["ok"])
        self.assertTrue(call("complex_argument", z="i")["ok"])

    def test_complex_derivative_and_limit(self):
        self.assertEqual(ok(self, "complex_derivative", expr="z^2")["text"], "2*z")
        self.assertTrue(call("complex_limit", expr="z", point="0")["ok"])
        self.assertTrue(call("complex_integral", expr="z", lower="0", upper="1")["ok"])


class BaseNTests(BridgeTestCase):
    def test_base_eval_and_format(self):
        self.assertEqual(ok(self, "base_eval", expr="1010+1", base=2)["text"], "1011")
        self.assertEqual(ok(self, "base_format", value=255, base=16)["text"], "FF")
        self.assertEqual(ok(self, "base_op", a=12, b=10, op="and", base=16)["text"], "8")
        self.assertEqual(ok(self, "base_parse", token="FF", base=16)["value"], 255)
        self.assertFalse(call("base_eval", expr="2", base=7)["ok"])


class MatrixTests(BridgeTestCase):
    def test_matrix_workflow(self):
        self.assertTrue(call("matrix_define", name="MatA", data=[[1, 2], [3, 4]])["ok"])
        self.assertTrue(call("matrix_define", name="MatB", data=[[5, 6], [7, 8]])["ok"])
        self.assertAlmostEqual(ok(self, "matrix_op", op="det", a="MatA")["scalar"], -2.0, places=10)
        self.assertTrue(call("matrix_op", op="inv", a="MatA")["ok"])
        self.assertTrue(call("matrix_op", op="+", a="MatA", b="MatB")["ok"])
        self.assertTrue(call("matrix_op", op="*", a="MatA", b="MatB")["ok"])
        matrix = ok(self, "matrix_get")["matrices"]
        self.assertEqual(matrix["MatA"], [[1.0, 2.0], [3.0, 4.0]])
        self.assertEqual(ok(self, "matrix_identity", n=3)["matrix"], [
            [1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0],
        ])
        self.assertTrue(call("matrix_clear", name="MatA")["ok"])
        self.assertIsNone(call("matrix_get")["matrices"]["MatA"])

    def test_matrix_dimension_error(self):
        self.assertFalse(call("matrix_define", name="MatA", data=[[1, 2, 3, 4, 5]])["ok"])
        self.assertFalse(call("matrix_op", op="det", a=[[1, 2], [3, 4], [5, 6]])["ok"])


class VectorTests(BridgeTestCase):
    def test_vector_workflow(self):
        self.assertTrue(call("vector_define", name="VctA", data=[1, 2, 3])["ok"])
        self.assertEqual(ok(self, "vector_op", op="dot", a="VctA", b="VctA")["scalar"], 14.0)
        self.assertEqual(ok(self, "vector_op", op="abs", a="VctA")["scalar"], 14 ** 0.5)
        self.assertTrue(call("vector_op", op="cross", a="VctA", b="VctA")["ok"])
        self.assertTrue(call("vector_op", op="scale", a="VctA", scalar=2)["ok"])
        self.assertEqual(ok(self, "vector_get")["vectors"]["VctA"], [1.0, 2.0, 3.0])
        self.assertTrue(call("vector_clear", name="VctA")["ok"])


class StatisticsTests(BridgeTestCase):
    def test_one_var(self):
        r = ok(self, "one_var_stats", x=[1, 2, 3, 4])
        self.assertEqual(r["stats"]["n"], 4.0)
        self.assertEqual(r["stats"]["x̄"], 2.5)
        self.assertIn("\n", r["text"])

    def test_regression(self):
        r = ok(self, "regression", x=[1, 2, 3], y=[3, 5, 7], kind="linear")
        self.assertAlmostEqual(r["regression"]["b"], 2.0, places=10)
        self.assertFalse(call("regression", x=[1, 2], y=[1, 2], kind="bogus")["ok"])

    def test_normal_and_distribution(self):
        self.assertEqual(float(ok(self, "normal_p", t=0)["text"]), 0.5)
        self.assertTrue(call("normal_q", t=0)["ok"])
        self.assertTrue(call("normal_r", t=0)["ok"])
        self.assertTrue(call("distribution", kind="Normal PD", x=0, mu=0, sigma=1)["ok"])
        self.assertTrue(call("distribution", kind="Binomial PD", x=2, N=5, p=0.5)["ok"])
        self.assertFalse(call("distribution", kind="Bogus")["ok"])


class EquationTests(BridgeTestCase):
    def test_polynomial_roots(self):
        r = ok(self, "polynomial_roots", coeffs=[1, 0, -4])
        self.assertEqual(sorted(r["roots"]), [-2.0, 2.0])

    def test_simultaneous(self):
        r = ok(self, "simultaneous", a=[[2, 1], [1, -1]], b=[5, 1])
        self.assertEqual(r["solution"], [2.0, 1.0])
        self.assertFalse(call("simultaneous", a=[[1, 2], [2, 4]], b=[1, 2])["ok"])

    def test_inequality_and_ratio(self):
        self.assertIn("x", ok(self, "inequality", coeffs=[1, -1], relation=">")["text"])
        self.assertEqual(ok(self, "ratio", kind="A:B=X:D", A="1", B="2", D="4")["text"], "2.000")
        self.assertFalse(call("ratio", kind="bogus")["ok"])


class ConversionTests(BridgeTestCase):
    def test_convert(self):
        self.assertEqual(ok(self, "convert", name="in→cm", value=1)["text"], "2.540")
        names = ok(self, "conversions")["conversions"]
        self.assertIn("in→cm", names)
        self.assertFalse(call("convert", name="nope", value=1)["ok"])


class SpreadsheetTests(BridgeTestCase):
    def test_sheet(self):
        ok(self, "sheet_set", address="A1", text="=2+3")
        r = ok(self, "sheet_set", address="A2", text="=A1*2")
        self.assertEqual(r["values"]["A2"], "10.000")
        self.assertTrue(r["free_space"] < 1700)
        r = ok(self, "sheet_snapshot")
        self.assertEqual(r["cells"]["A1"], "=2+3")
        self.assertTrue(call("sheet_delete", address="A1")["ok"])
        self.assertTrue(call("sheet_clear")["ok"])
        self.assertEqual(call("sheet_snapshot")["cells"], {})

    def test_circular_reference(self):
        call("sheet_set", address="A1", text="=A2")
        r = call("sheet_set", address="A2", text="=A1")
        self.assertFalse(r["ok"])


class SettingsTests(BridgeTestCase):
    def test_settings_validation(self):
        r = ok(self, "set_settings", angle_unit="DEG")
        self.assertEqual(r["settings"]["angle_unit"], "DEG")
        self.assertEqual(ok(self, "evaluate", expr="sin(30)")["text"], "1/2")
        self.assertFalse(call("set_settings", bogus=1)["ok"])
        self.assertFalse(call("set_settings", angle_unit="NOPE")["ok"])
        self.assertFalse(call("set_settings", number_digits=42)["ok"])
        self.assertFalse(call("set_settings", engineer_symbol="yes")["ok"])
        get = ok(self, "get_settings")["settings"]
        self.assertEqual(get["angle_unit"], "DEG")

    def test_reset_all(self):
        ok(self, "set_settings", angle_unit="DEG")
        ok(self, "evaluate", expr="2+2")
        ok(self, "reset_all")
        self.assertEqual(call("get_settings")["settings"]["angle_unit"], "RAD")
        self.assertEqual(call("history")["history"], [])


class PersistenceTests(BridgeTestCase):
    def setUp(self):
        super().setUp()
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)

    def test_round_trip(self):
        self.assertEqual(ok(self, "configure", path=self.dir)["text"], self.dir)
        ok(self, "set_settings", angle_unit="DEG", number_digits=5)
        ok(self, "evaluate", expr="2+2")
        ok(self, "set_settings", engineer_symbol=True)
        # Fresh engine, same database directory.
        b.reset()
        self.assertTrue(call("configure", path=self.dir)["ok"])
        settings = call("get_settings")["settings"]
        self.assertEqual(settings["angle_unit"], "DEG")
        self.assertEqual(settings["number_digits"], 5)
        self.assertTrue(settings["engineer_symbol"])
        history = call("history")["history"]
        self.assertEqual(history[-1]["expression"], "2+2")

    def test_invalid_saved_values_are_ignored(self):
        from scientific_calculator.settings_store import SettingsStore

        store = SettingsStore(pathlib.Path(self.dir) / "settings.db")
        store.save({"angle_unit": "NOPE", "number_digits": 99, "engineer_symbol": True})
        b.reset()
        ok(self, "configure", path=self.dir)
        settings = call("get_settings")["settings"]
        self.assertEqual(settings["angle_unit"], "RAD")
        self.assertEqual(settings["number_digits"], 3)


class ErrorBoundaryTests(BridgeTestCase):
    def test_errors_are_english_and_never_raise(self):
        r = call("evaluate", expr="1/0")
        self.assertFalse(r["ok"])
        self.assertIn("Math ERROR", r["error"])
        self.assertTrue(r["error"].isascii())
        self.assertFalse(call("evaluate", expr="__import__('os')")["ok"])
        self.assertFalse(json.loads(b.call("evaluate", "[1,2]"))["ok"])
        self.assertFalse(call("evaluate", expr="x.real")["ok"])

    def test_unknown_argument_shape(self):
        self.assertFalse(json.loads(b.call("evaluate", json.dumps(["not", "an", "object"])))["ok"])


class CancellationTests(BridgeTestCase):
    def test_cancel_interrupts_and_engine_survives(self):
        def spin(e, a):
            while True:
                sum(range(1000))

        b._OPS["spin"] = spin
        self.addCleanup(b._OPS.pop, "spin", None)
        out = {}
        thread = threading.Thread(target=lambda: out.update(r=json.loads(b.call("spin"))))
        thread.start()
        time.sleep(0.3)
        self.assertTrue(b.cancel())
        thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(out["r"]["error"], "Calculation cancelled")
        self.assertFalse(b.cancel())
        self.assertEqual(call("evaluate", expr="3*3")["text"], "9")


if __name__ == "__main__":
    unittest.main()
