"""Tests for the faithful-UI bridge operations (ui_*)."""
import json
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "app/src/main/python"))
import android_bridge as b  # noqa: E402


def call(op, **args):
    return json.loads(b.call(op, json.dumps(args)))


class UiBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        b.reset()
        result = call("ui_start", path=cls.tmp)
        assert result["ok"], result

    def setUp(self):
        # Reset to Calculate + clean LCD before every test.
        menu = call("ui_press", key="MENU")["snapshot"]["menu"]
        index = next(item["index"] for item in menu if item["label"] == "Calculate")
        call("ui_menu_select", index=index)
        call("ui_press", key="AC")

    def test_start_and_snapshot(self):
        snap = call("ui_snapshot")["snapshot"]
        self.assertEqual(snap["mode"], "Calculate")
        self.assertIn("Calculate", snap["status"])

    def test_press_and_result(self):
        for key in ("AC", "2", "PLUS", "3", "EQUALS"):
            result = call("ui_press", key=key)
            self.assertTrue(result["ok"], result.get("error"))
        snap = result["snapshot"]
        self.assertEqual(snap["expr"], "2+3")
        self.assertEqual(snap["result"], "5")

    def test_menu_and_select(self):
        result = call("ui_press", key="MENU")
        menu = result["snapshot"]["menu"]
        labels = [item["label"] for item in menu if not item["separator"]]
        self.assertIn("Matrix", labels)
        index = next(item["index"] for item in menu if item["label"] == "Matrix")
        snap = call("ui_menu_select", index=index)["snapshot"]
        self.assertEqual(snap["mode"], "Matrix")
        self.assertEqual(snap["result"], "MAT Define / Edit ◀▶ =")

    def test_angle_unit(self):
        snap = call("ui_set_angle", unit="DEG")["snapshot"]
        self.assertEqual(snap["angleUnit"], "DEG")
        call("ui_set_angle", unit="RAD")

    def test_skin_selection(self):
        for skin in ("Blue", "Pink", "White", "Graphite"):
            snap = call("ui_set_skin", skin=skin)["snapshot"]
            self.assertEqual(snap["skin"], skin)
        self.assertFalse(call("ui_set_skin", skin="Neon")["ok"])

    def test_optn_cascades(self):
        # OPTN opens nested submenus (cascades) that must be selectable by path.
        call("ui_press", key="AC")
        menu = call("ui_press", key="OPTN")["snapshot"]["menu"]
        labels = [item["label"] for item in menu if not item["separator"]]
        self.assertTrue(any("Hyperbolic Func" in (label or "") for label in labels))
        self.assertTrue(any("Angle Unit" in (label or "") for label in labels))
        sinh = next(item for item in menu if (item["label"] or "").endswith("sinh"))
        snap = call("ui_menu_select", path=sinh["path"])["snapshot"]
        self.assertIn("sinh(", snap["expr"])

    def test_power_off_latch_clears_when_the_app_reopens(self):
        # SHIFT+AC is OFF; re-opening the app (launcher or recents) must clear
        # the latch and the stuck SHIFT modifier, otherwise a still-running
        # process would immediately close again, and the first key press would
        # behave as if SHIFT were held (e.g. MENU would open SETUP).
        call("ui_press", key="SHIFT")
        snap = call("ui_press", key="AC")["snapshot"]
        self.assertTrue(snap["powerOff"])
        snap = call("ui_start", path=self.tmp)["snapshot"]
        self.assertFalse(snap["powerOff"])
        self.assertFalse(snap["shift"])
        menu = call("ui_press", key="MENU")["snapshot"]["menu"]
        self.assertIsNotNone(menu)


if __name__ == "__main__":
    unittest.main()
