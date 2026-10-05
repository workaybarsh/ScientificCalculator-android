"""JSON bridge between the Kotlin UI and the Tk-free Scientific Calculator engine.

Kotlin calls ``call(op, args_json) -> result_json`` from one background thread.
Every result is a JSON object::

    {"ok": true,  "text": "<display string>", "history": [[expr, result], ...], ...extras}
    {"ok": false, "error": "<message>"}

The bridge is the Android replacement for the desktop ``App`` + calculation
worker boundary.  It owns exactly one stateful engine, serializes every call,
translates legacy Turkish domain errors to English at this boundary, and keeps
settings plus the last ten history entries in a SQLite store inside the app's
private data directory (see ``configure``).

Cancellation uses ``PyThreadState_SetAsyncExc`` because Android has no reliable
``multiprocessing``.  It interrupts pure-Python code (SymPy) at bytecode
boundaries; a single long native SciPy call only stops when it returns to
Python.  Kotlin is responsible for the wall-clock timeout.

No operation ever raises: an unexpected failure is reported as
``Internal ERROR`` so the app process cannot be killed by a bad calculation.
"""
from __future__ import annotations

import ctypes
import json
import math
import os
import threading
from dataclasses import fields
from pathlib import Path
from typing import Any, Callable

import numpy as np
import sympy as sp

from scientific_calculator.calculation_result import CalculationResult
from scientific_calculator.calculator_engine import CalculatorError, ScientificCalculatorEngine
from scientific_calculator.constants_data import CONSTANTS_DATASET_LABELS
from scientific_calculator.engine.settings import CalculatorSettings
from scientific_calculator.errors import translate_error_message
from scientific_calculator.history import CalculationHistoryEntry
from scientific_calculator.settings_store import SettingsStore
from scientific_calculator.spreadsheet import SpreadsheetModel

_MISSING = object()

_lock = threading.Lock()          # the engine is stateful; serialize all access
_state_lock = threading.Lock()    # guards _current_tid
_current_tid: int | None = None
_engine: ScientificCalculatorEngine | None = None
_sheet: SpreadsheetModel | None = None
_store: SettingsStore | None = None
_data_dir: str | None = None

# ---------------------------------------------------------------------------
# Settings policy (mirrors App.SETTINGS_ENUMS / App.BOOLEAN_SETTINGS)
# ---------------------------------------------------------------------------
_ENUM_SETTINGS: dict[str, frozenset[str]] = {
    "angle_unit": frozenset({"DEG", "RAD", "GRA"}),
    "input_output": frozenset({"MathI/MathO", "MathI/DecimalO", "LineI/LineO", "LineI/DecimalO"}),
    "number_format": frozenset({"Norm", "Fix", "Sci"}),
    "complex_format": frozenset({"a+bi", "r∠θ"}),
    "spreadsheet_show_cell": frozenset({"Formula", "Value"}),
    "decimal_mark": frozenset({"Dot", "Comma"}),
    "multiline_font": frozenset({"Normal", "Small"}),
    "constant_dataset": frozenset(CONSTANTS_DATASET_LABELS),
}
_BOOLEAN_SETTINGS = frozenset({
    "engineer_symbol", "statistics_freq", "spreadsheet_auto_calc",
    "equation_complex", "table_two_functions", "digit_separator",
})

# Operations that never mutate persisted state, so a successful call skips a
# SQLite write.  Every other successful call persists settings + history.
_READ_ONLY_OPS = frozenset({
    "ping", "get_settings", "history", "history_recall", "matrix_get",
    "vector_get", "conversions", "sheet_snapshot", "configure",
    "ui_snapshot",
})


class _Cancelled(BaseException):
    """Injected into the worker thread by cancel(); BaseException so it is never swallowed."""


# ---------------------------------------------------------------------------
# Engine / persistence lifecycle
# ---------------------------------------------------------------------------
def _get_engine() -> ScientificCalculatorEngine:
    global _engine, _sheet
    if _engine is None:
        # Inline CAS: no child processes on Android; Kotlin owns timeouts.
        _engine = ScientificCalculatorEngine(cas_isolated=False, cas_timeout=None)
        _sheet = SpreadsheetModel(_engine)
    return _engine


def _get_sheet() -> SpreadsheetModel:
    global _sheet
    engine = _get_engine()
    if _sheet is None:
        _sheet = SpreadsheetModel(engine)
    return _sheet


def _settings_dict(engine: ScientificCalculatorEngine) -> dict[str, object]:
    return {f.name: getattr(engine.settings, f.name) for f in fields(CalculatorSettings)}


def _assign_settings(engine: ScientificCalculatorEngine, values: dict[str, object], *, strict: bool) -> None:
    """Validate and assign settings, mirroring the desktop codec's rules."""
    allowed = {f.name: f for f in fields(CalculatorSettings)}
    for key, value in values.items():
        if key not in allowed:
            if strict:
                raise CalculatorError(f"Argument ERROR: unknown setting {key}")
            continue
        if key == "number_digits":
            if type(value) is int and 0 <= value <= 9:
                setattr(engine.settings, key, value)
            elif strict:
                raise CalculatorError("Argument ERROR: number_digits must be 0..9")
        elif key in _BOOLEAN_SETTINGS:
            if type(value) is bool:
                setattr(engine.settings, key, value)
            elif strict:
                raise CalculatorError(f"Argument ERROR: {key} must be boolean")
        elif key in _ENUM_SETTINGS:
            if value in _ENUM_SETTINGS[key]:
                setattr(engine.settings, key, value)
            elif strict:
                raise CalculatorError(f"Argument ERROR: invalid value for {key}")
        elif strict:
            # calculator_settings currently has no other free-form field.
            setattr(engine.settings, key, value)


def _persist() -> None:
    """Atomically save settings + history; never let a storage fault break a calculation."""
    if _store is None or _engine is None:
        return
    try:
        _store.save_state(_settings_dict(_engine), list(_engine.history))
    except Exception:  # noqa: BLE001 - storage must not surface as a calculation error
        pass


def _load_state() -> None:
    if _store is None or _engine is None:
        return
    try:
        saved = _store.load()
    except Exception:  # noqa: BLE001
        saved = None
    if isinstance(saved, dict):
        _assign_settings(_engine, saved, strict=False)
    try:
        history = _store.load_history()
    except Exception:  # noqa: BLE001
        history = None
    if history is not None:
        _engine.history[:] = list(history)


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------
def _history(engine: ScientificCalculatorEngine) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    for entry in engine.history:
        entries.append({
            "expression": entry.expression,
            "result": entry.result,
            "kind": entry.kind,
            "metadata": entry.metadata,
        })
    return entries


def _format_value(engine: ScientificCalculatorEngine, value: Any, approximate: bool = False) -> str:
    if value is None:
        return ""
    if isinstance(value, CalculationResult):
        return _format_typed(engine, value)
    if isinstance(value, np.ndarray):
        if np.iscomplexobj(value):
            return "[" + ", ".join(_format_value(engine, complex(item), approximate) for item in value) + "]"
        return engine.format_result(value)
    if isinstance(value, tuple):
        return "(" + ", ".join(_format_value(engine, item, approximate) for item in value) + ")"
    return engine.format_result(value, approximate)


def _format_typed(engine: ScientificCalculatorEngine, result: CalculationResult) -> str:
    if result.value is not None:
        return engine.format_result(result.value, approximate=result.approx_value is not None)
    message = (result.message_code or result.status.value).replace("_", " ").strip()
    return message[:1].upper() + message[1:] if message else "No result"


def _payload(text: str = "", **extra: Any) -> dict[str, object]:
    payload: dict[str, object] = {"text": text}
    payload.update(extra)
    return payload


def _number(value: Any) -> Any:
    """Return a JSON-native number from a NumPy scalar, if possible."""
    if isinstance(value, np.generic):
        return value.item()
    return value


def _array_json(array: np.ndarray | None) -> Any:
    if array is None:
        return None
    return [[_number(item) for item in row] for row in np.atleast_2d(array)]


def _vector_json(array: np.ndarray | None) -> Any:
    if array is None:
        return None
    return [_number(item) for item in np.atleast_1d(array)]


# ---------------------------------------------------------------------------
# Core / settings / memory / history
# ---------------------------------------------------------------------------
def _op_ping(e, a):
    return _payload("pong")


def _op_configure(e, a):
    global _store, _data_dir
    path = a.get("path")
    engine = _get_engine()
    if path is None:
        return _payload(_data_dir or "", settings=_settings_dict(engine))
    _data_dir = str(path)
    _store = SettingsStore(Path(_data_dir) / "settings.db")
    _load_state()
    return _payload(_data_dir, settings=_settings_dict(engine))


def _op_get_settings(e, a):
    return _payload("", settings=_settings_dict(e))


def _op_set_settings(e, a):
    _assign_settings(e, a, strict=True)
    return _payload("ok", settings=_settings_dict(e))


def _op_reset_all(e, a):
    e.initialize_all()
    sheet = _get_sheet()
    sheet.delete_all()
    return _payload("ok", settings=_settings_dict(e))


def _op_evaluate(e, a):
    exact = bool(a.get("exact", True))
    return _payload(_format_value(e, e.evaluate(a["expr"], exact=exact), approximate=not exact))


def _op_approx(e, a):
    return _payload(_format_value(e, e.evaluate(a["expr"], exact=False), approximate=True))


def _op_evaluate_with_values(e, a):
    values = a.get("values") or {}
    if not isinstance(values, dict):
        raise CalculatorError("Argument ERROR: values must be an object")
    return _payload(_format_value(e, e.evaluate_with_values(a["expr"], values), approximate=True))


def _op_summation(e, a):
    value = e.summation(a["expr"], a["lower"], a["upper"], a.get("var", "x"))
    return _payload(_format_value(e, value))


def _op_memory_store(e, a):
    value = e.store(a["name"], a.get("value")) if a.get("value") is not None else e.store(a["name"])
    return _payload(_format_value(e, value))


def _op_memory_recall(e, a):
    name = a["name"]
    if name not in e.memory:
        raise CalculatorError("Argument ERROR: Geçersiz bellek")
    return _payload(_format_value(e, e.memory[name]))


def _op_memory_add(e, a):
    return _payload(_format_value(e, e.m_plus()))


def _op_memory_sub(e, a):
    return _payload(_format_value(e, e.m_minus()))


def _op_history(e, a):
    return _payload("", history=_history(e))


def _op_history_clear(e, a):
    e.history.clear()
    return _payload("ok")


def _op_history_recall(e, a):
    index = int(a["index"])
    try:
        entry = e.history[index]
    except (IndexError, TypeError):
        raise CalculatorError("Argument ERROR: history index out of range")
    return _payload(entry.expression, kind=entry.kind, metadata=entry.metadata)


def _op_prime_factorization(e, a):
    factors = e.prime_factorization(a["n"])
    text = " × ".join(
        str(prime) if power == 1 else f"{prime}^{power}"
        for prime, power in sorted(factors.items())
    )
    return _payload(text or str(a["n"]), factors={str(k): v for k, v in sorted(factors.items())})


def _op_random_number(e, a):
    return _payload(_format_value(e, e.random_number(), approximate=True))


def _op_random_int(e, a):
    return _payload(str(e.random_int(a["lower"], a["upper"])))


def _op_decimal_to_dms(e, a):
    degrees, minutes, seconds = e.dms_from_decimal(float(a["x"]))
    return _payload(f"{degrees:g}° {minutes}' {seconds:g}\"", degrees=degrees, minutes=minutes, seconds=seconds)


def _op_dms_to_decimal(e, a):
    value = e.decimal_from_dms(float(a["d"]), float(a["m"]), float(a["s"]))
    return _payload(_format_value(e, value, approximate=True))


def _op_pol(e, a):
    radius, angle = e.pol(float(a["x"]), float(a["y"]))
    return _payload(f"r={radius:.12g}  θ={angle:.12g}", r=radius, theta=angle)


def _op_rec(e, a):
    x, y = e.rec(float(a["r"]), float(a["theta"]))
    return _payload(f"x={x:.12g}  y={y:.12g}", x=x, y=y)


def _op_table(e, a):
    variable = a.get("var", "x")
    symbol = sp.Symbol(variable)
    expression = e.parse_symbolic(a["expr"], {variable: symbol})
    start = float(a["start"])
    stop = float(a["end"])
    step = float(a["step"])
    if not all(math.isfinite(value) for value in (start, stop, step)) or step == 0:
        raise CalculatorError("Argument ERROR: table bounds must be finite and step non-zero")
    rows: list[dict[str, object]] = []
    current = start
    lock = bool(step > 0)
    for _ in range(1001):
        if (lock and current > stop + 1e-12) or (not lock and current < stop - 1e-12):
            break
        try:
            value = sp.N(expression.subs(symbol, sp.Float(current)), 15)
            rendered = _format_value(e, value, approximate=True)
        except Exception:  # noqa: BLE001 - a single row must not fail the table
            rendered = "ERROR"
        rows.append({"x": current, "y": rendered})
        current += step
    if len(rows) > 200:
        raise CalculatorError("Argument ERROR: table range exceeds the row limit")
    lines = [f"{row['x']:.6g}   {row['y']}" for row in rows]
    return _payload("\n".join(lines), rows=rows)


# ---------------------------------------------------------------------------
# Calculus
# ---------------------------------------------------------------------------
def _op_derivative(e, a):
    value = e.symbolic_derivative(a["expr"], a.get("var", "x"))
    return _payload(_format_value(e, value))


def _op_derivative_at(e, a):
    value = e.derivative(a["expr"], a["point"], a.get("var", "x"))
    return _payload(_format_value(e, value, approximate=True))


def _op_integral(e, a):
    value = e.symbolic_integral(a["expr"], a.get("var", "x"))
    return _payload(_format_value(e, value) + " + C")


def _op_integral_definite(e, a):
    result = e.definite_integral_result(a["expr"], a["lower"], a["upper"], a.get("var", "x"))
    return _payload(_format_typed(e, result), status=result.status.value)


def _op_integral_double(e, a):
    value = e.double_integral(
        a["expr"], a["outer_lower"], a["outer_upper"], a["inner_lower"], a["inner_upper"],
        a.get("outer_var", "x"), a.get("inner_var", "y"),
    )
    return _payload(_format_value(e, value, approximate=True))


def _op_integral_triple(e, a):
    value = e.triple_integral(
        a["expr"], a["outer_lower"], a["outer_upper"], a["middle_lower"], a["middle_upper"],
        a["inner_lower"], a["inner_upper"], a.get("outer_var", "x"), a.get("middle_var", "y"),
        a.get("inner_var", "z"),
    )
    return _payload(_format_value(e, value, approximate=True))


def _op_solve(e, a):
    variable = a.get("var", "x")
    root, residual = e.solve(a["equation"], variable, a.get("guess", 0.0))
    return _payload(f"{variable} = {root:.12g}", root=root, residual=residual, variable=variable)


def _op_ode(e, a):
    value = e.solve_ode(
        a["equation"], a.get("dependent", "y"), a.get("independent", "x"),
        a.get("conditions") or None,
    )
    return _payload(_format_value(e, value))


# ---------------------------------------------------------------------------
# Complex mode
# ---------------------------------------------------------------------------
def _op_complex_eval(e, a):
    return _payload(_format_value(e, e.complex_eval(a["expr"])))


def _op_complex_argument(e, a):
    value = e.complex_argument(complex(e.parse(a["z"])))
    return _payload(_format_value(e, value, approximate=True))


def _op_to_polar(e, a):
    radius, angle = e.to_polar(complex(e.parse(a["z"])))
    return _payload(f"{radius:.12g}∠{angle:.12g}", r=radius, theta=angle)


def _op_from_polar(e, a):
    value = e.from_polar(float(a["r"]), float(a["theta"]))
    return _payload(_format_value(e, value))


def _op_complex_derivative(e, a):
    result = e.complex_derivative_result(a["expr"], a.get("var", "z"), a.get("point") or None)
    return _payload(_format_typed(e, result), status=result.status.value)


def _op_complex_limit(e, a):
    result = e.complex_limit_result(a["expr"], a["point"], a.get("var", "z"))
    return _payload(_format_typed(e, result), status=result.status.value)


def _op_complex_integral(e, a):
    value = e.complex_definite_integral(a["expr"], a["lower"], a["upper"], a.get("var", "z"))
    return _payload(_format_value(e, value, approximate=True))


# ---------------------------------------------------------------------------
# Base-N
# ---------------------------------------------------------------------------
def _op_base_eval(e, a):
    base = int(a.get("base", 10))
    value = e.evaluate_base(a["expr"], base)
    return _payload(e.format_base(value, base), value=value)


def _op_base_format(e, a):
    return _payload(e.format_base(a["value"], int(a["base"])))


def _op_base_op(e, a):
    value = e.base_operation(a["a"], a.get("b"), a.get("op", "and"))
    payload = _payload(str(value), value=value)
    if a.get("base") is not None:
        payload["text"] = e.format_base(value, int(a["base"]))
    return payload


def _op_base_parse(e, a):
    value = e.parse_base_token(a["token"], int(a["base"]))
    return _payload(str(value), value=value)


# ---------------------------------------------------------------------------
# Matrix / vector
# ---------------------------------------------------------------------------
def _op_matrix_define(e, a):
    value = e.define_matrix(a["name"], a["data"])
    return _payload(e.format_result(value), matrix=_array_json(value))


def _op_matrix_op(e, a):
    value = e.matrix_op(a["op"], a.get("a"), a.get("b"))
    if isinstance(value, np.ndarray):
        return _payload(e.format_result(value), matrix=_array_json(value))
    return _payload(_format_value(e, value, approximate=True), scalar=_number(value))


def _op_matrix_identity(e, a):
    value = e.identity(int(a["n"]))
    return _payload(e.format_result(value), matrix=_array_json(value))


def _op_matrix_get(e, a):
    definitions = {name: _array_json(value) for name, value in e.matrices.items()}
    return _payload(_format_value(e, e.mat_ans) if e.mat_ans is not None else "", matrices=definitions,
                    mat_ans=_array_json(e.mat_ans))


def _op_matrix_clear(e, a):
    name = a.get("name")
    from scientific_calculator.engine.state_defaults import default_matrices

    if name:
        if name not in e.matrices:
            raise CalculatorError("Argument ERROR: geçersiz matris adı")
        e.matrices[name] = None
    else:
        e.matrices = default_matrices()
        e.mat_ans = None
    return _payload("ok")


def _op_vector_define(e, a):
    value = e.define_vector(a["name"], a["data"])
    return _payload(e.format_result(value), vector=_vector_json(value))


def _op_vector_op(e, a):
    value = e.vector_op(a["op"], a.get("a"), a.get("b"), a.get("scalar"))
    if isinstance(value, np.ndarray):
        return _payload(e.format_result(value), vector=_vector_json(value))
    return _payload(_format_value(e, value, approximate=True), scalar=_number(value))


def _op_vector_get(e, a):
    definitions = {name: _vector_json(value) for name, value in e.vectors.items()}
    return _payload(_format_value(e, e.vct_ans) if e.vct_ans is not None else "", vectors=definitions,
                    vct_ans=_vector_json(e.vct_ans))


def _op_vector_clear(e, a):
    name = a.get("name")
    from scientific_calculator.engine.state_defaults import default_vectors

    if name:
        if name not in e.vectors:
            raise CalculatorError("Argument ERROR: geçersiz vektör adı")
        e.vectors[name] = None
    else:
        e.vectors = default_vectors()
        e.vct_ans = None
    return _payload("ok")


# ---------------------------------------------------------------------------
# Statistics / regression / distributions
# ---------------------------------------------------------------------------
def _render_mapping(e, mapping: dict[str, Any]) -> str:
    lines = []
    for key, value in mapping.items():
        if value is None:
            rendered = "—"
        elif isinstance(value, float) and not math.isfinite(value):
            rendered = "—"
        else:
            rendered = _format_value(e, float(value), approximate=True)
        lines.append(f"{key} = {rendered}")
    return "\n".join(lines)


def _op_one_var_stats(e, a):
    freq = a.get("freq")
    stats = e.one_var_stats(a["x"], freq)
    clean = {name: float(value) for name, value in stats.items()}
    return _payload(_render_mapping(e, clean), stats=clean)


def _op_regression(e, a):
    result = e.regression(a["x"], a["y"], a.get("kind", "linear"))
    coefficients = {key: float(value) for key, value in result.items() if key != "predict"}
    return _payload(_render_mapping(e, coefficients), regression=coefficients)


def _op_normal_p(e, a):
    return _payload(_format_value(e, e.normal_P(a["t"]), approximate=True))


def _op_normal_q(e, a):
    return _payload(_format_value(e, e.normal_Q(a["t"]), approximate=True))


def _op_normal_r(e, a):
    return _payload(_format_value(e, e.normal_R(a["t"]), approximate=True))


def _op_distribution(e, a):
    kind = a["kind"]
    parameters = {key: value for key, value in a.items() if key != "kind"}
    value = e.distribution(kind, **parameters)
    return _payload(_format_value(e, value, approximate=True), value=value)


# ---------------------------------------------------------------------------
# Equation / inequality / polynomial / simultaneous / ratio
# ---------------------------------------------------------------------------
def _op_polynomial_roots(e, a):
    roots = e.polynomial_roots(a["coeffs"])
    lines = []
    serialized: list[Any] = []
    for index, root in enumerate(roots, start=1):
        real, imaginary = float(np.real(root)), float(np.imag(root))
        if abs(imaginary) <= 1e-10 * max(1.0, abs(real)):
            lines.append(f"x{index} = {_format_value(e, real, approximate=True)}")
            serialized.append(real)
        else:
            lines.append(f"x{index} = {_format_value(e, complex(real, imaginary), approximate=True)}")
            serialized.append([real, imaginary])
    return _payload("\n".join(lines), roots=serialized)


def _op_simultaneous(e, a):
    solution = e.simultaneous(a["a"], a["b"])
    lines = [f"x{index} = {_format_value(e, float(value), approximate=True)}" for index, value in enumerate(solution, start=1)]
    return _payload("\n".join(lines), solution=[float(value) for value in solution])


def _op_inequality(e, a):
    value = e.inequality(a["coeffs"], a["relation"])
    return _payload(_format_value(e, value))


def _op_ratio(e, a):
    kind = a["kind"]
    parameters = {key: value for key, value in a.items() if key != "kind"}
    value = e.ratio(kind, **parameters)
    return _payload(_format_value(e, value, approximate=True), value=value)


# ---------------------------------------------------------------------------
# Unit conversion
# ---------------------------------------------------------------------------
def _op_convert(e, a):
    value = e.convert(a["name"], a["value"])
    return _payload(_format_value(e, value, approximate=True), value=value)


def _op_conversions(e, a):
    from scientific_calculator.engine.conversions import CONVERSIONS

    return _payload("", conversions=list(CONVERSIONS))


# ---------------------------------------------------------------------------
# Spreadsheet
# ---------------------------------------------------------------------------
def _op_sheet_set(e, a):
    _get_sheet().set(a["address"], a["text"])
    return _sheet_snapshot(e)


def _op_sheet_delete(e, a):
    _get_sheet().delete(a["address"])
    return _sheet_snapshot(e)


def _op_sheet_clear(e, a):
    _get_sheet().delete_all()
    return _sheet_snapshot(e)


def _op_sheet_snapshot(e, a):
    return _sheet_snapshot(e)


# ---------------------------------------------------------------------------
# Faithful desktop UI (real app.py driven headlessly through headless_app)
# ---------------------------------------------------------------------------
def _ui():
    import headless_app

    return headless_app


def _op_ui_start(e, a):
    headless = _ui()
    headless.configure(_data_dir or os.environ.get("HOME") or os.getcwd())
    headless.start()
    headless.power_on()
    return _payload("ok", snapshot=headless.snapshot())


def _op_ui_snapshot(e, a):
    return _payload("", snapshot=_ui().snapshot())


def _op_ui_press(e, a):
    headless = _ui()
    key = a["key"]
    if key == "MENU":
        return {"text": "", "snapshot": headless.press(key)}
    return _payload("", snapshot=headless.press(key, a.get("value")))


def _op_ui_menu_select(e, a):
    headless = _ui()
    path = a.get("path")
    index = a.get("index")
    return _payload("", snapshot=headless.menu_select(index=index, path=path))


def _op_ui_dialog_answer(e, a):
    headless = _ui()
    return _payload("", snapshot=headless.answer(a.get("value")))


def _op_ui_dialog_invoke(e, a):
    headless = _ui()
    return _payload("", snapshot=headless.invoke_dialog(
        int(a["dialog"]), int(a["widget"]), a.get("action", "command"), a.get("value"),
    ))


def _op_ui_dialog_dismiss(e, a):
    return _payload("", snapshot=_ui().dismiss_info())


def _op_ui_dialog_close_all(e, a):
    return _payload("", snapshot=_ui().close_dialogs())


def _op_ui_set_angle(e, a):
    headless = _ui()
    application = headless._require()
    application.set_angle(a["unit"])
    return _payload("", snapshot=headless.snapshot())


def _op_ui_set_skin(e, a):
    headless = _ui()
    application = headless._require()
    skin = a["skin"]
    if skin not in application.SKINS:
        raise CalculatorError(f"Argument ERROR: unknown skin {skin}")
    application.skin_name = skin
    try:
        application.save_settings_file(False)
    except Exception:  # noqa: BLE001 - persistence must not break a UI change
        pass
    return _payload("", snapshot=headless.snapshot())


def _op_ui_clear(e, a):
    headless = _ui()
    application = headless._require()
    application.ac_key()
    application.core.history.clear()
    return _payload("", snapshot=headless.snapshot())


def _sheet_snapshot(e) -> dict[str, object]:
    sheet = _get_sheet()
    values: dict[str, str] = {}
    for address in sheet.cells:
        try:
            values[address] = _format_value(e, sheet.value(address), approximate=True)
        except CalculatorError as exc:
            values[address] = translate_error_message(exc)[:120]
        except Exception:  # noqa: BLE001
            values[address] = "ERROR"
    return _payload("", cells=dict(sheet.cells), values=values,
                    memory_used=sheet.memory_used(), free_space=sheet.free_space())


_OP_TABLE: dict[str, Callable[[ScientificCalculatorEngine, dict[str, Any]], dict[str, object]]] = {
    # core
    "ping": _op_ping,
    "configure": _op_configure,
    "get_settings": _op_get_settings,
    "set_settings": _op_set_settings,
    "reset_all": _op_reset_all,
    "evaluate": _op_evaluate,
    "approx": _op_approx,
    "evaluate_with_values": _op_evaluate_with_values,
    "summation": _op_summation,
    "memory_store": _op_memory_store,
    "memory_recall": _op_memory_recall,
    "memory_add": _op_memory_add,
    "memory_sub": _op_memory_sub,
    "history": _op_history,
    "history_clear": _op_history_clear,
    "history_recall": _op_history_recall,
    "prime_factorization": _op_prime_factorization,
    "random_number": _op_random_number,
    "random_int": _op_random_int,
    "dms_to_decimal": _op_dms_to_decimal,
    "decimal_to_dms": _op_decimal_to_dms,
    "pol": _op_pol,
    "rec": _op_rec,
    "table": _op_table,
    # calculus
    "derivative": _op_derivative,
    "derivative_at": _op_derivative_at,
    "integral": _op_integral,
    "integral_definite": _op_integral_definite,
    "integral_double": _op_integral_double,
    "integral_triple": _op_integral_triple,
    "solve": _op_solve,
    "ode": _op_ode,
    # complex
    "complex_eval": _op_complex_eval,
    "complex_argument": _op_complex_argument,
    "to_polar": _op_to_polar,
    "from_polar": _op_from_polar,
    "complex_derivative": _op_complex_derivative,
    "complex_limit": _op_complex_limit,
    "complex_integral": _op_complex_integral,
    # base-n
    "base_eval": _op_base_eval,
    "base_format": _op_base_format,
    "base_op": _op_base_op,
    "base_parse": _op_base_parse,
    # matrix / vector
    "matrix_define": _op_matrix_define,
    "matrix_op": _op_matrix_op,
    "matrix_identity": _op_matrix_identity,
    "matrix_get": _op_matrix_get,
    "matrix_clear": _op_matrix_clear,
    "vector_define": _op_vector_define,
    "vector_op": _op_vector_op,
    "vector_get": _op_vector_get,
    "vector_clear": _op_vector_clear,
    # statistics / distributions
    "one_var_stats": _op_one_var_stats,
    "regression": _op_regression,
    "normal_p": _op_normal_p,
    "normal_q": _op_normal_q,
    "normal_r": _op_normal_r,
    "distribution": _op_distribution,
    # equations
    "polynomial_roots": _op_polynomial_roots,
    "simultaneous": _op_simultaneous,
    "inequality": _op_inequality,
    "ratio": _op_ratio,
    # conversions
    "convert": _op_convert,
    "conversions": _op_conversions,
    # spreadsheet
    "sheet_set": _op_sheet_set,
    "sheet_delete": _op_sheet_delete,
    "sheet_clear": _op_sheet_clear,
    "sheet_snapshot": _op_sheet_snapshot,
    # faithful desktop UI
    "ui_start": _op_ui_start,
    "ui_snapshot": _op_ui_snapshot,
    "ui_press": _op_ui_press,
    "ui_menu_select": _op_ui_menu_select,
    "ui_dialog_answer": _op_ui_dialog_answer,
    "ui_dialog_invoke": _op_ui_dialog_invoke,
    "ui_dialog_dismiss": _op_ui_dialog_dismiss,
    "ui_dialog_close_all": _op_ui_dialog_close_all,
    "ui_set_angle": _op_ui_set_angle,
    "ui_set_skin": _op_ui_set_skin,
    "ui_clear": _op_ui_clear,
}

# Public alias kept for tests and for Kotlin-visible introspection.
_OPS = _OP_TABLE


def call(op: str, args_json: str = "{}") -> str:
    """Run one allow-listed operation and return a JSON string (never raises)."""
    global _current_tid
    if not isinstance(op, str):
        return json.dumps({"ok": False, "error": "Argument ERROR: operation must be text"})
    handler = _OP_TABLE.get(op)
    if handler is None:
        return json.dumps({"ok": False, "error": f"Argument ERROR: unknown operation {op}"})
    try:
        args = json.loads(args_json) if args_json else {}
        if not isinstance(args, dict):
            raise CalculatorError("Argument ERROR: arguments must be an object")
        with _lock:
            with _state_lock:
                _current_tid = threading.get_ident()
            try:
                engine = _get_engine()
                payload = handler(engine, args)
            finally:
                while True:  # a late cancel() may still fire here; retry the cleanup
                    try:
                        with _state_lock:
                            _current_tid = None
                        break
                    except _Cancelled:
                        continue
            if op not in _READ_ONLY_OPS:
                _persist()
            return json.dumps({"ok": True, "history": _history(engine), **payload})
    except _Cancelled:
        return json.dumps({"ok": False, "error": "Calculation cancelled"})
    except CalculatorError as exc:
        return json.dumps({"ok": False, "error": translate_error_message(exc)[:500]})
    except Exception as exc:  # unexpected: report, never crash the app process
        return json.dumps({"ok": False, "error": f"Internal ERROR: {type(exc).__name__}"})


def cancel() -> bool:
    """Ask the running call() to stop. Safe from any thread; True if a call was interrupted.

    Works at Python bytecode boundaries, which covers SymPy (pure Python). A long
    uninterrupted native SciPy routine stops only when it returns to Python.
    """
    with _state_lock:
        tid = _current_tid
        if tid is None:
            return False
        return ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_ulong(tid), ctypes.py_object(_Cancelled)) == 1


def reset() -> None:
    """Drop engine and persistence state (used by tests and by 'Reset to defaults')."""
    global _engine, _sheet, _store, _data_dir
    with _lock:
        _engine = None
        _sheet = None
        _store = None
        _data_dir = None
