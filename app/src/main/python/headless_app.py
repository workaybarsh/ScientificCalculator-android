"""Headless driver for the real desktop App, used by the Android bridge.

Android has no Tk display, so ``tkinter`` and ``PIL`` are satisfied by the
virtual packages shipped beside this module.  The *real* ``scientific_calculator.app``
runs unmodified: this driver only

* constructs the App once,
* routes each Android key press to the matching desktop method, and
* returns an :func:`snapshot` of the LCD (status / expression / result /
  template / captured menu / live dialogs) for Compose to render.

Modal ``simpledialog``/``messagebox`` prompts are handled with a replay
protocol: when one is reached the action unwinds, Compose answers it, and the
action is replayed with the answer queued.  Custom ``Toplevel`` dialogs (SETUP,
CONST, CONV, RESET) are serialized widget trees whose commands are invoked
directly.
"""
from __future__ import annotations

import os
from typing import Any

import tkinter as tk  # the virtual package when running on Android
from tkinter import messagebox

_app = None
_data_dir: str | None = None
_power_off = False


class DialogPending(Exception):
    """Raised to unwind a key action until Compose answers a modal prompt."""


_pending_dialog: dict[str, Any] | None = None
_dialog_answers: list[Any] = []
_dialog_index = 0
_last_action = None
_modifier_snapshot: tuple[bool, bool] | None = None


def configure(data_dir: str) -> None:
    global _data_dir
    _data_dir = str(data_dir)
    os.environ["LOCALAPPDATA"] = _data_dir
    os.environ.setdefault("HOME", _data_dir)


def _inline_background_calculation(self, method, args, on_success):
    """Replace the multiprocessing worker with a synchronous call."""
    try:
        result = getattr(self.core, method)(*args)
    except Exception as error:  # noqa: BLE001 - App.err renders it on the LCD
        self.err(error)
        return False
    on_success(result)
    try:
        self._persist_calculation_history()
    except Exception:  # noqa: BLE001 - persistence must not break a calculation
        pass
    return True


def _patch_draw_edit_text(app_module) -> None:
    """Make every template box slice its text to the box width.

    The desktop passes ``max_text_width`` for most boxes, but the single
    integral's upper/lower bounds and a few others pass only the box rectangle.
    Those fields then draw past their box.  Defaulting ``max_text_width`` from
    the box keeps the desktop's own ``caret_text_view`` behaviour everywhere.
    """
    original = app_module.App._draw_edit_text

    def _draw_edit_text(self, c, key, text, x, y, font_desc, box=None, anchor="w", max_text_width=None, empty_placeholder="□"):
        if max_text_width is None and box is not None:
            if anchor == "w":
                max_text_width = max(1, box[2] - x)
            elif anchor == "e":
                max_text_width = max(1, x - box[0])
        return original(self, c, key, text, x, y, font_desc, box, anchor, max_text_width, empty_placeholder)

    app_module.App._draw_edit_text = _draw_edit_text


def start() -> None:
    global _app, _power_off
    if _app is not None:
        return
    from scientific_calculator import app as app_module

    app_module.App._run_background_calculation = _inline_background_calculation
    app_module.App._build_application_controllers = lambda self: setattr(self, "calculation_controller", None)
    app_module.App._restart_application = _safe_restart
    app_module.App._on_close = _safe_on_close
    _patch_draw_edit_text(app_module)
    _power_off = False
    instance = app_module.App()
    instance.core.cas_isolated = False
    instance.core.cas_timeout = None
    _app = instance


def power_on() -> None:
    """Return the calculator to a clean, switched-on state.

    The Python interpreter lives for the whole process, so state left by the
    previous session survives an Activity restart: the OFF latch itself, plus
    the SHIFT modifier that ``ac_key`` does not clear on the desktop (where the
    window simply closes).  Without this, re-entering the app from recents would
    immediately finish again, and the first key press would behave as if SHIFT
    were still held.
    """
    global _power_off
    _power_off = False
    application = _app
    if application is None:
        return
    try:
        application.shift = False
        application.alpha = False
    except Exception:  # noqa: BLE001 - a switch-on must never raise
        pass
    try:
        application._clear_before_interaction_transition()
        application.mode = "Calculate"
        application.status_refresh()
    except Exception:  # noqa: BLE001 - a switch-on must never raise
        pass


def _safe_on_close(self) -> None:
    """Android equivalent of the desktop SHIFT+AC OFF: save and request exit.

    The desktop closes its Tk window; Android cannot, so this persists settings
    and raises a flag that the Compose layer turns into ``Activity.finish()``.
    """
    global _power_off
    try:
        self.save_settings_file(False)
    except Exception:  # noqa: BLE001 - a power-off must not raise
        pass
    _power_off = True


def _safe_restart(self) -> None:
    """Android equivalent of the desktop ON key: reset state, keep preferences.

    The desktop launches a fresh process; Android must not, so this reloads the
    saved settings and returns the current process to a clean Calculate state.
    """
    try:
        self.save_settings_file(False)
    except Exception:  # noqa: BLE001 - a restart must not raise
        pass
    try:
        self.apply_saved_engine_settings()
        self._clear_before_interaction_transition()
        self.mode = "Calculate"
        self.status_refresh()
    except Exception:  # noqa: BLE001
        pass


def _require():
    if _app is None:
        start()
    return _app


def request_dialog(kind: str, title: Any, prompt: Any, initial: Any):
    """Called by the virtual simpledialog/messagebox from inside a key action."""
    global _dialog_index
    index = _dialog_index
    _dialog_index += 1
    if index < len(_dialog_answers):
        return _dialog_answers[index]
    raise DialogPending({
        "kind": kind,
        "title": str(title or ""),
        "prompt": str(prompt or ""),
        "initial": initial,
        "index": index,
    })


def _run_action(action) -> dict[str, Any]:
    global _last_action, _dialog_answers, _dialog_index, _pending_dialog, _modifier_snapshot
    application = _require()
    # Capture the modifier state BEFORE the action consumes it, so a replay
    # takes the same branch (e.g. SHIFT+CALC -> SOLVE, not CALC).
    _modifier_snapshot = (bool(application.shift), bool(application.alpha))
    _last_action = action
    _dialog_answers = []
    _dialog_index = 0
    _pending_dialog = None
    try:
        action()
    except DialogPending as pending:
        _pending_dialog = pending.args[0]
    return snapshot()


def answer(value: Any) -> dict[str, Any]:
    """Answer the pending modal prompt and replay the action."""
    global _dialog_answers, _dialog_index, _pending_dialog
    if _last_action is None:
        return snapshot()
    if _modifier_snapshot is not None:
        application = _require()
        application.shift, application.alpha = _modifier_snapshot
    _dialog_answers.append(value)
    _dialog_index = 0
    try:
        _last_action()
    except DialogPending as pending:
        _pending_dialog = pending.args[0]
        return snapshot()
    _pending_dialog = None
    _dialog_answers = []
    return snapshot()


# Physical-keypad hotspots, mirroring App._ui()'s _add_hotspot calls.
_KEY_ACTIONS = {
    "SHIFT": ("shift_key", None),
    "ALPHA": ("alpha_key", None),
    "MENU": ("menu_key", None),
    "ON": ("on_key", None),
    "UP": ("vertical_move", -1),
    "DOWN": ("vertical_move", 1),
    "LEFT": ("move", -1),
    "RIGHT": ("move", 1),
    "OPTN": ("optn_key", None),
    "CALC": ("calc_key", None),
    "INTEGRAL": ("integral_key", None),
    "X": ("x_key", None),
    "FRACTION": ("fraction_key", None),
    "SQRT": ("sqrt_key", None),
    "SQUARE": ("square_key", None),
    "POWER": ("power_key", None),
    "LOG": ("log_key", None),
    "LN": ("ln_key", None),
    "NEG": ("neg_key", None),
    "DMS": ("dms_key", None),
    "INV": ("inv_key", None),
    "SIN": ("trig_key", "sin"),
    "COS": ("trig_key", "cos"),
    "TAN": ("trig_key", "tan"),
    "STO": ("sto_key", None),
    "ENG": ("eng_key", None),
    "LPAREN": ("lparen_key", None),
    "RPAREN": ("rparen_key", None),
    "SD": ("sd_key", None),
    "MPLUS": ("mplus_key", None),
    "DEL": ("del_key", None),
    "AC": ("ac_key", None),
    "MUL": ("mul_key", None),
    "DIV": ("div_key", None),
    "PLUS": ("plus_key", None),
    "MINUS": ("minus_key", None),
    "DOT": ("dot_key", None),
    "SCI": ("sci_key", None),
    "ANS": ("ans_key", None),
    "EQUALS": ("equals", None),
}
for _digit in "0123456789":
    _KEY_ACTIONS[_digit] = ("num_key", _digit)


def _tk_font(font) -> tuple[str, int]:
    if isinstance(font, (tuple, list)) and len(font) >= 2:
        family = str(font[0])
        try:
            size = abs(int(float(font[1])))
        except (TypeError, ValueError):
            size = 12
        return family, size
    return "Monospace", 12


def _canvas_items(canvas) -> list[dict[str, Any]]:
    items = []
    last_text: dict[str, Any] | None = None
    for entry in getattr(canvas, "_items", []):
        options = entry.get("options", {})
        coords = entry.get("coords", [])
        item: dict[str, Any] = {"kind": entry["kind"]}
        if len(coords) >= 2:
            item["x"], item["y"] = coords[0], coords[1]
        if entry["kind"] == "text":
            family, size = _tk_font(options.get("font"))
            item["text"] = str(options.get("text", ""))
            item["anchor"] = options.get("anchor", "center")
            item["font"] = family
            item["size"] = size
            item["fill"] = str(options.get("fill", "#111111"))
        elif entry["kind"] == "rectangle" and len(coords) >= 4:
            item["x2"], item["y2"] = coords[2], coords[3]
            item["outline"] = str(options.get("outline", "#222222"))
            item["width"] = options.get("width", 1)
        elif entry["kind"] == "line" and len(coords) >= 4:
            item["x2"], item["y2"] = coords[2], coords[3]
            item["fill"] = str(options.get("fill", "#111111"))
            item["width"] = options.get("width", 1)
            # A caret line follows the text it edits; export the caret's
            # character index so Compose can place it with its own metrics.
            if last_text is not None:
                item["caretChars"] = _caret_char_count(last_text, float(item["x"]) - float(last_text["x"]))
                item["caretTextX"] = last_text["x"]
                item["caretText"] = last_text["text"]
                item["caretSize"] = last_text["size"]
        items.append(item)
        if entry["kind"] == "text":
            last_text = item
        elif entry["kind"] == "rectangle":
            pass
        else:
            last_text = None
    return items


def _caret_char_count(text_item: dict[str, Any], offset: float) -> int:
    """Invert the virtual monospace measure to recover the caret's char index."""
    text = str(text_item.get("text", ""))
    size = int(text_item.get("size", 12))
    advance = 0.6 * size
    if advance <= 0:
        return 0
    count = int(round(offset / advance))
    return max(0, min(len(text), count))


_SKIP_KINDS = {"Menu", "Tk"}
# Desktop-only settings the Android port intentionally does not surface.  The
# Compose layer scales the calculator skin itself, so the Tk UI-scale editor has
# no effect on Android and must not appear in the serialized Setup dialog.
_ANDROID_HIDDEN_DIALOG_LABELS = {"UI Scale"}


def _widget_label(widget) -> str:
    text = getattr(widget, "_text", None)
    if text is None:
        text = widget._options.get("text", "")
    return str(text or "")


def _android_hidden_row(widget) -> bool:
    """True for a dialog row that exists only for a desktop-only setting."""
    children = getattr(widget, "_children", [])
    return any(_widget_label(child) in _ANDROID_HIDDEN_DIALOG_LABELS for child in children)


def _serialize(widget) -> dict[str, Any]:
    node: dict[str, Any] = {"id": widget._widget_id, "kind": widget._kind}
    node["text"] = _widget_label(widget)
    if widget._kind == "Combobox":
        node["values"] = list(getattr(widget, "_values", []))
        variable = widget._options.get("textvariable")
        node["value"] = variable.get() if variable is not None else getattr(widget, "_current", "")
        node["editable"] = widget._options.get("state") != "readonly"
    elif widget._kind == "Entry":
        node["value"] = widget.get()
        node["editable"] = True
    elif widget._kind == "Listbox":
        node["items"] = list(widget._items)
        node["selection"] = widget._selection
    node["command"] = widget._options.get("command") is not None
    node["children"] = [
        _serialize(child)
        for child in widget._children
        if child._kind not in _SKIP_KINDS and not _android_hidden_row(child)
    ]
    return node


def _dialogs() -> list[dict[str, Any]]:
    return [
        {"id": top._widget_id, "title": top._options.get("title", ""), "root": _serialize(top)}
        for top in list(tk.TOPLEVELS)
        if not top._destroyed
    ]


def _flatten_menu(menu, prefix: str, path: list[int]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for index, entry in enumerate(menu._entries):
        if entry.get("separator"):
            entries.append({"label": None, "separator": True, "path": None})
            continue
        child = entry.get("menu")
        if child is not None:
            entries.extend(_flatten_menu(child, prefix + str(entry.get("label", "")) + " › ", path + [index]))
            continue
        entries.append({
            "label": prefix + str(entry.get("label", "")),
            "separator": False,
            "path": path + [index],
            "index": (path + [index])[0],
        })
    return entries


def _active_menu():
    return tk.ACTIVE_MENU


def _menu_snapshot() -> list[dict[str, Any]] | None:
    menu = _active_menu()
    if menu is None:
        return None
    return _flatten_menu(menu, "", [])


def _menu_entries(menu):
    return list(menu._entries)


def _result_viewport_source(application) -> tuple[str | None, int]:
    """Return the full text and pan offset backing the current LCD result.

    Completed calculations keep their full string in ``_completed_result_text``.
    LCD workspace flows (Matrix/Vector/History/...) instead pan a row of
    ``result_lines``; exposing that row and its offset lets the Compose layer
    render the same window the desktop shows instead of fitting a truncated
    slice with no knowledge of the text around it.
    """
    full = getattr(application, "_completed_result_text", None)
    offset = int(getattr(application, "_completed_result_offset", 0) or 0)
    if full is not None:
        return str(full), offset
    try:
        flow = application._lcd_state()
    except Exception:  # noqa: BLE001 - a snapshot must never raise
        flow = None
    if isinstance(flow, dict) and flow.get("phase") == "results":
        lines = flow.get("result_lines") or []
        if lines:
            index = max(0, min(len(lines) - 1, int(flow.get("result_index", 0) or 0)))
            return str(lines[index]), int(flow.get("result_offset", 0) or 0)
    return None, 0


def snapshot() -> dict[str, Any]:
    application = _require()
    result_full, result_offset = _result_viewport_source(application)
    result = {
        "mode": application.mode,
        "angleUnit": application.core.settings.angle_unit,
        "base": application.base,
        "shift": bool(application.shift),
        "alpha": bool(application.alpha),
        "status": application.status.cget("text"),
        "expr": application.expr.get(),
        "result": application.result.cget("text"),
        "resultFull": result_full,
        "resultOffset": result_offset,
        "powerOff": _power_off,
        "hint": application.MODE_HINTS.get(application.mode, ""),
        "skin": getattr(application, "skin_name", "Graphite"),
        "template": None,
        "menu": _menu_snapshot(),
        "dialog": _pending_dialog,
        "dialogs": _dialogs(),
        "info": list(messagebox.INFO_MESSAGES),
    }
    if getattr(application, "template_kind", None):
        result["template"] = {
            "kind": application.template_kind,
            "items": _canvas_items(application.template_canvas),
            "canvas": {
                "width": application.template_canvas.winfo_width(),
                "height": application.template_canvas.winfo_height(),
            },
        }
    return result


def press(key: str, value: Any = None) -> dict[str, Any]:
    application = _require()
    # A new key press dismisses any previously captured popup menu.
    tk.MENUS.clear()
    tk.ACTIVE_MENU = None
    action = _KEY_ACTIONS.get(key)
    if action is None:
        raise KeyError(f"unknown key {key}")
    method, argument = action
    function = getattr(application, method)
    if argument is None:
        return _run_action(lambda: function())
    return _run_action(lambda: function(argument))


def menu_select(index: Any = None, path: Any = None) -> dict[str, Any]:
    application = _require()
    menu = _active_menu()
    if menu is None:
        return snapshot()
    if path is None:
        path = [int(index)]
    current_entries = menu._entries
    entry = None
    for position, step in enumerate(path):
        entry = current_entries[int(step)]
        if position < len(path) - 1:
            child_menu = entry.get("menu")
            if child_menu is None:
                return snapshot()
            current_entries = child_menu._entries
    if entry is None:
        return snapshot()
    command = entry.get("command")
    if command is None:
        return snapshot()

    def run():
        command()
        tk.ACTIVE_MENU = None

    return _run_action(run)


def invoke_dialog(dialog_id: int, widget_id: int, action: str, value: Any = None) -> dict[str, Any]:
    widget = tk.WIDGETS.get(int(widget_id))
    if widget is None:
        return snapshot()

    def set_value():
        variable = widget._options.get("textvariable")
        if variable is not None:
            variable.set(value)
        elif widget._kind == "Entry":
            widget._buffer = "" if value is None else str(value)
        elif widget._kind == "Combobox":
            widget.set(value)

    def run_command():
        if widget._kind == "Listbox" and value is not None:
            widget.selection_set(int(value))
        command = widget._options.get("command")
        if command is not None:
            command()

    if action == "set":
        return _run_action(set_value)
    if action == "select":
        def select():
            if widget._kind == "Listbox" and value is not None:
                widget.selection_set(int(value))
        return _run_action(select)
    return _run_action(run_command)


def close_dialogs() -> dict[str, Any]:
    for top in list(tk.TOPLEVELS):
        top.destroy()
    return snapshot()


def dismiss_info() -> dict[str, Any]:
    messagebox.INFO_MESSAGES.clear()
    return snapshot()
