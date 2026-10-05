"""Tests for interactive modal dialogs and Toplevel dialog capture."""
import json
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "app/src/main/python"))
import android_bridge as b  # noqa: E402


def call(op, **args):
    return json.loads(b.call(op, json.dumps(args)))


def find(nodes, predicate):
    for node in nodes:
        if predicate(node):
            return node
        found = find(node.get("children", []), predicate)
        if found is not None:
            return found
    return None


class DialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        b.reset()
        assert call("ui_start", path=cls.tmp)["ok"]

    def setUp(self):
        call("ui_dialog_close_all")
        menu = call("ui_press", key="MENU")["snapshot"]["menu"]
        index = next(i["index"] for i in menu if i["label"] == "Calculate")
        call("ui_menu_select", index=index)
        call("ui_press", key="AC")

    def test_sto_opens_string_dialog_and_recalls(self):
        # 7 -> STO -> answer "A" stores Ans into memory A.
        call("ui_press", key="7")
        call("ui_press", key="EQUALS")
        snap = call("ui_press", key="STO")["snapshot"]
        self.assertIsNotNone(snap["dialog"])
        self.assertEqual(snap["dialog"]["kind"], "string")
        snap = call("ui_dialog_answer", value="A")["snapshot"]
        self.assertIsNone(snap["dialog"])
        self.assertEqual(snap["result"], "A=7")

    def test_calc_prompts_for_variable_values(self):
        # CALC on "x+1" asks for x.
        call("ui_press", key="AC")
        call("ui_press", key="X")
        call("ui_press", key="PLUS")
        call("ui_press", key="1")
        snap = call("ui_press", key="CALC")["snapshot"]
        self.assertIsNotNone(snap["dialog"])
        self.assertEqual(snap["dialog"]["kind"], "float")
        snap = call("ui_dialog_answer", value=41)["snapshot"]
        self.assertIsNone(snap["dialog"])
        self.assertTrue(snap["result"].startswith("42"))

    def test_constants_dialog_lists_and_inserts(self):
        # SHIFT+7 opens CONST (a Toplevel with a Listbox and Insert button).
        call("ui_press", key="SHIFT")
        snap = call("ui_press", key="7")["snapshot"]
        self.assertTrue(snap["dialogs"], "CONST dialog should be open")
        dialog = snap["dialogs"][-1]
        listbox = find([dialog["root"]], lambda n: n["kind"] == "Listbox")
        insert = find([dialog["root"]], lambda n: n["kind"] == "Button" and n["text"] == "Insert")
        self.assertIsNotNone(listbox)
        self.assertIsNotNone(insert)
        self.assertTrue(len(listbox["items"]) > 10)
        call("ui_dialog_invoke", dialog=dialog["id"], widget=listbox["id"], action="select", value=0)
        snap = call("ui_dialog_invoke", dialog=dialog["id"], widget=insert["id"], action="command")["snapshot"]
        self.assertFalse(snap["dialogs"], "CONST closes after Insert")

    def test_setup_dialog_edits_angle(self):
        # SHIFT+MENU opens SETUP; change the Angle Unit combo then Save.
        call("ui_press", key="SHIFT")
        snap = call("ui_press", key="MENU")["snapshot"]
        self.assertTrue(snap["dialogs"], "SETUP dialog should be open")
        dialog = snap["dialogs"][-1]
        combos = []

        def collect(nodes):
            for node in nodes:
                if node["kind"] == "Combobox":
                    combos.append(node)
                collect(node.get("children", []))

        collect([dialog["root"]])
        angle = next(c for c in combos if "DEG" in c["values"] and "RAD" in c["values"])
        save = find([dialog["root"]], lambda n: n["kind"] == "Button" and n["text"] == "Save")
        call("ui_dialog_invoke", dialog=dialog["id"], widget=angle["id"], action="set", value="DEG")
        snap = call("ui_dialog_invoke", dialog=dialog["id"], widget=save["id"], action="command")["snapshot"]
        self.assertEqual(snap["angleUnit"], "DEG")
        self.assertFalse(snap["dialogs"], "SETUP closes after Save")
        call("ui_set_angle", unit="RAD")

    def test_info_message_recorded(self):
        headless = __import__("headless_app")
        headless._require().help_key()
        snap = call("ui_snapshot")["snapshot"]
        self.assertTrue(snap["info"])
        self.assertEqual(snap["info"][-1]["title"], "Quick help")
        call("ui_dialog_dismiss")
        snap = call("ui_snapshot")["snapshot"]
        self.assertFalse(snap["info"])

    def test_integral_opens_lcd_chooser(self):
        call("ui_press", key="AC")
        snap = call("ui_press", key="INTEGRAL")["snapshot"]
        self.assertNotEqual(snap["result"], "0")
        # The chooser is an LCD flow, surfaced through the result/hint text.
        self.assertTrue(snap["result"])

    def test_integral_template_canvas_items(self):
        call("ui_press", key="AC")
        call("ui_press", key="INTEGRAL")
        snap = call("ui_press", key="EQUALS")["snapshot"]
        template = snap["template"]
        self.assertIsNotNone(template)
        self.assertEqual(template["canvas"]["width"], 381)
        self.assertEqual(template["canvas"]["height"], 92)
        kinds = [item["kind"] for item in template["items"]]
        self.assertIn("text", kinds)
        self.assertIn("rectangle", kinds)
        self.assertIn("line", kinds)  # the editing caret
        integral = next(item for item in template["items"] if item.get("text") == "∫")
        self.assertGreater(integral["size"], 0)
        call("ui_press", key="AC")

    def test_template_long_body_shows_ellipsis(self):
        call("ui_press", key="AC")
        call("ui_press", key="INTEGRAL")
        call("ui_press", key="EQUALS")
        for _ in range(20):
            call("ui_press", key="9")
        snap = call("ui_snapshot")["snapshot"]
        texts = [item.get("text", "") for item in snap["template"]["items"] if item["kind"] == "text"]
        # The desktop slices a too-long field and marks the hidden side.
        self.assertTrue(any("…" in text for text in texts), texts)
        call("ui_press", key="AC")

    def test_integral_bounds_slice_with_ellipsis(self):
        call("ui_press", key="AC")
        call("ui_press", key="INTEGRAL")
        call("ui_press", key="EQUALS")
        # Move to the upper bound (body -> var -> upper) and type a long value.
        call("ui_press", key="UP")
        call("ui_press", key="UP")
        for _ in range(14):
            call("ui_press", key="9")
        snap = call("ui_snapshot")["snapshot"]
        texts = [item.get("text", "") for item in snap["template"]["items"] if item["kind"] == "text"]
        self.assertTrue(any("…" in text for text in texts), texts)
        # The editing caret carries its character index for exact placement.
        lines = [item for item in snap["template"]["items"] if item["kind"] == "line"]
        self.assertTrue(any(item.get("caretChars") is not None and item["caretChars"] >= 0 for item in lines), lines)
        call("ui_press", key="AC")

    def test_long_result_exposes_viewport(self):
        call("ui_press", key="AC")
        for _ in range(40):
            call("ui_press", key="7")
        call("ui_press", key="EQUALS")
        snap = call("ui_snapshot")["snapshot"]
        self.assertIsNotNone(snap.get("resultFull"))
        self.assertEqual(len(snap["resultFull"]), 40)
        self.assertLess(len(snap["result"]), len(snap["resultFull"]))
        self.assertEqual(snap.get("resultOffset"), 0)
        call("ui_press", key="AC")

    def test_solve_replays_with_shift_branch(self):
        # SHIFT+CALC opens SOLVE; the replay must stay on the SHIFT branch.
        call("ui_press", key="AC")
        for key in ("X", "POWER", "2", "MINUS", "9"):
            call("ui_press", key=key)
        call("ui_press", key="ALPHA")
        call("ui_press", key="CALC")  # inserts the red '='
        call("ui_press", key="0")
        call("ui_press", key="SHIFT")
        snap = call("ui_press", key="CALC")["snapshot"]
        self.assertIsNotNone(snap["dialog"])
        self.assertEqual(snap["dialog"]["title"], "SOLVE")
        snap = call("ui_dialog_answer", value=1.0)["snapshot"]
        self.assertIsNone(snap["dialog"])
        self.assertIn("x=3", snap["result"])

    def test_conversion_dialog_converts(self):        # SHIFT+8 opens CONV (Entry + Listbox + Convert button).
        call("ui_press", key="SHIFT")
        snap = call("ui_press", key="8")["snapshot"]
        self.assertTrue(snap["dialogs"], "CONV dialog should be open")
        dialog = snap["dialogs"][-1]
        listbox = find([dialog["root"]], lambda n: n["kind"] == "Listbox")
        convert = find([dialog["root"]], lambda n: n["kind"] == "Button" and n["text"] == "Convert")
        self.assertIsNotNone(listbox)
        self.assertIsNotNone(convert)
        self.assertIn("in→cm", listbox["items"])
        call("ui_dialog_invoke", dialog=dialog["id"], widget=listbox["id"], action="select",
             value=listbox["items"].index("in→cm"))
        snap = call("ui_dialog_invoke", dialog=dialog["id"], widget=convert["id"], action="command")["snapshot"]
        self.assertFalse(snap["dialogs"])
        self.assertTrue(snap["result"])

    def test_setup_dialog_hides_desktop_only_ui_scale(self):
        # The Compose layer scales the skin, so the desktop UI-scale editor must
        # not be exported to Android; the other Setup rows are still present.
        call("ui_press", key="SHIFT")
        snap = call("ui_press", key="MENU")["snapshot"]
        self.assertTrue(snap["dialogs"], "SETUP dialog should be open")
        dialog = snap["dialogs"][-1]

        texts = []

        def walk(nodes):
            for node in nodes:
                texts.append(node.get("text", ""))
                walk(node.get("children", []))

        walk([dialog["root"]])
        self.assertNotIn("UI Scale", texts)
        combos = []

        def collect(nodes):
            for node in nodes:
                if node["kind"] == "Combobox":
                    combos.append(node)
                collect(node.get("children", []))

        collect([dialog["root"]])
        # Angle Unit survives the filter, so Setup still works end to end.
        self.assertTrue(any("DEG" in c["values"] and "RAD" in c["values"] for c in combos))
        call("ui_dialog_close_all")

    def test_lcd_flow_result_exposes_viewport(self):
        # Workspace flows (Matrix/Vector/History/...) keep a multi-row result
        # viewport instead of the completed-result fields.  Its current row and
        # pan offset must reach Android so a long row can be inspected with ◀/▶.
        headless = __import__("headless_app")
        app = headless._require()
        long_line = "1234567890" * 6
        app._lcd_flow = {"mode": "Test", "values": {}, "draft": {}, "last_error": ""}
        app._lcd_show_results("TEST", [long_line])
        snap = call("ui_snapshot")["snapshot"]
        self.assertEqual(snap["resultFull"], long_line)
        self.assertEqual(snap["resultOffset"], 0)
        self.assertLess(len(snap["result"]), len(long_line))
        snap = call("ui_press", key="RIGHT")["snapshot"]
        self.assertEqual(snap["resultFull"], long_line)
        self.assertEqual(snap["resultOffset"], 1)
        app._reset_lcd_flow()


if __name__ == "__main__":
    unittest.main()
