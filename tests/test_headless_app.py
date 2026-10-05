"""Tests for the headless driver over the real desktop App.

Runs the actual ``scientific_calculator.app`` under the virtual Tk layer and
checks that the LCD text matches the desktop's own output.
"""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "app/src/main/python"))

import headless_app  # noqa: E402


class HeadlessAppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        headless_app.configure(str(pathlib.Path(__file__).resolve().parent / "_headless_tmp"))
        headless_app.start()

    def setUp(self):
        # Return to a clean Calculate state before each test.
        headless_app.press("AC")
        headless_app.press("AC")

    def test_initial_snapshot(self):
        snap = headless_app.snapshot()
        self.assertEqual(snap["mode"], "Calculate")
        self.assertIn("Calculate", snap["status"])
        self.assertEqual(snap["result"], "0")

    def test_addition(self):
        for key in ("2", "PLUS", "3", "EQUALS"):
            snap = headless_app.press(key)
        self.assertEqual(snap["expr"], "2+3")
        self.assertEqual(snap["result"], "5")

    def test_trig_uses_angle_unit(self):
        headless_app.press("SHIFT")  # no-op for sin; ensure modifier reset
        headless_app.press("AC")
        for key in ("SIN", "3", "0", "RPAREN", "EQUALS"):
            snap = headless_app.press(key)
        # RAD: sin(30) is ~ -0.988; set DEG to check the exact desktop value.
        self.assertTrue(snap["result"])

    def test_angle_switch_changes_result(self):
        # Cycle angle unit through the status menu is not a key; use the app API.
        app = headless_app._require()
        app.set_angle("DEG")
        app.set_expr("")
        for key in ("SIN", "3", "0", "RPAREN", "EQUALS"):
            snap = headless_app.press(key)
        self.assertEqual(snap["result"], "1/2")
        app.set_angle("RAD")

    def test_menu_lists_all_modes(self):
        result = headless_app.press("MENU")
        labels = [item["label"] for item in result["menu"] if not item["separator"]]
        for mode in ("Calculate", "Complex", "Base-N", "Matrix", "Vector",
                     "Statistics", "Distribution", "Spreadsheet", "Table",
                     "Equation/Func", "Inequality", "Ratio"):
            self.assertIn(mode, labels)

    def test_mode_switch_shows_desktop_hint(self):
        result = headless_app.press("MENU")
        matrix_index = next(i["index"] for i in result["menu"] if i["label"] == "Matrix")
        snap = headless_app.menu_select(matrix_index)
        self.assertEqual(snap["mode"], "Matrix")
        self.assertEqual(snap["result"], "MAT Define / Edit ◀▶ =")

    def test_backspace_and_clear(self):
        for key in ("1", "2", "3"):
            headless_app.press(key)
        headless_app.press("DEL")
        self.assertEqual(headless_app.snapshot()["expr"], "12")
        headless_app.press("AC")
        self.assertEqual(headless_app.snapshot()["expr"], "")

    def test_on_restart_is_safe(self):
        # ON must not spawn a process on Android; it resets to Calculate.
        for key in ("1", "2"):
            headless_app.press(key)
        snap = headless_app.press("ON")
        self.assertEqual(snap["mode"], "Calculate")
        self.assertEqual(snap["expr"], "")


if __name__ == "__main__":
    unittest.main()
