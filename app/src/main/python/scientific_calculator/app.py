from __future__ import annotations

import copy
import logging
import math
import multiprocessing
import os
import re
import sys
import tkinter as tk
import tkinter.font as tkfont
from contextlib import suppress
from logging.handlers import RotatingFileHandler
from tkinter import messagebox, simpledialog, ttk
from typing import Any, Literal, cast, overload

import numpy as np
from PIL import Image, ImageTk

from . import entry_rules, lcd_fields, lcd_forms
from .application_persistence import ApplicationPersistence
from .calculation_errors import CalculationTimeout
from .constants_data import CONSTANTS_DATASET_LABELS, constants_for_dataset
from .engine.conversions import CONVERSIONS
from .errors import CalculatorError, translate_error_message
from .expression_document import ExpressionDocument
from .fonts import LCD_FAMILIES, MATH_FAMILIES, choose_family, supports_letter_superscripts
from .history import CalculationHistoryEntry
from .lcd_flow_state import LCDFlowState
from .lcd_layout import (
    ResultViewport,
    caret_text_view,
    render_math_text,
    result_viewport,
    scroll_result,
    wrap_label,
)
from .math_template import MathTemplate, NavigationDirection
from .restart_manager import restart_application

# Font families the 480x980 LCD layout was measured against.  Used when a shell
# is built without a Tk initializer and never resolved a platform family.
_DEFAULT_FONT_FAMILY = {"lcd": LCD_FAMILIES[0], "math": MATH_FAMILIES[0]}


class _LazySymPy:
    """Stand in for SymPy until the application first needs a symbol.

    SymPy is 0.6 seconds and thousands of files, all read from cold disk on
    the first launch after a reboot. The user interface itself needs none of
    it, so the import waits until a calculation does.
    """

    def __getattr__(self, name):
        import sympy

        globals()["sp"] = sympy
        return getattr(sympy, name)


sp = _LazySymPy()


_DEFERRED_NAMES = frozenset(
    {
        "ApplicationServices",
        "CalculationController",
        "CalculationSession",
        "ScientificCalculatorEngine",
        "SpreadsheetModel",
    }
)


def __getattr__(name):
    """Import the calculation engine only once the application needs it.

    These modules pull in SymPy, which costs roughly 0.6 seconds and reads
    thousands of files that are still cold after a reboot. Deferring them lets
    the window appear first, and they stay module attributes so tests and
    integrations can patch them by name.

    The imports below are written literally rather than through
    ``importlib``: PyInstaller resolves dependencies statically and cannot
    follow a module name that is only known at run time, so a computed import
    leaves them out of the packaged application entirely.
    """
    if name not in _DEFERRED_NAMES:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    from .application_services import ApplicationServices
    from .calculation_controller import CalculationController
    from .calculation_session import CalculationSession
    from .calculator_engine import ScientificCalculatorEngine
    from .spreadsheet import SpreadsheetModel

    resolved = {
        "ApplicationServices": ApplicationServices,
        "CalculationController": CalculationController,
        "CalculationSession": CalculationSession,
        "ScientificCalculatorEngine": ScientificCalculatorEngine,
        "SpreadsheetModel": SpreadsheetModel,
    }
    globals().update(resolved)
    return resolved[name]


def _lazy(name):
    """Return a deferred import, preferring an attribute a test has patched."""
    value = globals().get(name)
    return __getattr__(name) if value is None else value
from .settings_codec import SettingsCodec, SettingsPolicy
from .settings_store import SettingsStore
from .spreadsheet_cursor import SpreadsheetCursor
from .template_session import TemplateSession

LOGGER = logging.getLogger("scientific_calculator")


class App(tk.Tk):
    MODES=["Calculate","Complex","Base-N","Matrix","Vector","Statistics","Distribution","Spreadsheet","Table","Equation/Func","Inequality","Ratio"]
    LCD_WORKSPACE_MODES=frozenset({
        "Matrix", "Vector", "Statistics", "Distribution", "Spreadsheet",
        "Table", "Equation/Func", "Inequality", "Ratio",
    })
    MODE_HINTS={
        "Calculate":"Enter expression, then =",
        "Complex":"Enter z, then =",
        "Base-N":"Select base, enter value, =",
        "Matrix":"LCD form: OPTN action, = next",
        "Vector":"LCD form: OPTN action, = next",
        "Statistics":"LCD form: choose analysis, = next",
        "Distribution":"LCD form: choose distribution, = next",
        "Spreadsheet":"LCD cells: arrows move, = save",
        "Table":"LCD form: f(x), range, then =",
        "Equation/Func":"LCD form: choose equation type",
        "Inequality":"LCD form: degree, coefficients, relation",
        "Ratio":"LCD form: choose ratio type",
    }
    ALPHA_MAP={"neg":"A","dms":"B","inv":"C","sin":"D","cos":"E","tan":"F","rparen":"x","sd":"y","mplus":"M","sci":"e"}
    UI_SCALES=(40,50,60,75,100,125,150,200)
    SKINS={
        "Graphite":"skins/skin_graphite.png",
        "Blue":"skins/skin_blue.png",
        "Pink":"skins/skin_pink.png",
        "White":"skins/skin_white.png",
    }
    BOOLEAN_SETTINGS=frozenset({
        "engineer_symbol", "statistics_freq", "spreadsheet_auto_calc",
        "equation_complex", "digit_separator",
    })
    # Physical keyboard input is deliberately narrower than the parser.  A
    # keyboard must not become a hidden second input language: every accepted
    # character maps to a visible calculator key or one of its SHIFT/ALPHA
    # functions.  Functions such as sin() and sqrt() are inserted by their
    # dedicated calculator keys rather than typed letter by letter.
    KEYBOARD_CHARACTER_MAP={
        "*":"×", "-":"−", "+":"+", "/":"/", "^":"^",
        "(":"(", ")":")", ",":",", ".":".", "%":"%", "=":"=",
        "×":"×", "−":"−", "÷":"/", "π":"π",
    }
    KEYBOARD_VARIABLES=frozenset({"A", "B", "C", "D", "E", "F", "M", "d", "t", "u", "v", "x", "y", "z", "e"})
    SETTINGS_DATA_VERSION=3
    SETTINGS_SCHEMA_VERSION=SETTINGS_DATA_VERSION  # compatibility with saved v1/v2 payloads
    SETTINGS_ENUMS={
        "angle_unit":frozenset({"DEG","RAD","GRA"}),
        "input_output":frozenset({"MathI/MathO","MathI/DecimalO","LineI/LineO","LineI/DecimalO"}),
        "number_format":frozenset({"Norm","Fix","Sci"}),
        "complex_format":frozenset({"a+bi","r∠θ"}),
        "spreadsheet_show_cell":frozenset({"Formula","Value"}),
        "decimal_mark":frozenset({"Dot","Comma"}),
        "multiline_font":frozenset({"Normal","Small"}),
        "constant_dataset":frozenset(CONSTANTS_DATASET_LABELS),
    }
    LCD_TEXT_COLOR="#273026"
    LOADING_NOTICE="Loading…"
    INTEGRAL_ACTIONS=(
        ("definite","Integral"), ("double","Double"), ("triple","Triple"),
    )
    COMPLEX_CALCULUS_ACTIONS=(("definite","Integral"),)
    LEGACY_CALCULUS_ACTION_IDS={
        "Definite Integral":"definite", "Complex Definite Integral":"definite",
        "Indefinite Integral":"definite", "Complex Indefinite Integral":"definite",
        "Improper Integral":"definite",
        "Double Integral":"double", "Triple Integral":"triple",
    }
    def __init__(self):
        super().__init__()
        self._initialize_tk_environment()
        self._load_bootstrap_configuration()
        self._configure_root_window()
        # The interface is engine-free, so it is built before the calculation
        # engine is imported.  The user then waits on a real calculator face
        # showing ``Loading…`` on its LCD instead of an empty window.
        self._ui()
        self._show_loading_notice()
        self._build_services()
        self._restore_runtime_state()
        self._initialize_interaction_state()
        self._build_application_controllers()
        self._clear_loading_notice(); self.status_refresh()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _initialize_tk_environment(self):
        try:
            self._tk_pixels_per_point = float(self.tk.call("tk", "scaling"))
        except Exception:
            self._tk_pixels_per_point = 96.0 / 72.0
        self.title("Scientific Calculator")
        self.skin_mode=True

    def _load_bootstrap_configuration(self):
        self.load_settings_file()
        self.ui_scale=self._fit_ui_scale_to_display(self.ui_scale)

    def _configure_root_window(self):
        self.geometry(f"{self._sp(480)}x{self._sp(980)}")
        self.resizable(False,False)
        self.configure(bg="#ffffff")
        self._apply_window_icon()

    def _apply_window_icon(self):
        """Set the taskbar and window icon on every platform.

        ``iconbitmap`` reads a Windows ``.ico`` only on Windows; elsewhere Tk
        expects an X11 bitmap and silently refuses one, which left the app with
        no icon on Linux.  ``iconphoto`` accepts a decoded image everywhere, so
        it is the one that actually has to succeed.  The PhotoImage is kept on
        the instance because Tk holds only a weak reference to it.
        """
        icon_path=self._resource_path("icons/app.ico")
        with suppress(Exception):
            self.iconbitmap(icon_path)
        with suppress(Exception):
            self._window_icon=ImageTk.PhotoImage(Image.open(icon_path))
            # ``ImageTk.PhotoImage`` duck-types Tk's own PhotoImage at runtime;
            # the stub for ``iconphoto`` only recognizes the nominal Tk class.
            self.iconphoto(True,cast("tk.PhotoImage",self._window_icon))

    def _show_loading_notice(self):
        """Report the engine import on the calculator's own LCD.

        Importing the engine reads thousands of SymPy files that are still
        cold after a reboot.  The skin and LCD are already on screen by now,
        so the wait is shown where a calculator would show it.
        """
        with suppress(Exception):
            self.result.config(text=self.LOADING_NOTICE)
            self.update()

    def _clear_loading_notice(self):
        """Return the LCD to its idle reading once the engine is ready."""
        with suppress(Exception):
            if self.result.cget("text")==self.LOADING_NOTICE:
                self.result.config(text="0")

    def _build_services(self):
        services=_lazy("ApplicationServices").build(
            _lazy("ScientificCalculatorEngine"),_lazy("CalculationSession"),_lazy("SpreadsheetModel"))
        self.core=services.engine
        self.calculation_session=services.calculation_session
        self.sheet=services.spreadsheet

    def _require_calculation_session(self):
        """Return the commit boundary, building it for a shell without ``__init__``.

        Headless compatibility tests and embedders may construct an App without
        running its Tk initializer, so ``_build_services`` never assigned a
        session.  Recovering it here keeps that supported path beside the rest
        of service construction and leaves the calculation callbacks with a
        single, unconditional commit boundary.
        """
        session=self.__dict__.get("calculation_session")
        if session is None:
            session=self.calculation_session=_lazy("CalculationSession")(self.core)
        return session

    def _restore_runtime_state(self):
        self.apply_saved_engine_settings()
        self.load_calculation_history()

    def _initialize_interaction_state(self):
        self.mode="Calculate"; self.shift=False; self.alpha=False; self.base=10; self.history_pos=len(self.core.history); self.undo=[]; self.overwrite=False
        self._last_submitted_expression=None
        self._expression_document=ExpressionDocument()
        self._history_documents={}
        self._engineering_exponent=None
        self._pre_equals_recall_available=False
        self._completed_result_text=None
        self._completed_result_offset=0
        self._calculation_busy=False
        self._lcd_flow: dict[str, Any] | None = None
        self._template_session=None
        self.template_kind=None
        self.template_fields: dict[str, object] = {}
        self.template_order=[]; self.template_index=0; self.template_cursors={}; self._template_rendering=False

    def _build_application_controllers(self):
        self.calculation_controller=_lazy("CalculationController")(self)


    def _db_base_path(self):
        """Persistent local SQLite settings database."""
        root = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), ".scientific_calculator")
        # Keep path discovery side-effect free.  ``SettingsStore.load`` owns
        # directory creation and safely falls back to in-memory defaults when
        # a profile directory is unavailable (for example, read-only).
        return os.path.join(root, "ScientificCalculator", "settings.db")

    @staticmethod
    def _platform_default_ui_scale():
        """Return the reference scale for every new installation.

        macOS may still choose a smaller *effective* scale when its usable
        client area cannot fit the 100% skin. A saved user's preference is
        never rewritten merely because a display is small.
        """
        return 100

    @classmethod
    def _settings_codec(cls):
        return SettingsCodec(
            SettingsPolicy(
                data_version=cls.SETTINGS_DATA_VERSION,
                ui_scales=frozenset(cls.UI_SCALES),
                skins=frozenset(cls.SKINS),
                boolean_settings=cls.BOOLEAN_SETTINGS,
                enums=cls.SETTINGS_ENUMS,
            )
        )

    @classmethod
    def _default_saved_config(cls):
        return cls._settings_codec().default_config(cls._platform_default_ui_scale())

    def _log_settings_issue(self, operation, error):
        """Record only an operation and error class; never persist setting values."""
        try:
            log_path=os.path.join(os.path.dirname(self._db_base_path()),"settings.log")
            logger=logging.getLogger("scientific_calculator.settings")
            logger.setLevel(logging.WARNING)
            if not any(getattr(handler,"baseFilename",None)==os.path.abspath(log_path) for handler in logger.handlers):
                handler=RotatingFileHandler(log_path,maxBytes=64*1024,backupCount=1,encoding="utf-8")
                handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
                logger.addHandler(handler)
            logger.warning("settings_%s_failed error=%s",operation,type(error).__name__)
        except Exception:
            # The calculator must still start when a disk/permission problem
            # prevents diagnostic logging.
            pass

    @classmethod
    def _sanitize_calculator_settings(cls, saved):
        return cls._settings_codec().sanitize_calculator_settings(saved)

    @classmethod
    def _sanitize_saved_config(cls, saved):
        return cls._settings_codec().sanitize_saved_config(
            saved, default_scale=cls._platform_default_ui_scale()
        )

    @classmethod
    def _migrate_settings(cls, saved):
        return cls._settings_codec().migrate(saved)

    def _settings_store(self):
        return SettingsStore(self._db_base_path(), self._log_settings_issue)

    def _persistence_service(self):
        return ApplicationPersistence(self._settings_store, history_limit=SettingsStore.HISTORY_LIMIT)

    @staticmethod
    def _flatten_settings(data):
        return App._settings_codec().flatten(data)

    @staticmethod
    def _unflatten_settings(data):
        return App._settings_codec().unflatten(data)

    def load_settings_file(self):
        saved = self._persistence_service().load_settings()
        cfg=self._sanitize_saved_config(self._migrate_settings(self._unflatten_settings(saved)))
        self.saved_config = cfg
        self.requested_ui_scale = self._validated_ui_scale(cfg.get("scale",100))
        self.ui_scale = self.requested_ui_scale
        self.skin_name = self._validated_skin_name(cfg.get("skin","Graphite"))

    @classmethod
    def _validated_ui_scale(cls, value):
        return cls._settings_codec().validated_ui_scale(value)

    @classmethod
    def _validated_skin_name(cls, value):
        """Return a bundled skin name, falling back safely for old/corrupt settings."""
        return cls._settings_codec().validated_skin_name(value)

    def apply_saved_engine_settings(self):
        saved=self._sanitize_calculator_settings(getattr(self,"saved_config",{}).get("calculator_settings",{}))
        for k,v in saved.items():
            if hasattr(self.core.settings,k):
                setattr(self.core.settings,k,v)

    def _history_entries(self):
        return self._persistence_service().normalize_history(getattr(self.core,"history",[]))

    def load_calculation_history(self):
        try:
            entries=self._persistence_service().load_history()
            # A failed database read is represented by ``None``.  Do not make
            # a populated in-memory history look deleted while the store is
            # temporarily unavailable.
            if entries is not None:
                self.core.history[:]=entries
        except Exception as error:
            self._log_settings_issue("load history",error)

    def _persist_calculation_history(self, store=None):
        entries=self._history_entries()
        self.core.history[:]=entries
        if store is None:
            self._persistence_service().save_history(entries)
        else:
            store.save_history(entries)
        # Keep recall positioned *after* the newest entry.  This makes the
        # next ▲ deterministic, whether a calculation has just completed or
        # the user has just cleared the screen with AC.
        self.history_pos=len(entries)
        return entries

    def _lcd_message(self, message):
        """Show a short status on the calculator itself when it is available."""
        with suppress(AttributeError, RecursionError, tk.TclError):
            self._set_lcd_label(message)

    @classmethod
    def _coerce_boolean_setting(cls, name, value):
        """Normalize Setup/persisted On/Off values without truthy string leakage."""
        return cls._settings_codec().coerce_boolean(name, value)

    def save_settings_file(self, notify=False):
        data = {
            "schema_version": self.SETTINGS_DATA_VERSION,
            "scale": self._validated_ui_scale(self.__dict__.get("requested_ui_scale",self.__dict__.get("ui_scale",100))),
            "skin": self._validated_skin_name(getattr(self,"skin_name","Graphite")),
            "calculator_settings": self._sanitize_calculator_settings(dict(vars(self.core.settings))) if hasattr(self,"core") else {}
        }
        try:
            history=self._history_entries()
            self.core.history[:]=history
            self._persistence_service().save_state(self._flatten_settings(data), history)
            self.saved_config = data
            if notify:
                self._lcd_message("Settings saved")
            return True
        except Exception as e:
            self._log_settings_issue("save",e)
            if notify:
                self.err(CalculatorError("Settings ERROR: save failed"), clear_input=False)
            return False

    def _rebuild_scaled_ui(self):
        expression = ""
        result_text = "0"
        completed_text = self.__dict__.get("_completed_result_text")
        completed_offset = self.__dict__.get("_completed_result_offset",0)
        cursor = 0
        try:
            expression = self.expr.get()
            result_text = self.result.cget("text")
            cursor = self.expr.index(tk.INSERT)
        except (AttributeError, tk.TclError):
            pass
        template_active = bool(getattr(self,"template_kind",None))
        for child in self.winfo_children():
            # Auxiliary mode windows retain their work when the calculator skin
            # is rebuilt for a new UI scale.  Only root UI widgets belong to
            # the scaled canvas and should be recreated here.
            if not isinstance(child,tk.Toplevel):
                child.destroy()
        # Windows keeps a non-resizable Tk window at its previous dimensions.
        # Temporarily unlock it so every supported scale gets its own geometry.
        self.resizable(True,True)
        try:
            self.geometry(f"{self._sp(480)}x{self._sp(980)}")
            self._ui()
            if template_active:
                self.result.config(text=result_text)
                self.render_template()
            else:
                self.set_expr(expression)
                if completed_text is not None:
                    self._completed_result_text=completed_text
                    self._completed_result_offset=completed_offset
                    self._show_completed_result(completed_text,reset=False)
                else:
                    self.result.config(text=result_text)
                self.expr.icursor(max(0,min(len(expression),cursor)))
            self.status_refresh()
        finally:
            self.resizable(False,False)

    def apply_scale(self, percent):
        self.requested_ui_scale = self._validated_ui_scale(percent)
        self.ui_scale = self._fit_ui_scale_to_display(self.requested_ui_scale)
        self.save_settings_file(False)
        self._rebuild_scaled_ui()

    def reset_app_settings(self):
        try:
            self._persistence_service().reset_defaults()
        except Exception as error:
            self._log_settings_issue("reset", error)
            self.err(CalculatorError("Settings ERROR: reset failed"), clear_input=False)
            return False
        self.requested_ui_scale = self._platform_default_ui_scale()
        self.ui_scale = self._fit_ui_scale_to_display(self.requested_ui_scale)
        self.skin_name = "Graphite"
        try:
            self.core.settings = type(self.core.settings)()
            self.core.history.clear()
            self.history_pos=0
        except Exception:
            pass
        self.saved_config = self._default_saved_config()
        self._rebuild_scaled_ui()
        self._lcd_message("Settings reset")
        return True

    def clear_calculation_history(self):
        """Remove only calculation history and persist the change atomically."""
        previous_history=list(self.core.history)
        previous_position=getattr(self,"history_pos",0)
        self.core.history.clear()
        self.history_pos=0
        if self.save_settings_file(False):
            self._lcd_message("History cleared")
            return True
        self.core.history[:]=previous_history
        self.history_pos=previous_position
        self.err(CalculatorError("Settings ERROR: history clear failed"), clear_input=False)
        return False

    def _run_background_calculation(self, method, args, on_success):
        """Run an engine method in a cancellable isolated process.

        The worker receives a snapshot. Its Ans/history/memory changes are
        committed only by this Tk-thread callback, after its operation id has
        been confirmed by the controller.
        """
        def start():
            self._calculation_busy=True
            self._set_lcd_label("Calculating…")

        def success(payload):
            self._require_calculation_session().apply_success(payload)
            on_success(payload.result)
            try:
                self._persist_calculation_history()
            except Exception as error:
                self._log_settings_issue("save history",error)

        def failure(error): self.err(error)
        def finish(): self._calculation_busy=False
        try:
            return self.calculation_controller.start_engine_method(
                self.core, method, *args, on_start=start, on_success=success,
                on_error=failure, on_finish=finish,
            )
        except Exception as error:
            self.err(error)
            return False

    def _on_close(self):
        # Persist the current Setup state even if the user closes the app later.
        try:
            controller = self.__dict__.get("calculation_controller")
            if controller: controller.close()
            self.save_settings_file(False)
        finally:
            self.destroy()

    def _resource_path(self,name):
        frozen_base=getattr(sys,"_MEIPASS",None)
        if frozen_base:
            return os.path.join(frozen_base,name)
        here=os.path.dirname(os.path.abspath(__file__))
        project_asset=os.path.abspath(os.path.join(here,"..","..","assets",name))
        if os.path.exists(project_asset):
            return project_asset
        return os.path.join(here,name)

    def _skin_xy(self,x,y):
        # Original generated-image coordinates -> current scaled skin coordinates.
        base_x=(float(x)-330.0)*0.8
        base_y=(float(y)-5.0)*0.8
        return (int(round(base_x*self._scale_factor())),
                int(round(base_y*self._scale_factor())))


    def _scale_factor(self):
        return self.ui_scale / 100.0

    def _fit_ui_scale_to_display(self, requested_scale):
        """Keep the complete fixed-size calculator visible on every platform.

        The selected scale is retained separately as ``requested_ui_scale``;
        this helper only chooses an effective scale that fits the current work
        area.  Moving to a larger display can therefore restore the user's
        preferred scale without deleting a supported scale option.
        """
        requested_scale=self._validated_ui_scale(requested_scale)
        try:
            horizontal_margin=24 if sys.platform=="darwin" else 16
            vertical_margin=96 if sys.platform=="darwin" else 80
            available_width=max(1,self.winfo_screenwidth()-horizontal_margin)
            available_height=max(1,self.winfo_screenheight()-vertical_margin)
            maximum=int(math.floor(100*min(available_width/480,available_height/980)))
        except (AttributeError, RecursionError, tk.TclError, TypeError, ValueError):
            return requested_scale
        choices=[scale for scale in self.UI_SCALES if scale<=maximum]
        return min(requested_scale,max(choices,default=self.UI_SCALES[0]))

    def _schedule_skin_geometry_validation(self):
        """Validate the macOS client area after Tk has completed layout.

        Display-size estimates are necessary before the window exists, but a
        Retina or externally scaled display can still return a smaller actual
        client canvas. This deferred, bounded check handles that discrepancy
        without changing the user's saved requested scale.
        """
        if sys.platform!="darwin" or self.__dict__.get("_skin_geometry_validation_scheduled",False):
            return
        try:
            self._skin_geometry_validation_scheduled=True
            self.after_idle(self._verify_skin_geometry)
        except (AttributeError, RecursionError, tk.TclError):
            self._skin_geometry_validation_scheduled=False

    def _verify_skin_geometry(self):
        """Reduce only the effective scale when a completed macOS layout clips."""
        self._skin_geometry_validation_scheduled=False
        if sys.platform!="darwin":
            return False
        try:
            self.update_idletasks()
            expected_width,expected_height=self._sp(480),self._sp(980)
            actual_width,actual_height=self.winfo_width(),self.winfo_height()
            canvas_width,canvas_height=self.skin_canvas.winfo_width(),self.skin_canvas.winfo_height()
        except (AttributeError, RecursionError, tk.TclError, TypeError, ValueError):
            return False
        # A newly mapped window can report one logical pixel before the
        # window server responds. Retry once; never infer clipping from that
        # transient state or create an endless callback chain.
        if min(actual_width,actual_height,canvas_width,canvas_height)<=1:
            retries=self.__dict__.get("_skin_geometry_retry_count",0)
            if retries<1:
                try:
                    self._skin_geometry_retry_count=retries+1
                    self._skin_geometry_validation_scheduled=True
                    self.after(50,self._verify_skin_geometry)
                except (AttributeError, RecursionError, tk.TclError):
                    self._skin_geometry_validation_scheduled=False
            return False
        self._skin_geometry_retry_count=0
        if actual_width>=expected_width and actual_height>=expected_height and canvas_width>=expected_width and canvas_height>=expected_height:
            return False
        current=self._validated_ui_scale(getattr(self,"ui_scale",100))
        tried=self.__dict__.setdefault("_skin_geometry_checked_scales",set())
        tried.add(current)
        choices=[scale for scale in self.UI_SCALES if scale<current and scale not in tried]
        if not choices:
            return False
        self.ui_scale=max(choices)
        self._rebuild_scaled_ui()
        return True

    def _sp(self,v):
        """Scale a 100%-reference pixel coordinate with consistent rounding."""
        return max(0,int(round(float(v) * self._scale_factor())))

    def _fp(self,base_points):
        """Return a negative Tk font size (pixels), preserving the 100% look exactly."""
        px_at_100 = float(base_points) * self._tk_pixels_per_point
        px = max(1,int(round(px_at_100 * self._scale_factor())))
        return -px

    def _fs(self,v):
        """Legacy point-size helper for non-LCD UI only."""
        return max(1,int(round(float(v) * self._scale_factor())))

    def _resolve_font_families(self):
        """Pick the best installed family for each LCD role.

        ``Consolas`` and ``Cambria Math`` are the Windows design reference but
        are absent on macOS and Linux, where Tk would otherwise substitute an
        arbitrary family and shift the measured LCD geometry.  A substituted
        family can also lack the patchy superscript letters, so the display
        only uses those when the resolved family is known to carry them.
        """
        try:
            installed=tkfont.families(self)
        except (AttributeError, tk.TclError):
            installed=()
        lcd=choose_family(installed,LCD_FAMILIES)
        self._font_family={"lcd":lcd,"math":choose_family(installed,MATH_FAMILIES,fallback=lcd)}
        self._superscript_letters=supports_letter_superscripts(lcd)

    def _font(self,role,base_points,*styles):
        """Return a Tk font tuple for an LCD role, sized exactly as ``_fp`` did.

        Shells built without ``__init__`` never resolved a platform family, so
        they fall back to the Windows design reference the layout was written
        against instead of failing.
        """
        families=self.__dict__.get("_font_family") or _DEFAULT_FONT_FAMILY
        return (families[role],self._fp(base_points),*styles)

    @staticmethod
    def _table_row_count(start, end, step, two_functions=False):
        return entry_rules.table_row_count(start, end, step, two_functions)


    def _add_hotspot(self,name,box,cmd):
        x1,y1=self._skin_xy(box[0],box[1]); x2,y2=self._skin_xy(box[2],box[3])
        self.skin_hotspots.append((name,x1,y1,x2,y2,cmd))

    def _skin_click(self,event):
        for name,x1,y1,x2,y2,cmd in reversed(self.skin_hotspots):
            if x1 <= event.x <= x2 and y1 <= event.y <= y2:
                if self.__dict__.get("_calculation_busy",False) and name != "AC":
                    return "break"
                cmd()
                return "break"

    def _refresh_modifier_status(self):
        """Show modifier state as colored LCD text only."""
        try:
            self.shift_status.config(text="SHIFT" if self.shift else "")
            self.alpha_status.config(text="ALPHA" if self.alpha else "")
        except (AttributeError, tk.TclError):
            pass

    def _ui(self):
        # Resolve the LCD typefaces before any widget measures its font.
        self._resolve_font_families()
        # The selected calculator skin is the visual layout reference.
        self.skin_canvas=tk.Canvas(self,width=self._sp(480),height=self._sp(980),bg="#ffffff",
                                   highlightthickness=0,bd=0)
        self.skin_canvas.pack(fill="both",expand=False)
        skin_file=self.SKINS[self._validated_skin_name(getattr(self,"skin_name","Graphite"))]
        base_skin=Image.open(self._resource_path(skin_file))
        target_size=(self._sp(480),self._sp(980))
        if base_skin.size != target_size:
            base_skin=base_skin.resize(target_size,Image.Resampling.LANCZOS)
        # Do not depend on an implicit Tk default root in frozen builds.
        self._skin_img=ImageTk.PhotoImage(base_skin,master=self.skin_canvas)
        self.skin_canvas.create_image(0,0,image=self._skin_img,anchor="nw")

        # Dynamic LCD overlay: cover the static spreadsheet screenshot only inside screen.
        sx1,sy1=self._sp(40),self._sp(128)
        sx2,sy2=self._sp(435),self._sp(289)
        self.skin_canvas.create_rectangle(sx1,sy1,sx2,sy2,fill="#eaf0e5",outline="#111111",width=max(1,self._sp(1)))

        status_x=sx1+self._sp(7); status_y=sy1+self._sp(7)
        status_width=(sx2-sx1)-self._sp(14)
        modifier_width=self._sp(105)
        self.status=tk.Label(self.skin_canvas,text="",font=self._font("lcd",9,"bold"),
                             anchor="w",bg="#eaf0e5",fg="#273026")
        self.status.place(x=status_x,y=status_y,width=max(0,status_width-modifier_width),height=self._sp(20))
        self.shift_status=tk.Label(self.skin_canvas,text="",font=self._font("lcd",9,"bold"),
                                   anchor="e",bg="#eaf0e5",fg=self.LCD_TEXT_COLOR)
        self.shift_status.place(x=status_x+status_width-self._sp(105),y=status_y,
                                width=self._sp(49),height=self._sp(20))
        self.alpha_status=tk.Label(self.skin_canvas,text="",font=self._font("lcd",9,"bold"),
                                   anchor="e",bg="#eaf0e5",fg=self.LCD_TEXT_COLOR)
        self.alpha_status.place(x=status_x+status_width-self._sp(54),y=status_y,
                                width=self._sp(54),height=self._sp(20))

        self.expr=tk.Entry(self.skin_canvas,font=self._font("lcd",19),justify="right",
                           bg="#f0f4ed",fg="#111111",insertbackground="#111111",
                           insertwidth=max(1,self._sp(2)),relief="flat",bd=0)
        self.expr.place(x=sx1+self._sp(7),y=sy1+self._sp(34),width=(sx2-sx1)-self._sp(14),height=self._sp(51))

        self.template_canvas=tk.Canvas(self.skin_canvas,bg="#f0f4ed",
                                       highlightthickness=0,bd=0)
        self.template_canvas.bind("<KeyPress>",self._template_keypress)

        self.result=tk.Label(self.skin_canvas,text="0",font=self._font("lcd",18,"bold"),
                             anchor="e",bg="#f0f4ed",fg="#111111")
        self.result.place(x=sx1+self._sp(7),y=sy1+self._sp(89),width=(sx2-sx1)-self._sp(14),height=self._sp(58))

        self.expr.bind("<KeyPress>",self._physical_keypress)
        self.expr.bind("<KeyPress>",self._template_keypress,add="+")
        self.expr.bind("<KeyPress>",self._lcd_keypress,add="+")

        self.skin_hotspots=[]

        # Top controls
        self._add_hotspot("SHIFT",(375,430,425,482),self.shift_key)
        self._add_hotspot("ALPHA",(452,430,504,482),self.alpha_key)
        self._add_hotspot("MENU",(742,430,792,482),self.menu_key)
        self._add_hotspot("ON",(820,430,872,482),self.on_key)

        # Direction pad
        self._add_hotspot("UP",(589,429,656,477),lambda:self.vertical_move(-1))
        self._add_hotspot("LEFT",(526,470,586,530),lambda:self.move(-1))
        self._add_hotspot("RIGHT",(659,470,720,530),lambda:self.move(1))
        self._add_hotspot("DOWN",(589,522,656,570),lambda:self.vertical_move(1))

        # Function top row
        self._add_hotspot("OPTN",(363,536,438,585),self.optn_key)
        self._add_hotspot("CALC",(451,536,526,585),self.calc_key)
        self._add_hotspot("INTEGRAL",(720,536,785,585),self.integral_key)
        self._add_hotspot("X",(808,536,873,585),self.x_key)

        # Scientific rows
        self._add_hotspot("FRACTION",(363,610,437,660),self.fraction_key)
        self._add_hotspot("SQRT",(451,610,525,660),self.sqrt_key)
        self._add_hotspot("SQUARE",(540,610,614,660),self.square_key)
        self._add_hotspot("POWER",(628,610,703,660),self.power_key)
        self._add_hotspot("LOG",(716,610,792,660),self.log_key)
        self._add_hotspot("LN",(805,610,879,660),self.ln_key)

        self._add_hotspot("NEG",(363,683,437,733),self.neg_key)
        self._add_hotspot("DMS",(451,683,525,733),self.dms_key)
        self._add_hotspot("INV",(540,683,614,733),self.inv_key)
        self._add_hotspot("SIN",(628,683,703,733),lambda:self.trig_key("sin"))
        self._add_hotspot("COS",(716,683,792,733),lambda:self.trig_key("cos"))
        self._add_hotspot("TAN",(805,683,879,733),lambda:self.trig_key("tan"))

        self._add_hotspot("STO",(363,754,437,807),self.sto_key)
        self._add_hotspot("ENG",(451,754,525,807),self.eng_key)
        self._add_hotspot("LPAREN",(540,754,614,807),self.lparen_key)
        self._add_hotspot("RPAREN",(628,754,703,807),self.rparen_key)
        self._add_hotspot("SD",(716,754,792,807),self.sd_key)
        self._add_hotspot("MPLUS",(805,754,879,807),self.mplus_key)

        # Numeric keypad
        self._add_hotspot("7",(363,832,456,902),lambda:self.num_key("7"))
        self._add_hotspot("8",(468,832,561,902),lambda:self.num_key("8"))
        self._add_hotspot("9",(574,832,667,902),lambda:self.num_key("9"))
        self._add_hotspot("DEL",(680,832,773,902),self.del_key)
        self._add_hotspot("AC",(786,832,879,902),self.ac_key)

        self._add_hotspot("4",(363,918,456,987),lambda:self.num_key("4"))
        self._add_hotspot("5",(468,918,561,987),lambda:self.num_key("5"))
        self._add_hotspot("6",(574,918,667,987),lambda:self.num_key("6"))
        self._add_hotspot("MUL",(680,918,773,987),self.mul_key)
        self._add_hotspot("DIV",(786,918,879,987),self.div_key)

        self._add_hotspot("1",(363,1002,456,1073),lambda:self.num_key("1"))
        self._add_hotspot("2",(468,1002,561,1073),lambda:self.num_key("2"))
        self._add_hotspot("3",(574,1002,667,1073),lambda:self.num_key("3"))
        self._add_hotspot("PLUS",(680,1002,773,1073),self.plus_key)
        self._add_hotspot("MINUS",(786,1002,879,1073),self.minus_key)

        self._add_hotspot("0",(363,1088,456,1158),lambda:self.num_key("0"))
        self._add_hotspot("DOT",(468,1088,561,1158),self.dot_key)
        self._add_hotspot("SCI",(574,1088,667,1158),self.sci_key)
        self._add_hotspot("ANS",(680,1088,773,1158),self.ans_key)
        self._add_hotspot("EQUALS",(786,1088,879,1158),self.equals)

        self.skin_canvas.bind("<Button-1>",self._skin_click)
        self.bind("<F1>",lambda e:self.help_key())
        self.bind("<Escape>",lambda e:self.ac_key())
        self.expr.focus_set()
        self._schedule_skin_geometry_validation()

    def status_refresh(self):
        self.status.config(text=f"{self.mode}  {self.core.settings.angle_unit}  B{self.base}")
        self._refresh_modifier_status()

    @staticmethod
    def _lcd_clip(text,limit=28):
        """Legacy compact-status helper.

        Semantic labels and completed results intentionally do not use this
        helper.  They are rendered by the shared width-aware layout/viewport
        path below so their underlying text is never replaced with an ellipsis.
        """
        text=str(text).replace("\n"," ")
        return text if len(text)<=limit else text[:max(1,limit-1)]+"…"

    @classmethod
    def _history_line(cls, expression, result):
        """Keep the full operation and result for the result viewport."""
        return f"{expression} = {result}"

    def _lcd_content_width(self):
        """Return the usable LCD width without relying on character counts."""
        try:
            width=int(self.result.winfo_width())
            # Tk can report a transient one-pixel width immediately after a
            # scaled UI rebuild. Treat it like the unavailable zero-width
            # state so a completed result is not reduced to one glyph.
            if width>1:
                return width
        except (AttributeError, RecursionError, tk.TclError, TypeError, ValueError):
            pass
        try:
            return max(1,self._sp(381))
        except (AttributeError, RecursionError, tk.TclError, TypeError, ValueError):
            return 381

    def _lcd_measure_text(self, text):
        """Measure with the rendered LCD font, with a deterministic test fallback."""
        try:
            font=tkfont.Font(font=self.result.cget("font"))
            return font.measure(str(text))
        except (AttributeError, RecursionError, RuntimeError, tk.TclError, TypeError, ValueError):
            try:
                return max(1,self._sp(10))*len(str(text))
            except (AttributeError, RecursionError, RuntimeError, tk.TclError, TypeError, ValueError):
                return 10*len(str(text))

    def _set_lcd_label(self, text):
        """Render semantic UI text completely, wrapping by measured pixel width."""
        self._restore_result_style()
        rendered=wrap_label(text,self._lcd_content_width(),self._lcd_measure_text)
        self.result.config(text=rendered,justify="right")

    def _result_viewport(self, text, offset=0) -> ResultViewport:
        return result_viewport(text,offset,self._lcd_content_width(),self._lcd_measure_text)

    def _show_completed_result(self, text, *, reset=True):
        """Display a full completed result through its bounded visual viewport."""
        self._restore_result_style()
        self._completed_result_text=render_math_text(
            text,superscript_letters=self.__dict__.get("_superscript_letters",True)
        )
        if reset:
            self._completed_result_offset=0
        viewport=self._result_viewport(self._completed_result_text,self._completed_result_offset)
        self._completed_result_offset=viewport.offset
        self.result.config(text=viewport.text)
        return viewport

    def _clear_completed_result(self):
        self._completed_result_text=None
        self._completed_result_offset=0

    def _restore_result_style(self):
        """Return the shared LCD result row to its ordinary full-result style."""
        with suppress(AttributeError, RecursionError, tk.TclError):
            self.result.config(font=self._font("lcd",18,"bold"),anchor="e",justify="right")

    def _show_template_error(self, message):
        """Keep template errors in a compact, one-line lower-right LCD row."""
        self._clear_completed_result()
        self._template_error_active=True
        viewport=self._result_viewport(str(message),0)
        with suppress(AttributeError, RecursionError, tk.TclError):
            self.result.config(
                text=viewport.text,font=self._font("lcd",11,"bold"),anchor="e",justify="right",
            )

    def _clear_template_error(self):
        if not self.__dict__.get("_template_error_active",False):
            return
        self._template_error_active=False
        self._restore_result_style()
        with suppress(AttributeError, RecursionError, tk.TclError):
            self.result.config(text="")

    def _scroll_completed_result(self, direction):
        """Pan an overflowing ordinary result; retain arrow ownership at edges."""
        text=self.__dict__.get("_completed_result_text")
        if text is None:
            return False
        current=self._result_viewport(text,self.__dict__.get("_completed_result_offset",0))
        if not (current.can_scroll_left or current.can_scroll_right):
            return False
        viewport=scroll_result(text,current.offset,direction,self._lcd_content_width(),self._lcd_measure_text)
        self._completed_result_offset=viewport.offset
        self.result.config(text=viewport.text)
        return True

    def _reset_history_browsing(self):
        """Use the explicit after-newest sentinel required by Up-arrow recall."""
        try:
            self.history_pos=len(self._history_entries())
        except (AttributeError, TypeError):
            self.history_pos=0

    def _record_submitted_expression(self, expression):
        self._last_submitted_expression=str(expression)
        document=self.__dict__.get("_expression_document")
        if isinstance(document,ExpressionDocument) and document.source==self._last_submitted_expression:
            history_documents=self.__dict__.setdefault("_history_documents",{})
            history_documents[self._last_submitted_expression]=document
            while len(history_documents)>10:
                history_documents.pop(next(iter(history_documents)))
        self._pre_equals_recall_available=bool(self._last_submitted_expression)
        self._reset_history_browsing()

    def _begin_independent_edit(self):
        """Invalidate result-only navigation once the user starts a new edit."""
        # Refer to the implementation directly so this remains safe for the
        # lightweight non-Tk stand-ins used by contract tests.
        App._clear_completed_result(self)
        self._pre_equals_recall_available=False

    @staticmethod
    def _lcd_title(title):
        """Keep flow guidance inside the deliberately compact calculator LCD."""
        first=str(title).split(maxsplit=1)[0].upper()
        return {
            "MATRIX":"MAT", "VECTOR":"VCT", "STATISTICS":"STAT",
            "DISTRIBUTION":"DIST", "SPREADSHEET":"SHEET", "TABLE":"TABLE",
            "EQUATION":"EQN", "INEQUALITY":"INEQ", "RATIO":"RATIO",
            "POLYNOMIAL":"POLY", "SIMULTANEOUS":"SIMUL",
        }.get(first,first[:8])

    def _format_error_message(self,e):
        return translate_error_message(e)

    def _lcd_flow_active(self):
        return self._lcd_state() is not None

    @overload
    def _lcd_state(self, *, create: Literal[True]) -> dict: ...
    @overload
    def _lcd_state(self, *, create: Literal[False] = False) -> dict | None: ...
    def _lcd_state(self, *, create=False):
        """Return the compatibility-safe typed LCD flow mapping.

        Older tests and extension code can still assign a plain dictionary;
        preserve that mapping's identity so external owners can continue to
        update it. Flows created by the application use ``LCDFlowState``.
        """
        raw_flow=self.__dict__.get("_lcd_flow")
        if isinstance(raw_flow,dict) and not isinstance(raw_flow,LCDFlowState):
            return raw_flow
        flow=LCDFlowState.promote(raw_flow)
        if flow is None and create:
            flow=LCDFlowState()
        if flow is not None:
            self._lcd_flow=flow
        return flow

    def _active_flow(self) -> dict:
        """Return the current LCD flow for a handler reached only while one is open.

        Every caller of this method is itself reached only through the LCD's
        own mode dispatch, which already confirmed a flow exists before
        invoking it. This narrows that runtime invariant for the type
        checker once, instead of repeating a redundant ``is None`` guard with
        no real branch to take at each of its call sites.
        """
        flow = self._lcd_state()
        assert flow is not None
        return flow

    def _history_lcd_active(self):
        return lcd_forms.is_history(self._lcd_state())

    def _reset_lcd_flow(self):
        self._lcd_flow=None

    def _set_lcd_expression(self,text):
        self.expr.delete(0,tk.END)
        self.expr.insert(0,str(text))
        self.expr.icursor(tk.END)

    def _entry_vertical_key(self,direction):
        """Route keyboard ▲/▼ through the same context-sensitive LCD controls."""
        self.vertical_move(direction)
        return "break"

    def _entry_horizontal_key(self,direction):
        """Only consume ◀/▶ when an LCD flow assigns them a navigation meaning."""
        if self._lcd_move(direction):
            return "break"
        return None

    def _lcd_prepare_direct_entry(self):
        """Replace a newly rendered field default on the first calculator-key press."""
        flow=self._lcd_state()
        if not flow or flow.get("phase")!="form" or not flow.get("field_armed",False):
            return
        flow["field_armed"]=False
        self.expr.delete(0,tk.END)
        with suppress(tk.TclError):
            self.expr.selection_clear()

    @staticmethod
    def _lcd_matrix_row_tokens(text):
        return lcd_fields.matrix_row_tokens(text)

    def _lcd_matrix_row_allows_insert(self,token):
        """Reject a new matrix-row value once the row already has all columns."""
        flow=self._lcd_state()
        spec=self._lcd_current_spec()
        if not flow or spec is None or spec.get("type")!="matrix_row":
            return True
        try:
            text=self.expr.get()
            cursor=self.expr.index(tk.INSERT)
            insert_text=str(token)
            candidate=text[:cursor]+insert_text+text[cursor:]
            values=self._lcd_matrix_row_tokens(candidate)
            columns=int(spec["columns"])
            if len(values)>columns:
                return False
            # Do not leave a stray separator after a full row: it would only
            # begin a cell that cannot receive another value.
            before=text[:cursor].rstrip()
            starts_new_cell=(
                len(values)>=columns
                and insert_text in {" ","\t",",",";","+","-","−"}
                and bool(before)
                and before[-1] not in ",;+-−"
                and not (insert_text in {"+","-","−"} and before[-1] in "eE")
            )
            return not starts_new_cell
        except (AttributeError, ValueError, tk.TclError):
            return True

    def _lcd_error(self,e):
        flow=self._lcd_state()
        if flow is None:
            self.err(e)
            return
        flow["last_error"]=self._format_error_message(e)
        self._clear_active_input_for_error()
        self._clear_modifiers()
        self._set_lcd_label("ERROR: "+flow["last_error"])

    def _lcd_real(self,text,label="value",integer=False,minimum=None,maximum=None):
        return lcd_fields.parse_real(self.core,text,label,integer,minimum,maximum)

    @staticmethod
    def _lcd_real_expression(parsed,label="value"):
        return lcd_fields.real_expression(parsed,label)

    def _lcd_numbers(self,text,label):
        return lcd_fields.parse_numbers(self.core,text,label)

    def _lcd_function(self,text,label="function"):
        return lcd_fields.parse_function(self.core,text,label)

    def _lcd_parse_field(self,spec,raw):
        return lcd_fields.parse_field(self.core,spec,raw)

    @staticmethod
    def _lcd_number_text(value):
        return lcd_fields.number_text(value)

    def _lcd_result_number_text(self, value):
        """Render optional/non-finite statistical values without crashing the LCD."""
        if value is None:
            return "n/a"
        try:
            if not math.isfinite(float(value)):
                return "n/a"
        except (TypeError, ValueError, OverflowError):
            return "n/a"
        return self._lcd_number_text(value)

    def _lcd_field_text(self,flow,spec):
        return lcd_fields.field_text(flow,spec)

    def _lcd_current_spec(self):
        return lcd_forms.current_spec(self._lcd_state())

    def _lcd_begin_form(self,title,fields,stage):
        flow=self._lcd_state(create=True)
        self._clear_completed_result()
        self._pre_equals_recall_available=False
        field_list=list(fields)
        flow.update({
            "phase":"form", "title":title, "fields":field_list, "stage":stage,
            "index":0, "draft":{}, "result_lines":[], "result_index":0,
            "field_armed":False, "template":MathTemplate.linear(field["key"] for field in field_list),
        })
        self._lcd_render_field()

    def _lcd_render_field(self):
        flow=self._lcd_state()
        spec=self._lcd_current_spec()
        if not flow or spec is None:
            return
        template=flow.get("template")
        if isinstance(template,MathTemplate):
            template.active_slot=spec["key"]
        raw_value=self._lcd_field_text(flow,spec)
        selected_text=""
        if spec.get("type")=="choice":
            try:
                selected=self._lcd_parse_field(spec,raw_value)
                selected_text=spec.get("choice_labels",{}).get(selected,str(selected))
            except Exception:
                selected_text="choose"
            # Choice navigation is a menu, not editable calculator input.
            # Keep the entry blank so its caret never selects or overwrites
            # a visible option code such as 1/2/3 while ◀/▶ is used.
            self._set_lcd_expression("")
        else:
            self._set_lcd_expression(raw_value)
        # Fresh defaults should be replaceable with one keypad press.  Native
        # keyboard input replaces the selection; ``insert`` handles skin keys.
        flow["field_armed"]=spec.get("type")!="choice"
        if spec.get("type")!="choice":
            self.expr.selection_range(0,tk.END)
        title=self._lcd_title(flow["title"])
        if spec.get("type")=="choice":
            prompt=f"{title} {selected_text}  ◀▶  ="
        else:
            prompt=f"{title} {spec.get('label',spec['key'])}  ="
        self._set_lcd_label(prompt)
        self.expr.focus_set()

    def _lcd_capture_draft(self):
        flow=self._lcd_state()
        spec=self._lcd_current_spec()
        if flow and spec is not None:
            value=self.expr.get()
            if spec.get("type")=="choice" and not value.strip():
                selected=self._lcd_parse_field(spec,self._lcd_field_text(flow,spec))
                value=next(
                    str(code) for code,choice in spec["choices"].items() if choice==selected
                )
            flow.setdefault("draft",{})[spec["key"]]=value
            template=flow.get("template")
            if isinstance(template,MathTemplate):
                template.active_slot=spec["key"]
                template.set_active_value(value)

    def _lcd_show_results(self,title,lines):
        flow=self._active_flow()
        self._clear_completed_result()
        flow.update({
            "phase":"results", "title":title, "result_lines":[str(line) for line in lines] or ["0"],
            "result_index":0, "result_offset":0,
        })
        self._lcd_render_result()

    def _lcd_render_result(self):
        flow=self._lcd_state()
        if not flow or flow.get("phase")!="results":
            return
        lines=flow.get("result_lines",["0"])
        flow["field_armed"]=False
        flow["result_index"]=max(0,min(len(lines)-1,flow.get("result_index",0)))
        index=flow["result_index"]
        if flow.get("mode") == "History":
            # '=' recalls a history item; OPTN is neither relevant nor true.
            self._set_lcd_expression("HISTORY   ▲▼")
            entries=flow.get("history_entries",[])
            if (
                0 <= index < len(entries)
                and isinstance(entries[index],CalculationHistoryEntry)
                and self._render_history_integral_preview(entries[index])
            ):
                self._show_completed_result(entries[index].result)
                self.expr.focus_set()
                return
            # The previous entry may have drawn its integral. This one has no
            # template, so the canvas has to go: otherwise that integral stays
            # on the LCD above an unrelated result.
            self._hide_template_canvas()
        else:
            self._set_lcd_expression(f"{self._lcd_title(flow['title'])}  ▲▼  ◀▶  OPTN")
        viewport=self._result_viewport(lines[index],flow.get("result_offset",0))
        flow["result_offset"]=viewport.offset
        self.result.config(text=viewport.text)
        self.expr.focus_set()

    def _lcd_cycle_choice(self,direction):
        flow=self._lcd_state()
        spec=self._lcd_current_spec()
        if not flow or spec is None or spec.get("type")!="choice":
            return False
        codes=list(spec["choices"])
        try:
            raw=self.expr.get() or self._lcd_field_text(flow,spec)
            current=self._lcd_parse_field(spec,raw)
            index=next(index for index,code in enumerate(codes) if spec["choices"][code]==current)
        except Exception:
            index=0
        code=codes[(index+direction)%len(codes)]
        flow.setdefault("draft",{})[spec["key"]]=str(code)
        self._lcd_render_field()
        return True

    def _lcd_submit(self):
        flow=self._lcd_state()
        if not flow:
            return
        if flow.get("phase")=="sheet":
            self._lcd_submit_sheet()
            return
        if flow.get("phase")=="results":
            self._start_lcd_flow(flow["mode"])
            return
        spec=self._lcd_current_spec()
        if spec is None:
            return
        try:
            raw=self.expr.get()
            if spec.get("type")=="choice" and not raw.strip():
                raw=self._lcd_field_text(flow,spec)
            value=self._lcd_parse_field(spec,raw)
        except Exception as exc:
            self._lcd_error(exc)
            return
        flow.setdefault("values",{})[spec["key"]]=value
        flow.setdefault("draft",{}).pop(spec["key"],None)
        if flow["index"]<len(flow["fields"])-1:
            flow["index"]+=1
            self._lcd_render_field()
            return
        try:
            self._lcd_complete_flow()
        except Exception as exc:
            self._lcd_error(exc)

    def _lcd_vertical_move(self,direction):
        flow=self._lcd_state()
        if not flow:
            return False
        if flow.get("phase")=="sheet":
            return self._lcd_move_sheet_row(direction)
        if flow.get("phase")=="results":
            lines=flow.get("result_lines",[])
            if lines:
                old_index=flow.get("result_index",0)
                flow["result_index"]=max(0,min(len(lines)-1,old_index+direction))
                if flow["result_index"]!=old_index:
                    flow["result_offset"]=0
                    flow["history_body_cursor"]=0
                self._lcd_render_result()
            return True
        if flow.get("phase")=="form":
            self._lcd_capture_draft()
            flow["index"]=max(0,min(len(flow["fields"])-1,flow["index"]+direction))
            self._lcd_render_field()
            return True
        return False

    def _lcd_move(self,direction):
        flow=self._lcd_state()
        if not flow:
            return False
        if flow.get("phase")=="sheet":
            return self._lcd_move_sheet_column(direction)
        if flow.get("phase")=="results":
            lines=flow.get("result_lines",[])
            if not lines:
                return False
            if flow.get("mode")=="History" and self._scroll_history_integral_preview(direction):
                return True
            index=max(0,min(len(lines)-1,flow.get("result_index",0)))
            current=self._result_viewport(lines[index],flow.get("result_offset",0))
            if not (current.can_scroll_left or current.can_scroll_right):
                return False
            viewport=scroll_result(lines[index],current.offset,direction,self._lcd_content_width(),self._lcd_measure_text)
            flow["result_offset"]=viewport.offset
            self.result.config(text=viewport.text)
            return True
        if flow.get("phase")!="form":
            return False
        spec=self._lcd_current_spec()
        if spec is None or spec.get("type")=="choice":
            return self._lcd_cycle_choice(direction)
        template=flow.get("template")
        if not isinstance(template,MathTemplate):
            return False
        if template.active_slot not in {field["key"] for field in flow["fields"]}:
            return False
        self._lcd_capture_draft()
        if not template.move(NavigationDirection.LEFT if direction < 0 else NavigationDirection.RIGHT):
            return False
        for index,field in enumerate(flow["fields"]):
            if field["key"]==template.active_slot:
                flow["index"]=index
                self._lcd_render_field()
                return True
        return False

    def _lcd_keypress(self,event):
        flow=self._lcd_state()
        if not flow:
            return None
        if flow.get("phase")=="form":
            if event.char and event.char.isprintable() and not self._lcd_matrix_row_allows_insert(event.char):
                return "break"
            if (event.char and event.char.isprintable()) or event.keysym in {"BackSpace","Delete"}:
                flow["field_armed"]=False
            return None
        if flow.get("phase")!="sheet":
            return None
        if (
            flow.get("sheet_phase")=="browse"
            and event.keysym not in {"Left","Right","Up","Down","Return","KP_Enter","Escape"}
            and (event.char and event.char.isprintable() or event.keysym in {"BackSpace","Delete"})
        ):
            flow["editing"]=True
        return None

    def _keyboard_character_token(self, char):
        """Return the calculator-key equivalent of a typed character, if any."""
        if char in self.KEYBOARD_CHARACTER_MAP:
            return self.KEYBOARD_CHARACTER_MAP[char]
        if char.isdigit() or char in self.KEYBOARD_VARIABLES:
            return char
        if char == "i" and getattr(self,"mode","Calculate")=="Complex":
            return char
        return None

    def _physical_keypress(self,event):
        """Route physical keys through the same public operations as LCD keys."""
        if self.__dict__.get("_calculation_busy",False):
            if event.keysym == "Escape":
                self.ac_key()
            return "break"
        if self.template_kind:
            return None
        if event.keysym in {"Return","KP_Enter"}:
            self.equals(); return "break"
        if event.keysym in {"Escape"}:
            self.ac_key(); return "break"
        if event.keysym in {"BackSpace","Delete"}:
            self.del_key(); return "break"
        if event.keysym in {"Left","Right"}:
            self.move(-1 if event.keysym=="Left" else 1); return "break"
        if event.keysym in {"Up","Down"}:
            self.vertical_move(-1 if event.keysym=="Up" else 1); return "break"
        # Block paste and modifier combinations so they cannot bypass the
        # visible-key restriction.  F1/Escape are handled at the root level.
        if event.state & 0x4 or event.state & 0x8:
            return "break"
        if event.char and event.char.isprintable():
            token=self._keyboard_character_token(event.char)
            if token is not None:
                self.insert(token)
            return "break"
        return None

    def _lcd_options(self):
        flow=self._lcd_state()
        if not flow:
            return
        if flow["mode"]=="Spreadsheet":
            if flow.get("phase")=="results":
                self._lcd_start_sheet()
            elif flow.get("editing"):
                self._lcd_error(CalculatorError("Save or cancel the cell edit before opening tools"))
            else:
                self._lcd_sheet_tools()
        else:
            self._start_lcd_flow(flow["mode"])

    def _start_lcd_flow(self,mode,*,source_expression=None):
        if mode=="History" and self.__dict__.get("mode","Calculate") not in {"Calculate","Complex"}:
            return
        self.cancel_template()
        self._lcd_flow=LCDFlowState(mode=mode,values={},draft={},last_error="")
        if source_expression is not None:
            self._active_flow()["source_expression"]=source_expression
        starters={
            "Integral":self._lcd_start_integral,
            "Complex Integral":self._lcd_start_complex_integral,
            "Matrix":self._lcd_start_matrix,
            "Vector":self._lcd_start_vector,
            "Statistics":self._lcd_start_statistics,
            "Distribution":self._lcd_start_distribution,
            "Spreadsheet":self._lcd_start_sheet,
            "Table":self._lcd_start_table,
            "Equation/Func":self._lcd_start_equation,
            "Inequality":self._lcd_start_inequality,
            "Ratio":self._lcd_start_ratio,
            "History":self._lcd_start_history,
        }
        starters[mode]()

    def _lcd_start_history(self):
        # The engine keeps history in calculation order for Ans and ordinary
        # input recall.  The LCD list is a newest-first view: entry 1 is the
        # most recently completed calculation.
        entries=list(reversed(self._history_entries()))
        flow=self._lcd_state(create=True)
        flow["history_entries"]=entries
        lines=[self._history_line(entry.expression,entry.result) for entry in entries] or ["No saved calculations"]
        self._lcd_show_results("HISTORY",lines)

    @staticmethod
    def _history_integral_preview(entry):
        return entry_rules.history_integral_preview(entry)

    def _render_history_integral_preview(self, entry):
        """Draw a calculus history entry through the normal template renderer.

        The temporary renderer state is deliberately restored afterwards: the
        History flow remains a browser, while '=' creates the editable form.
        """
        preview=self._history_integral_preview(entry)
        if preview is None:
            return False
        kind,fields,order=preview
        flow=self.__dict__.get("_lcd_flow",{})
        cursor=max(0,min(len(fields.get("body","")),int(flow.get("history_body_cursor",0))))
        names=("template_kind","template_fields","template_order","template_index","template_cursors")
        previous={name:self.__dict__.get(name) for name in names}
        prior_read_only=self.__dict__.get("_template_read_only",False)
        try:
            self.template_kind=kind
            self.template_fields=cast(dict, fields)
            self.template_order=order
            self.template_index=0
            self.template_cursors={key:len(str(value)) for key,value in fields.items() if key!="order"}
            self.template_cursors["body"]=cursor
            self._template_read_only=True
            self.render_template()
        finally:
            for name,value in previous.items():
                setattr(self,name,value)
            self._template_read_only=prior_read_only
        return True

    def _scroll_history_integral_preview(self, direction):
        """Pan only an overflowing integrand while its symbols and bounds stay fixed."""
        flow=self.__dict__.get("_lcd_flow")
        if not flow or flow.get("mode")!="History":
            return False
        entries=flow.get("history_entries",[])
        index=flow.get("result_index",0)
        if not 0 <= index < len(entries) or not isinstance(entries[index],CalculationHistoryEntry):
            return False
        preview=self._history_integral_preview(entries[index])
        if preview is None:
            return False
        _kind,fields,_order=preview
        body=fields.get("body","")
        max_width=max(1,self._lcd_content_width()-self._sp(240))
        shown,_cursor_offset=self._template_text_view(
            body,0,self._font("lcd",17),max_width,empty_placeholder="",
        )
        if shown==body:
            return False
        cursor=max(0,min(len(body),int(flow.get("history_body_cursor",0))))
        target=max(0,min(len(body),cursor+(1 if direction>0 else -1)))
        if target==cursor:
            return False
        flow["history_body_cursor"]=target
        self._lcd_render_result()
        return True

    def _lcd_recall_history_entry(self):
        """Recall the selected raw history record without recalculating it."""
        flow=self._lcd_state()
        if not flow:
            return
        entries=flow.get("history_entries",[])
        index=flow.get("result_index",0)
        if not entries or not 0<=index<len(entries):
            self._set_lcd_label("History is empty")
            return
        self._reset_lcd_flow()
        entry=entries[index]
        if isinstance(entry,CalculationHistoryEntry) and self._recall_structured_history(entry):
            self._reset_history_browsing()
            return
        expression,result=entry
        self._recall_expression(expression)
        self._show_completed_result(result)
        self._reset_history_browsing()

    def _lcd_start_integral(self):
        self._active_flow().setdefault("source_expression",self.expr.get().strip())
        self._lcd_begin_form(
            "INTEGRAL",[self._lcd_action_choice_field("calculus_action","type",self.INTEGRAL_ACTIONS)],"calculus_action",
        )

    def _lcd_start_complex_integral(self):
        self._active_flow().setdefault("source_expression",self.expr.get().strip())
        self._lcd_begin_form(
            "CPLX INT",[self._lcd_action_choice_field("calculus_action","type",self.COMPLEX_CALCULUS_ACTIONS)],"calculus_action",
        )

    def _lcd_choose_calculus_action(self):
        flow=self._active_flow(); action=self.LEGACY_CALCULUS_ACTION_IDS.get(flow["values"]["calculus_action"],flow["values"]["calculus_action"])
        source=flow.get("source_expression","")
        if action=="definite":
            self._reset_lcd_flow()
            self.set_expr(source)
            self.start_integral_template()
            return
        if action in {"double", "triple"}:
            if flow["mode"]=="Complex Integral":
                raise CalculatorError("Argument ERROR: unsupported calculus operation")
            self._reset_lcd_flow()
            self.set_expr(source)
            self.start_multiple_integral_template(action)
            return
        raise CalculatorError("Argument ERROR: unsupported calculus operation")

    @staticmethod
    def _lcd_choice_field(key,label,choices,default=None):
        return lcd_fields.choice_field(key,label,choices,default)

    @staticmethod
    def _lcd_action_choice_field(key,label,actions):
        return lcd_fields.action_choice_field(key,label,actions)

    @staticmethod
    def _lcd_number_field(key,label,default: Any = "",integer=False,minimum=None,maximum=None):
        return lcd_fields.number_field(key,label,default,integer,minimum,maximum)

    @staticmethod
    def _lcd_matrix_choices(include_ans=False):
        choices={1:"MatA",2:"MatB",3:"MatC",4:"MatD"}
        if include_ans:
            choices[5]="MatAns"
        return choices

    @staticmethod
    def _lcd_vector_choices(include_ans=False):
        choices={1:"VctA",2:"VctB",3:"VctC",4:"VctD"}
        if include_ans:
            choices[5]="VctAns"
        return choices

    def _lcd_array_lines(self,title,value):
        return lcd_fields.array_lines(title,value)

    def _lcd_complete_flow(self):
        flow=self._active_flow()
        handlers={
            "calculus_action":self._lcd_choose_calculus_action,
            "matrix_action":self._lcd_choose_matrix_action,
            "matrix_shape":self._lcd_expand_matrix_values,
            "matrix_rows":self._lcd_define_matrix,
            "matrix_operation":self._lcd_run_matrix_operation,
            "matrix_identity":self._lcd_run_matrix_identity,
            "matrix_copy":self._lcd_run_matrix_copy,
            "vector_action":self._lcd_choose_vector_action,
            "vector_shape":self._lcd_expand_vector_values,
            "vector_values":self._lcd_define_vector,
            "vector_operation":self._lcd_run_vector_operation,
            "vector_copy":self._lcd_run_vector_copy,
            "statistics_action":self._lcd_choose_statistics_action,
            "statistics_run":self._lcd_run_statistics,
            "distribution_kind":self._lcd_choose_distribution_kind,
            "distribution_run":self._lcd_run_distribution,
            "table_run":self._lcd_run_table,
            "equation_kind":self._lcd_choose_equation_kind,
            "equation_poly_degree":self._lcd_expand_polynomial_values,
            "equation_simul_size":self._lcd_expand_simultaneous_values,
            "inequality_degree":self._lcd_expand_inequality_values,
            "inequality_values":self._lcd_run_inequality,
            "ratio_kind":self._lcd_choose_ratio_kind,
            "ratio_values":self._lcd_run_ratio,
            "sheet_tool":self._lcd_choose_sheet_tool,
            "sheet_copy":self._lcd_run_sheet_copy,
            "sheet_cut":self._lcd_run_sheet_cut,
            "sheet_grab":self._lcd_run_sheet_grab,
            "sheet_fill_value":self._lcd_run_sheet_fill_value,
            "sheet_fill_formula":self._lcd_run_sheet_fill_formula,
            "sheet_delete_all":self._lcd_run_sheet_delete_all,
        }
        handler=handlers.get(cast(str, flow.get("stage")))
        if handler is None:
            raise CalculatorError("Argument ERROR: unsupported LCD workflow")
        handler()

    # Matrix -----------------------------------------------------------------
    def _lcd_start_matrix(self):
        actions={
            1:"Define / Edit",2:"A + B",3:"A - B",4:"A × B",5:"det(A)",
            6:"A⁻¹",7:"Trn(A)",8:"A²",9:"A³",10:"Abs(A)",11:"Identity",12:"Copy",
        }
        self._lcd_begin_form("MATRIX",[self._lcd_choice_field("action","action",actions)],"matrix_action")

    def _lcd_choose_matrix_action(self):
        flow=self._active_flow(); action=flow["values"]["action"]
        if action=="Define / Edit":
            self._lcd_begin_form("MATRIX define",[
                self._lcd_choice_field("matrix_name","name",self._lcd_matrix_choices()),
                self._lcd_number_field("matrix_rows","rows",2,integer=True,minimum=1,maximum=4),
                self._lcd_number_field("matrix_cols","columns",2,integer=True,minimum=1,maximum=4),
            ],"matrix_shape")
            return
        if action=="Identity":
            self._lcd_begin_form("MATRIX identity",[self._lcd_number_field("matrix_size","size",2,integer=True,minimum=1,maximum=4)],"matrix_identity")
            return
        if action=="Copy":
            self._lcd_begin_form("MATRIX copy",[
                self._lcd_choice_field("matrix_source","source",self._lcd_matrix_choices(True)),
                self._lcd_choice_field("matrix_destination","destination",self._lcd_matrix_choices()),
            ],"matrix_copy")
            return
        operation={"A + B":"+","A - B":"-","A × B":"*","det(A)":"det","A⁻¹":"inv","Trn(A)":"trn","A²":"square","A³":"cube","Abs(A)":"abs"}[action]
        fields=[self._lcd_choice_field("matrix_a","first matrix",self._lcd_matrix_choices(True))]
        if operation in {"+","-","*"}:
            fields.append(self._lcd_choice_field("matrix_b","second matrix",self._lcd_matrix_choices(True)))
        flow["matrix_operation"]=operation
        self._lcd_begin_form("MATRIX "+action,fields,"matrix_operation")

    def _lcd_expand_matrix_values(self):
        values=self._active_flow()["values"]
        self._lcd_begin_form(*lcd_forms.matrix_form(
            values["matrix_name"],values["matrix_rows"],values["matrix_cols"]))

    def _lcd_define_matrix(self):
        flow=self._active_flow(); rows=flow["values"]["matrix_rows"]
        data=np.array([flow["values"][f"matrix_row_{row}"] for row in range(rows)])
        name=flow["values"]["matrix_name"]
        self.core.define_matrix(name,data)
        self._lcd_show_results("MATRIX",self._lcd_array_lines(name,data))

    def _lcd_run_matrix_operation(self):
        flow=self._active_flow(); operation=flow["matrix_operation"]
        result=self.core.matrix_op(operation,flow["values"]["matrix_a"],flow["values"].get("matrix_b"))
        self._lcd_show_results("MATRIX",self._lcd_array_lines(operation,result))

    def _lcd_run_matrix_identity(self):
        result=self.core.identity(self._active_flow()["values"]["matrix_size"])
        self._lcd_show_results("MATRIX",self._lcd_array_lines("I",result))

    def _lcd_run_matrix_copy(self):
        values=self._active_flow()["values"]; source=values["matrix_source"]; destination=values["matrix_destination"]
        data=self.core.mat_ans if source=="MatAns" else self.core.matrices.get(source)
        if data is None:
            raise CalculatorError("Dimension ERROR")
        self.core.matrices[destination]=np.array(data,copy=True)
        self._lcd_show_results("MATRIX",[f"{source} → {destination}"])

    # Vector -----------------------------------------------------------------
    def _lcd_start_vector(self):
        actions={1:"Define / Edit",2:"A + B",3:"A - B",4:"Dot",5:"Cross",6:"Angle",7:"Abs",8:"Unit",9:"Scalar ×",10:"Copy"}
        self._lcd_begin_form("VECTOR",[self._lcd_choice_field("action","action",actions)],"vector_action")

    def _lcd_choose_vector_action(self):
        flow=self._active_flow(); action=flow["values"]["action"]
        if action=="Define / Edit":
            self._lcd_begin_form("VECTOR define",[
                self._lcd_choice_field("vector_name","name",self._lcd_vector_choices()),
                self._lcd_number_field("vector_dimension","dimension",2,integer=True,minimum=2,maximum=3),
            ],"vector_shape")
            return
        if action=="Copy":
            self._lcd_begin_form("VECTOR copy",[
                self._lcd_choice_field("vector_source","source",self._lcd_vector_choices(True)),
                self._lcd_choice_field("vector_destination","destination",self._lcd_vector_choices()),
            ],"vector_copy")
            return
        operation={"A + B":"+","A - B":"-","Dot":"dot","Cross":"cross","Angle":"angle","Abs":"abs","Unit":"unit","Scalar ×":"scale"}[action]
        fields=[self._lcd_choice_field("vector_a","first vector",self._lcd_vector_choices(True))]
        if operation in {"+","-","dot","cross","angle"}:
            fields.append(self._lcd_choice_field("vector_b","second vector",self._lcd_vector_choices(True)))
        if operation=="scale":
            fields.append(self._lcd_number_field("vector_scalar","scalar",1))
        flow["vector_operation"]=operation
        self._lcd_begin_form("VECTOR "+action,fields,"vector_operation")

    def _lcd_expand_vector_values(self):
        values=self._active_flow()["values"]
        self._lcd_begin_form(*lcd_forms.vector_form(values["vector_name"],values["vector_dimension"]))

    def _lcd_define_vector(self):
        flow=self._active_flow(); dimension=flow["values"]["vector_dimension"]
        data=np.array([flow["values"][f"vector_{index}"] for index in range(dimension)])
        name=flow["values"]["vector_name"]
        self.core.define_vector(name,data)
        self._lcd_show_results("VECTOR",self._lcd_array_lines(name,data))

    def _lcd_run_vector_operation(self):
        flow=self._active_flow(); values=flow["values"]
        result=self.core.vector_op(flow["vector_operation"],values["vector_a"],values.get("vector_b"),values.get("vector_scalar"))
        self._lcd_show_results("VECTOR",self._lcd_array_lines(flow["vector_operation"],result))

    def _lcd_run_vector_copy(self):
        values=self._active_flow()["values"]; source=values["vector_source"]; destination=values["vector_destination"]
        data=self.core.vct_ans if source=="VctAns" else self.core.vectors.get(source)
        if data is None:
            raise CalculatorError("Dimension ERROR")
        self.core.vectors[destination]=np.array(data,copy=True)
        self._lcd_show_results("VECTOR",[f"{source} → {destination}"])

    # Statistics -------------------------------------------------------------
    def _lcd_start_statistics(self):
        analyses={1:"1-Variable",2:"Linear",3:"Quadratic",4:"Logarithmic",5:"e Exponential",6:"ab Exponential",7:"Power",8:"Inverse",9:"P(t)",10:"Q(t)",11:"R(t)",12:"x→t"}
        self._lcd_begin_form("STAT",[self._lcd_choice_field("analysis","analysis",analyses)],"statistics_action")

    def _lcd_choose_statistics_action(self):
        flow=self._active_flow(); analysis=flow["values"]["analysis"]
        if analysis=="1-Variable":
            fields=[{"key":"stat_x","label":"x values (comma)","type":"numbers","default":""}]
            if self.core.settings.statistics_freq:
                fields.append({"key":"stat_frequency","label":"frequencies (comma)","type":"numbers","default":""})
        elif analysis in {"P(t)","Q(t)","R(t)"}:
            fields=[self._lcd_number_field("stat_t","t",0)]
        elif analysis=="x→t":
            fields=[{"key":"stat_x","label":"x values (comma)","type":"numbers","default":""}]
            if self.core.settings.statistics_freq:
                fields.append({"key":"stat_frequency","label":"frequencies (comma)","type":"numbers","default":""})
            fields.append(self._lcd_number_field("stat_target","x",0))
        else:
            fields=[
                {"key":"stat_x","label":"x values (comma)","type":"numbers","default":""},
                {"key":"stat_y","label":"y values (comma)","type":"numbers","default":""},
            ]
        self._lcd_begin_form("STAT "+analysis,fields,"statistics_run")

    def _lcd_run_statistics(self):
        values=self._active_flow()["values"]; analysis=values["analysis"]
        if analysis=="1-Variable":
            result=self.core.one_var_stats(values["stat_x"],values.get("stat_frequency"))
            lines=[f"{key} = {self._lcd_result_number_text(value)}" for key,value in result.items()]
        elif analysis in {"P(t)","Q(t)","R(t)"}:
            fn={"P(t)":self.core.normal_P,"Q(t)":self.core.normal_Q,"R(t)":self.core.normal_R}[analysis]
            lines=[f"{analysis} = {fn(values['stat_t']):.12g}"]
        elif analysis=="x→t":
            stats=self.core.one_var_stats(values["stat_x"],values.get("stat_frequency"))
            if stats["σx"]==0:
                raise CalculatorError("Math ERROR: standard deviation is zero")
            lines=[f"t = {(values['stat_target']-stats['x̄'])/stats['σx']:.12g}"]
        else:
            kind={"Linear":"linear","Quadratic":"quadratic","Logarithmic":"log","e Exponential":"exp_e","ab Exponential":"exp_b","Power":"power","Inverse":"inverse"}[analysis]
            result=self.core.regression(values["stat_x"],values["stat_y"],kind)
            lines=[f"{key} = {self._lcd_result_number_text(value)}" for key,value in result.items() if key!="predict"]
        self._lcd_show_results("STAT",lines)

    # Distribution -----------------------------------------------------------
    def _lcd_start_distribution(self):
        kinds={1:"Normal PD",2:"Normal CD",3:"Inverse Normal",4:"Binomial PD",5:"Binomial CD",6:"Poisson PD",7:"Poisson CD"}
        self._lcd_begin_form("DIST",[self._lcd_choice_field("distribution_kind","type",kinds)],"distribution_kind")

    def _lcd_choose_distribution_kind(self):
        self._lcd_begin_form(*lcd_forms.distribution_form(self._active_flow()["values"]["distribution_kind"]))

    def _lcd_run_distribution(self):
        values=self._active_flow()["values"]; kind=values["distribution_kind"]
        fields={
            "Normal PD":["x","sigma","mu"],"Normal CD":["lower","upper","sigma","mu"],"Inverse Normal":["area","sigma","mu"],
            "Binomial PD":["x","N","p"],"Binomial CD":["x","N","p"],"Poisson PD":["x","lam"],"Poisson CD":["x","lam"],
        }[kind]
        result=self.core.distribution(kind,**{key:values[key] for key in fields})
        self._lcd_show_results("DIST",[f"{kind} = {result:.12g}"])

    # Table ------------------------------------------------------------------
    def _lcd_start_table(self):
        fields=[{"key":"table_f","label":"f(x)","type":"function","default":"x^2"}]
        if self.core.settings.table_two_functions:
            fields.append({"key":"table_g","label":"g(x)","type":"function","default":"x^2+1"})
        fields.extend([
            self._lcd_number_field("table_start","start",-1),
            self._lcd_number_field("table_end","end",1),
            self._lcd_number_field("table_step","step",0.5),
        ])
        self._lcd_begin_form("TABLE",fields,"table_run")

    def _lcd_run_table(self):
        values=self._active_flow()["values"]; has_g="table_g" in values
        count=self._table_row_count(values["table_start"],values["table_end"],values["table_step"],has_g)
        rows=[]
        for index in range(count):
            x_value=values["table_start"]+index*values["table_step"]
            x_symbol=sp.Float(x_value)
            f_value=self._lcd_real_expression(self.core.parse(values["table_f"],{"x":x_symbol}),"table result")
            row=f"x={x_value:.12g}  f={f_value:.12g}"
            if has_g:
                g_value=self._lcd_real_expression(self.core.parse(values["table_g"],{"x":x_symbol}),"table result")
                row+=f"  g={g_value:.12g}"
            rows.append(row)
        self.core.memory["x"]=sp.Float(values["table_start"]+(count-1)*values["table_step"])
        self._lcd_show_results("TABLE",rows)

    # Equation / inequality / ratio -----------------------------------------
    def _lcd_start_equation(self):
        kinds=(("polynomial","Polynomial"),("simultaneous","Simultaneous"),("ode","Differential Eq."))
        self._lcd_begin_form(
            "EQUATION",[self._lcd_action_choice_field("equation_kind","type",kinds)],"equation_kind",
        )

    def _lcd_choose_equation_kind(self):
        kind=self._active_flow()["values"]["equation_kind"]
        if kind=="polynomial":
            self._lcd_begin_form("POLYNOMIAL",[self._lcd_number_field("polynomial_degree","degree",2,integer=True,minimum=2,maximum=4)],"equation_poly_degree")
        elif kind=="simultaneous":
            self._lcd_begin_form("SIMULTANEOUS",[self._lcd_number_field("simultaneous_size","unknowns",2,integer=True,minimum=2,maximum=4)],"equation_simul_size")
        else:
            # The single editable mathematical template is the entire ODE
            # input. Its four coefficient slots are classified by the engine
            # when the user presses '='.
            self.start_ode_template()

    def _lcd_expand_polynomial_values(self):
        degree=self._active_flow()["values"]["polynomial_degree"]
        self.start_polynomial_template(degree)

    @staticmethod
    def _lcd_complex_text(value):
        number=complex(value)
        if abs(number.imag)<1e-10:
            return f"{number.real:.12g}"
        return f"{number.real:.12g}{number.imag:+.12g}i"

    def _polynomial_result_lines(self, degree, coefficients):
        roots=self.core.polynomial_roots(coefficients)
        lines=[f"x{index+1} = {self._lcd_complex_text(root)}" for index,root in enumerate(roots)]
        if not lines and not self.core.settings.equation_complex:
            lines.append("No real roots")
        if degree==2:
            a,b,c=coefficients; x_value=-b/(2*a); y_value=a*x_value*x_value+b*x_value+c
            lines.append(f"Vertex = ({x_value:.12g}, {y_value:.12g})")
        return lines

    def _lcd_expand_simultaneous_values(self):
        size=self._active_flow()["values"]["simultaneous_size"]
        self.start_simultaneous_template(size)

    def _lcd_start_inequality(self):
        self._lcd_begin_form("INEQUALITY",[self._lcd_number_field("inequality_degree","degree",2,integer=True,minimum=1,maximum=4)],"inequality_degree")

    def _lcd_expand_inequality_values(self):
        degree=self._active_flow()["values"]["inequality_degree"]
        fields=[self._lcd_number_field(f"inequality_{index}",f"coefficient a{degree-index}",0) for index in range(degree+1)]
        fields.append(self._lcd_choice_field("inequality_relation","relation",{1:">",2:"<",3:"≥",4:"≤"}))
        self._lcd_begin_form(f"INEQUALITY {degree}",fields,"inequality_values")

    def _lcd_run_inequality(self):
        values=self._active_flow()["values"]; degree=values["inequality_degree"]
        coefficients=[values[f"inequality_{index}"] for index in range(degree+1)]
        result=self.core.inequality(coefficients,values["inequality_relation"])
        self._lcd_show_results("INEQUALITY",[str(result)])

    def _lcd_start_ratio(self):
        kinds={1:"A:B = X:D",2:"A:B = C:X"}
        self._lcd_begin_form("RATIO",[self._lcd_choice_field("ratio_kind","form",kinds)],"ratio_kind")

    def _lcd_choose_ratio_kind(self):
        self._lcd_begin_form(*lcd_forms.ratio_form(self._active_flow()["values"]["ratio_kind"]))

    def _lcd_run_ratio(self):
        values=self._active_flow()["values"]; kind=values["ratio_kind"]
        if kind=="A:B = X:D":
            result=self.core.ratio("A:B=X:D",A=values["ratio_A"],B=values["ratio_B"],D=values["ratio_D"])
        else:
            result=self.core.ratio("A:B=C:X",A=values["ratio_A"],B=values["ratio_B"],C=values["ratio_C"])
        if not math.isfinite(float(result)):
            raise CalculatorError("Math ERROR: ratio result must be finite")
        self._lcd_show_results("RATIO",[f"X = {result:.12g}"])

    # Spreadsheet ------------------------------------------------------------
    def _lcd_start_sheet(self):
        self._active_flow().update({
            "phase":"sheet", "stage":"sheet", "sheet_phase":"browse",
        })
        SpreadsheetCursor().apply_to(self._active_flow())
        self._lcd_render_sheet()

    def _lcd_sheet_address(self):
        return lcd_forms.sheet_address(self._active_flow())

    def _lcd_render_sheet(self):
        flow=self.__dict__.get("_lcd_flow")
        if not flow or flow.get("phase")!="sheet":
            return
        address=self._lcd_sheet_address()
        raw=self.sheet.cells.get(address,"")
        if not flow.get("editing"):
            self._set_lcd_expression(raw)
        if flow.get("editing"):
            prompt=f"Edit {address}  = save  AC"
        else:
            shown=self._spreadsheet_display_value(address)
            prompt=f"{address}={shown if shown!='' else 0}  ▲▼ ◀▶  OPTN"
        self._set_lcd_label(prompt)
        self.expr.focus_set()

    def _lcd_move_sheet_column(self,direction):
        flow=self.__dict__.get("_lcd_flow")
        if not flow or flow.get("phase")!="sheet":
            return False
        cursor=SpreadsheetCursor.from_flow(flow)
        if cursor.editing:
            return False
        cursor.move_column(direction).apply_to(flow)
        self._lcd_render_sheet()
        return True

    def _lcd_move_sheet_row(self,direction):
        flow=self.__dict__.get("_lcd_flow")
        if not flow or flow.get("phase")!="sheet":
            return False
        cursor=SpreadsheetCursor.from_flow(flow)
        if cursor.editing:
            return True
        cursor.move_row(direction).apply_to(flow)
        self._lcd_render_sheet()
        return True

    def _lcd_submit_sheet(self):
        flow=self._active_flow()
        address=self._lcd_sheet_address()
        raw=self.sheet.cells.get(address,"")
        if flow.get("editing") or self.expr.get()!=raw:
            self.sheet.set(address,self.expr.get())
            flow["editing"]=False
            self._lcd_render_sheet()
            self._set_lcd_label(f"Saved {address} = {self._spreadsheet_display_value(address) or 0}")
            return
        flow["editing"]=True
        self._set_lcd_label(f"Edit {address}  = save  AC")

    def _lcd_sheet_return(self,message=None):
        flow=self._active_flow()
        flow.update({"phase":"sheet","stage":"sheet","sheet_phase":"browse","editing":False,"draft":{}})
        self._lcd_render_sheet()
        if message:
            self._set_lcd_label(message)

    def _lcd_sheet_tools(self):
        tools={
            1:"Edit cell",2:"Delete cell",3:"Copy cell",4:"Cut cell",5:"Fill value",
            6:"Fill formula",7:"Insert reference",8:"Recalculate",9:"Free space",10:"Delete all",
        }
        self._lcd_begin_form("SHEET tools",[self._lcd_choice_field("sheet_tool","tool",tools)],"sheet_tool")

    def _lcd_choose_sheet_tool(self):
        flow=self._active_flow(); tool=flow["values"]["sheet_tool"]
        if tool=="Edit cell":
            flow.update({"phase":"sheet","stage":"sheet","sheet_phase":"browse","editing":True})
            self._set_lcd_expression(self.sheet.cells.get(self._lcd_sheet_address(),""))
            self._set_lcd_label(f"Edit {self._lcd_sheet_address()}  = save  AC")
            return
        if tool=="Delete cell":
            address=self._lcd_sheet_address(); self.sheet.delete(address); self._lcd_sheet_return(f"Deleted {address}")
            return
        if tool in {"Copy cell","Cut cell"}:
            fields=[
                self._lcd_choice_field("sheet_target_column","destination column",{1:"A",2:"B",3:"C",4:"D",5:"E"}),
                self._lcd_number_field("sheet_target_row","destination row",1,integer=True,minimum=1,maximum=45),
            ]
            self._lcd_begin_form("SHEET "+tool,fields,"sheet_copy" if tool=="Copy cell" else "sheet_cut")
            return
        if tool=="Insert reference":
            source=self._lcd_sheet_address()
            fields=[
                self._lcd_choice_field("sheet_target_column","destination column",{1:"A",2:"B",3:"C",4:"D",5:"E"}),
                self._lcd_number_field("sheet_target_row","destination row",1,integer=True,minimum=1,maximum=45),
                {"key":"sheet_reference_prefix","label":"formula before reference","type":"raw","default":"="},
            ]
            self._lcd_begin_form(f"SHEET insert {source}",fields,"sheet_grab")
            return
        if tool in {"Fill value","Fill formula"}:
            fields=[
                self._lcd_choice_field("sheet_target_column","end column",{1:"A",2:"B",3:"C",4:"D",5:"E"}),
                self._lcd_number_field("sheet_target_row","end row",1,integer=True,minimum=1,maximum=45),
                {"key":"sheet_fill_text","label":"value" if tool=="Fill value" else "=formula","type":"raw","default":""},
            ]
            self._lcd_begin_form("SHEET "+tool,fields,"sheet_fill_value" if tool=="Fill value" else "sheet_fill_formula")
            return
        if tool=="Recalculate":
            count=len(self.sheet.recalculate()); self._lcd_sheet_return(f"Recalculated {count} cells")
            return
        if tool=="Free space":
            self._lcd_show_results("SHEET",[f"Free space = {self.sheet.free_space()} bytes"])
            return
        self._lcd_begin_form("SHEET delete all",[self._lcd_choice_field("sheet_confirm","confirm",{1:"Cancel",2:"Delete all"},"Cancel")],"sheet_delete_all")

    def _lcd_sheet_target_address(self):
        return lcd_forms.sheet_target_address(self._active_flow())

    def _lcd_run_sheet_copy(self):
        source=self._lcd_sheet_address(); destination=self._lcd_sheet_target_address()
        self.sheet.copy(source,destination)
        self._lcd_sheet_return(f"Copied {source} → {destination}")

    def _lcd_run_sheet_cut(self):
        source=self._lcd_sheet_address(); destination=self._lcd_sheet_target_address()
        self.sheet.cut(source,destination)
        self._lcd_sheet_return(f"Cut {source} → {destination}")

    def _lcd_run_sheet_grab(self):
        """Insert the selected source-cell reference into a destination formula.

        The former popup workspace called this feature "Grab".  Making both
        addresses and the expression prefix explicit works on the calculator
        LCD and prevents accidental self-references while retaining its
        formula-building purpose.
        """
        source=self._lcd_sheet_address(); destination=self._lcd_sheet_target_address()
        if source==destination:
            raise CalculatorError("Argument ERROR: reference destination must be different from the source")
        prefix=self._active_flow()["values"]["sheet_reference_prefix"]
        if not prefix.startswith("="):
            raise CalculatorError("Syntax ERROR: formula before reference must start with =")
        self.sheet.set(destination,prefix+source)
        self._lcd_sheet_return(f"Inserted {source} into {destination}")

    def _lcd_run_sheet_fill_value(self):
        source=self._lcd_sheet_address(); destination=self._lcd_sheet_target_address()
        self.sheet.fill_value(source,destination,self._active_flow()["values"]["sheet_fill_text"])
        self._lcd_sheet_return(f"Filled {source}:{destination}")

    def _lcd_run_sheet_fill_formula(self):
        source=self._lcd_sheet_address(); destination=self._lcd_sheet_target_address(); formula=self._active_flow()["values"]["sheet_fill_text"]
        if not formula.startswith("="):
            raise CalculatorError("Syntax ERROR: formula must start with =")
        self.sheet.fill_formula(source,destination,formula)
        self._lcd_sheet_return(f"Filled {source}:{destination}")

    def _lcd_run_sheet_delete_all(self):
        if self._active_flow()["values"]["sheet_confirm"]=="Delete all":
            self.sheet.delete_all()
            self._lcd_sheet_return("Spreadsheet cleared")
        else:
            self._lcd_sheet_return("Delete all cancelled")

    def consume(self): self.shift=False; self.alpha=False; self.status_refresh()

    def _document_editing_active(self):
        return bool(
            isinstance(self.__dict__.get("_expression_document"),ExpressionDocument)
            and self.__dict__.get("mode","Calculate") in {"Calculate","Complex"}
            and not self.__dict__.get("template_kind")
            and not self.__dict__.get("_lcd_flow")
        )

    def _expression_document_for_entry(self):
        document=self.__dict__.get("_expression_document")
        if not isinstance(document,ExpressionDocument):
            document=ExpressionDocument()
        try:
            display=self.expr.get()
        except (AttributeError, tk.TclError):
            return document
        if document.display!=display:
            document=ExpressionDocument.from_text(display)
        self._expression_document=document
        return document

    def _set_expression_document(self, document, cursor=None):
        self._expression_document=document
        display=document.display
        self.expr.delete(0,tk.END)
        self.expr.insert(0,display)
        self.expr.icursor(len(display) if cursor is None else max(0,min(len(display),cursor)))

    def _expression_source(self):
        if self._document_editing_active():
            return self._expression_document_for_entry().source
        return self.expr.get()

    def _recall_expression(self, expression):
        document=self.__dict__.get("_history_documents",{}).get(str(expression))
        if isinstance(document,ExpressionDocument) and self.__dict__.get("mode","Calculate") in {"Calculate","Complex"}:
            self._set_expression_document(document)
        else:
            self.set_expr(str(expression))

    def remember(self):
        value=self._expression_document_for_entry() if self._document_editing_active() else self.expr.get()
        self.undo.append(value); self.undo=self.undo[-50:]

    def cancel_template(self):
        self._template_error_active=False
        self._template_session=None
        self.template_kind=None; self.template_fields={}; self.template_order=[]; self.template_index=0; self.template_cursors={}
        self._hide_template_canvas()

    def _hide_template_canvas(self):
        """Hide the template canvas and restore the plain LCD entry/result rows."""
        try:
            if getattr(self,"skin_mode",False):
                self.template_canvas.place_forget()
                # restore normal LCD entry/result positions
                sx1,sy1=self._sp(40),self._sp(128); sx2=self._sp(435)
                self.expr.place(x=sx1+self._sp(7),y=sy1+self._sp(34),width=(sx2-sx1)-self._sp(14),height=self._sp(51))
                self.result.place(x=sx1+self._sp(7),y=sy1+self._sp(89),width=(sx2-sx1)-self._sp(14),height=self._sp(58))
            else:
                self.template_canvas.pack_forget()
                if not self.expr.winfo_ismapped():
                    self.expr.pack(fill="x",padx=7,pady=(2,2),ipady=5,before=self.result)
            self.expr.selection_clear()
        except Exception:
            pass

    def insert(self,s):
        if self._history_lcd_active():
            self.consume()
            return
        if self.template_kind:
            self.template_insert(s); self.consume(); return
        if not self._lcd_matrix_row_allows_insert(s):
            self.consume()
            return
        self._begin_independent_edit()
        flow=self.__dict__.get("_lcd_flow")
        if flow and flow.get("phase")=="sheet" and flow.get("sheet_phase")=="browse":
            flow["editing"]=True
        self._lcd_prepare_direct_entry()
        self.remember(); pos=self.expr.index(tk.INSERT)
        if self._document_editing_active():
            document=self._expression_document_for_entry()
            if self.overwrite:
                for _ in range(len(str(s))):
                    document=document.delete_forward(pos)
            document=document.insert_text(pos,s)
            self._set_expression_document(document,pos+len(str(s)))
            self.consume()
            return
        if self.overwrite and pos<len(self.expr.get()): self.expr.delete(pos,pos+len(s))
        self.expr.insert(pos,s); self.consume()

    def _insert_engineering_prefix(self, symbol):
        """Insert an atomic visible prefix whose source stays parser-safe."""
        if not self._document_editing_active():
            return
        self._begin_independent_edit()
        self._lcd_prepare_direct_entry()
        self.remember()
        position=self.expr.index(tk.INSERT)
        document=self._expression_document_for_entry().insert_engineering_prefix(position,symbol)
        self._set_expression_document(document,position+1)
        self.consume()

    def set_expr(self,s,*,preserve_completed_result=False):
        if not self._template_rendering:self.cancel_template()
        if not preserve_completed_result:
            self._begin_independent_edit()
        flow=self.__dict__.get("_lcd_flow")
        if flow and flow.get("phase")=="form":
            flow["field_armed"]=False
        if self._document_editing_active():
            self._expression_document=ExpressionDocument.from_text(s)
        self.expr.delete(0,tk.END); self.expr.insert(0,s)

    def show(self,x,approx=False):
        self._engineering_exponent=None
        self._show_completed_result(self.core.format_result(x,approximate=approx))

    def _clear_modifiers(self):
        self.shift=False
        self.alpha=False
        with suppress(AttributeError, RecursionError, tk.TclError):
            self.status_refresh()

    def _clear_active_input_for_error(self):
        """Clear only the active entry, preserving its current calculator mode."""
        flow=self.__dict__.get("_lcd_flow")
        if flow and flow.get("phase")=="form":
            spec=self._lcd_current_spec()
            if spec is not None:
                flow.setdefault("draft",{})[spec["key"]]=""
                flow["field_armed"]=False
        elif getattr(self,"template_kind",None):
            try:
                key=cast(str, self._active_template_field())
                self.template_fields[key]=""
                self.template_cursors[key]=0
                self.render_template()
                return
            except (AttributeError, KeyError, RecursionError, tk.TclError):
                pass
        with suppress(AttributeError, RecursionError, tk.TclError):
            self.set_expr("")

    def err(self,e,*,clear_input=True):
        """Render calculator errors on the LCD; never open a popup."""
        if isinstance(e,CalculationTimeout):
            message="Math ERROR: calculation timed out"
        elif isinstance(e,(CalculatorError,str)):
            message=self._format_error_message(e)
        else:
            LOGGER.error("Unexpected calculator failure", exc_info=(type(e),e,e.__traceback__))
            message="Internal ERROR"
        template_active=self.__dict__.get("template_kind") is not None
        # A template represents one mathematical sentence.  Clearing the
        # focused slot after a validation or worker error hides the actual
        # submitted input and makes correction needlessly difficult.
        if clear_input and not template_active:
            self._clear_active_input_for_error()
        self._clear_modifiers()
        if template_active:
            self._show_template_error(message)
        else:
            self._lcd_message(message)

    def shift_key(self): self.shift=not self.shift; self.alpha=False; self.status_refresh()
    def alpha_key(self): self.alpha=not self.alpha; self.shift=False; self.status_refresh()

    def _active_template_field(self):
        if not self.template_kind:return None
        session=self.__dict__.get("_template_session")
        if isinstance(session,TemplateSession) and session.order==self.template_order:
            session.index=max(0,min(len(session.order)-1,self.template_index))
            return session.active_key
        return self.template_order[self.template_index]

    def _set_template_session(self, kind, fields, order, index, cursors):
        """Install a pure template session while retaining legacy App fields.

        The field dictionaries are intentionally shared with the compatibility
        attributes, so existing private UI seams and the renderer observe the
        same edits without a second synchronization channel.
        """
        session=TemplateSession(kind,fields,order,index,cursors)
        self._template_session=session
        self.template_kind=session.kind
        self.template_fields=session.fields
        self.template_order=session.order
        self.template_index=session.index
        self.template_cursors=session.cursors

    def move(self,d):
        """◀/▶ edit only the current template field; they never change fields."""
        if self._history_lcd_active():
            self._lcd_move(d)
            return
        if self.template_kind:
            # Equation coefficients can be full expressions just like an
            # integrand or ODE coefficient.  Keep ◀/▶ inside the active slot
            # for all of those editors so the focused field's viewport follows
            # its caret; ▲/▼ remains the explicit slot-to-slot navigation.
            if self.template_kind in {"integral", "multiple_integral", "ode", "derivative", "simultaneous"}:
                self.template_cursor_move(d)
            else:
                self.template_move(d)
            return
        if self._lcd_move(d):
            return
        if self._scroll_completed_result(d):
            return
        self.expr.icursor(max(0,min(len(self.expr.get()),self.expr.index(tk.INSERT)+d)))

    def vertical_move(self,d):
        if self._lcd_vertical_move(d):
            return
        if self.template_kind:
            self.template_move(d)
            return
        if d<0 and self.__dict__.get("_pre_equals_recall_available",False):
            expression=self.__dict__.get("_last_submitted_expression")
            if expression:
                self.set_expr(expression)
                self._pre_equals_recall_available=False
                self._set_lcd_label("Edit recalled expression")
                return
        entry = self.__dict__.get("expr")
        if entry is None or not entry.get().strip():
            self.history_move(d)

    def _template_keypress(self,event):
        if not self.template_kind:return None
        if event.keysym in ("Left","Right"):
            self.move(-1 if event.keysym=="Left" else 1); return "break"
        if event.keysym in ("Up","Down"):
            self.vertical_move(-1 if event.keysym=="Up" else 1); return "break"
        if event.keysym=="BackSpace":
            self.template_backspace(delete_forward=False); return "break"
        if event.keysym=="Delete":
            self.template_backspace(delete_forward=True); return "break"
        if event.keysym in ("Return","KP_Enter"):
            self.equals(); return "break"
        if event.keysym=="Escape":
            self.cancel_template(); self.set_expr(""); return "break"
        if event.keysym=="Tab":
            self.template_move(-1 if (event.state & 1) else 1); return "break"
        if event.state & 0x4:return "break"
        if event.char and event.char.isprintable():
            token=self._keyboard_character_token(event.char)
            if token is not None:
                self.template_insert(token)
            return "break"
        return "break"

    def start_integral_template(self, source_expression=None, *, restored_fields=None):
        self._reset_lcd_flow()
        complex_mode=self.__dict__.get("mode","Calculate")=="Complex"
        # Complex integration always starts as a clean dz template; it must
        # not inherit an incidental display value such as the calculator's 1.
        current=(
            str(source_expression).strip()
            if source_expression is not None and not complex_mode
            else (self.expr.get().strip() if not self.template_kind and not complex_mode else "")
        )
        fields={"lower":"","upper":"","body":current,"var":"z" if complex_mode else ""}
        if restored_fields:
            for key in fields:
                if key in restored_fields:
                    fields[key]=str(restored_fields[key])
        # Real-mode differentials stay user-defined.  Complex integration is
        # always with respect to z, so it has no editable differential slot.
        order=["body","lower","upper"]+([] if complex_mode else ["var"])
        self._set_template_session("integral",fields,order,order.index("body"),{k:len(v) for k,v in fields.items()})
        self.render_template()
        self._set_lcd_label("")

    def start_derivative_template(self, source_expression=None):
        self._reset_lcd_flow()
        current=(
            str(source_expression).strip()
            if source_expression is not None
            else (self.expr.get().strip() if not self.template_kind else "")
        )
        fields={"body":current,"var":"z" if self.__dict__.get("mode","Calculate")=="Complex" else "x","point":""}
        order=["body","var","point"]
        self._set_template_session("derivative",fields,order,order.index("body"),{k:len(v) for k,v in fields.items()})
        self.render_template()
        # The formula itself provides the derivative context; leaving the
        # result row blank prevents narrow LCD labels from colliding with it.
        self._set_lcd_label("")

    def start_ode_template(self, equation=None, dependent_variable="y", independent_variable="x", initial_conditions=""):
        """Open either the compact coefficient editor or a structured ODE recall form."""
        self._reset_lcd_flow()
        if equation is not None:
            fields={
                "equation":str(equation),
                "dependent_variable":str(dependent_variable),
                "independent_variable":str(independent_variable),
                "initial_conditions":str(initial_conditions),
            }
            order=["equation","dependent_variable","independent_variable","initial_conditions"]
            self._set_template_session("ode_details",fields,order,0,{key:len(value) for key,value in fields.items()})
            self.render_template()
            self._set_lcd_label("")
            return
        fields={"ode_a":"","ode_b":"","ode_c":"","ode_f":""}
        order=["ode_a","ode_b","ode_c","ode_f"]
        self._set_template_session("ode",fields,order,0,{key:0 for key in order})
        self.render_template()
        self._set_lcd_label("")

    def start_polynomial_template(self, degree):
        """Open a second- through fourth-degree polynomial with navigable slots."""
        if degree not in {2,3,4}:
            raise CalculatorError("Argument ERROR: polynomial degree must be 2 to 4")
        self._reset_lcd_flow()
        fields={"degree":degree}
        order=[]
        for index in range(degree+1):
            key=f"polynomial_{index}"
            fields[key]=""
            order.append(key)
        self._set_template_session("polynomial",fields,order,0,{key:0 for key in order})
        self.render_template()
        self._set_lcd_label("")

    def start_simultaneous_template(self, size):
        """Open one navigable equation row of a 2×2–4×4 linear system."""
        if size not in {2,3,4}:
            raise CalculatorError("Argument ERROR: simultaneous unknowns must be 2 to 4")
        self._reset_lcd_flow()
        fields={"size":size,"completed_rows":0}
        order=[]
        for row in range(size):
            for column in range(size):
                key=f"simul_{row}_{column}"
                fields[key]=""
                order.append(key)
            key=f"simul_b_{row}"
            fields[key]=""
            order.append(key)
        self._set_template_session("simultaneous",fields,order,0,{key:0 for key in order})
        self.render_template()
        self._set_lcd_label("")

    def start_multiple_integral_template(self, order, *, restored_fields=None):
        """Open an editable natural multi-integral with numbered LCD layers."""
        if order not in {"double", "triple"}:
            raise CalculatorError("Argument ERROR: unsupported integral order")
        self._reset_lcd_flow()
        current=""
        if not self.__dict__.get("template_kind"):
            current=self.expr.get().strip()
        layer_names=["outer", "inner"] if order=="double" else ["outer", "middle", "inner"]
        fields={"body":current, "order":order}
        for name in layer_names:
            fields[f"{name}_lower"]=""
            fields[f"{name}_upper"]=""
            fields[f"{name}_var"]=""
        if restored_fields:
            for key in fields:
                if key != "order" and key in restored_fields:
                    fields[key]=str(restored_fields[key])
        template_order=["body"]
        for name in reversed(layer_names):
            template_order.extend((f"{name}_lower", f"{name}_upper", f"{name}_var"))
        self._set_template_session(
            "multiple_integral",fields,template_order,0,
            {key:len(value) for key,value in fields.items() if key != "order"},
        )
        self.render_template()
        self._set_lcd_label("")

    def _canvas_caret_x(self, text, cursor, font_desc, start_x):
        try:
            font=tkfont.Font(font=font_desc)
            return start_x+font.measure(text[:cursor])
        except Exception:
            return start_x+cursor*10

    def _template_text_view(self,text,cursor,font_desc,max_width,empty_placeholder="□"):
        """Return a cursor-visible one-line slice for a constrained canvas field."""
        try:
            measure=tkfont.Font(font=font_desc).measure
        except Exception:
            measure=lambda value:len(value)*10
        return caret_text_view(text,cursor,max_width,measure,empty_placeholder)

    def _draw_edit_text(self,c,key,text,x,y,font_desc,box=None,anchor="w",max_text_width=None,empty_placeholder="□"):
        active=not self.__dict__.get("_template_read_only",False) and self._active_template_field()==key
        cursor=max(0,min(len(text),self.template_cursors.get(key,len(text))))
        shown,caret_offset=self._template_text_view(text,cursor,font_desc,max_text_width,empty_placeholder)
        if box and active:
            c.create_rectangle(*box,outline="#222222",width=max(1,int(round(self._sp(2)))))
        c.create_text(x,y,text=shown,font=font_desc,anchor=anchor,fill="#111111")
        if active:
            cx=x+caret_offset
            half=self._sp(13)
            c.create_line(cx,y-half,cx,y+half,fill="#111111",width=max(1,int(round(self._sp(2)))))

    def render_template(self):
        if not self.template_kind:
            return
        f=self.template_fields
        S=self._sp

        if getattr(self,"skin_mode",False):
            with suppress(Exception):
                self.expr.place_forget()
            sx1,sy1=S(40),S(128); sx2=S(435)
            self.template_canvas.place(
                x=sx1+S(7), y=sy1+S(30),
                width=(sx2-sx1)-S(14), height=S(92)
            )
            self.result.place(
                x=sx1+S(7), y=sy1+S(126),
                width=(sx2-sx1)-S(14), height=S(23)
            )
        else:
            with suppress(Exception):
                self.expr.pack_forget()
            if not self.template_canvas.winfo_ismapped():
                self.template_canvas.pack(fill="x",padx=7,pady=(1,2),before=self.result)

        c=self.template_canvas
        c.delete("all")
        # Work directly in physical scaled pixels so the 100% design is preserved.
        # In skin mode the template canvas occupies the LCD's inner width
        # (395 - 14 = 381 logical pixels), not the full 430 px LCD panel.
        # Using the panel width positions the differential variable outside
        # the canvas, clipping the final "x" in "dx".
        # The canvas is placed at the LCD's 381 px inner width in skin mode.
        # Derive every integral position from that same logical width so a UI
        # scale change keeps the full differential visible.
        w=int(round(S(381))) if getattr(self,"skin_mode",False) else max(c.winfo_width(),int(round(S(480))))

        if self.template_kind=="integral":
            c.config(height=max(1,int(round(S(72)))))
            c.create_text(S(18),S(36),text="∫",font=self._font("math",46),anchor="w",fill="#111111")
            self._draw_edit_text(
                c,"upper",f.get("upper",""),S(46),S(13),
                self._font("lcd",12,"bold"),
                (S(40),S(2),S(139),S(25)),
                max_text_width=S(139)-S(46)
            )
            self._draw_edit_text(
                c,"lower",f.get("lower",""),S(46),S(59),
                self._font("lcd",12,"bold"),
                (S(40),S(47),S(139),S(70)),
                max_text_width=S(139)-S(46)
            )

            body_x=S(150)
            close_x=w-S(88)
            body_right=max(body_x+S(12),close_x-S(7))
            self._draw_edit_text(
                c,"body",f.get("body",""),body_x,S(36),
                self._font("lcd",19),
                (S(145),S(21),body_right,S(52)),
                max_text_width=body_right-body_x
            )
            differential_x=min(close_x+max(1,S(1)),w-S(35))
            c.create_text(differential_x,S(36),text="d",font=self._font("lcd",17),anchor="w",fill="#111111")
            var_x=min(differential_x+S(20),w-S(35))
            self._draw_edit_text(
                c,"var",f.get("var","") ,var_x,S(36),
                self._font("lcd",17,"bold"),
                (min(differential_x+S(15),w-S(55)),S(22),w-S(7),S(52)),
                max_text_width=max(1,(w-S(7))-var_x)
            )
        elif self.template_kind=="multiple_integral":
            c.config(height=max(1,int(round(S(84)))) )
            order=f["order"]
            layer_names=["outer", "inner"] if order=="double" else ["outer", "middle", "inner"]
            count=len(layer_names)
            sign_spacing=S(54)
            for index,name in enumerate(layer_names):
                sign_x=S(10)+index*sign_spacing
                c.create_text(sign_x,S(40),text="∫",font=self._font("math",37),anchor="w",fill="#111111")
                self._draw_edit_text(
                    c,f"{name}_upper",f[f"{name}_upper"],sign_x+S(27),S(15),
                    self._font("lcd",10,"bold"),(sign_x+S(24),S(4),sign_x+S(67),S(25)),max_text_width=S(40),
                )
                self._draw_edit_text(
                    c,f"{name}_lower",f[f"{name}_lower"],sign_x+S(27),S(63),
                    self._font("lcd",10,"bold"),(sign_x+S(24),S(51),sign_x+S(67),S(76)),max_text_width=S(40),
                )
            body_x=S(12)+count*sign_spacing+S(6)
            # Each d□ pair owns its own focus box.  Leave enough room for
            # three full-size differentials while keeping the integrand field
            # visible in the triple-integral layout.
            differential_count=len(layer_names)
            pair_width=S(30)
            diff_x=w-S(4)-pair_width*differential_count
            body_right=max(body_x+S(12),diff_x-S(5))
            self._draw_edit_text(
                c,"body",f.get("body",""),body_x,S(40),self._font("lcd",17),
                (body_x-S(4),S(25),body_right,S(54)),max_text_width=body_right-body_x,
            )
            for index,name in enumerate(reversed(layer_names)):
                pair_x=diff_x+index*pair_width
                c.create_text(pair_x,S(40),text="d",font=self._font("lcd",17,"bold"),anchor="w",fill="#111111")
                variable_x=pair_x+S(15)
                self._draw_edit_text(
                    c,f"{name}_var",f[f"{name}_var"],variable_x,S(40),
                    self._font("lcd",17,"bold"),
                    (variable_x-S(3),S(24),variable_x+S(15),S(56)),max_text_width=S(14),
                )
        elif self.template_kind=="ode":
            # A four-term ODE does not fit legibly on the calculator LCD as
            # one line.  Keep the mathematical sentence intact but split it
            # into two roomy rows, so coefficient expressions never collide.
            c.config(height=max(1,int(round(S(72)))))
            coefficient_font=self._font("lcd",11,"bold")
            formula_font=self._font("lcd",14,"bold")
            def draw_ode_slot(key,left,right,y,suffix=""):
                box=(left,y-S(13),right,y+S(13))
                c.create_rectangle(*box,outline="#9b9b9b",width=max(1,int(round(S(1)))))
                self._draw_edit_text(
                    c,key,f.get(key,""),left+S(4),y,coefficient_font,box,
                    max_text_width=max(S(6),right-left-S(8)),empty_placeholder="",
                )
                if suffix:
                    c.create_text(right+S(4),y,text=suffix,font=formula_font,anchor="w",fill="#111111")

            top_y=S(20); bottom_y=S(52); coefficient_width=S(76)
            draw_ode_slot("ode_a",S(6),S(6)+coefficient_width,top_y,"·y''")
            # The superscript marks in y'' need their own breathing room:
            # placing the following plus at 116 made it appear as y''+.
            # Keep a real pixel gap even on the smallest supported scale.  At
            # 60%, the earlier logical 130px position rounded against y''.
            c.create_text(S(138),top_y,text="+",font=formula_font,anchor="w",fill="#111111")
            draw_ode_slot("ode_b",S(158),S(158)+coefficient_width,top_y,"·y'")
            c.create_text(S(6),bottom_y,text="+",font=formula_font,anchor="w",fill="#111111")
            draw_ode_slot("ode_c",S(24),S(24)+coefficient_width,bottom_y,"·y")
            c.create_text(S(130),bottom_y,text="=",font=formula_font,anchor="w",fill="#111111")
            rhs_left=S(150); rhs_right=min(w-S(6),rhs_left+S(120))
            draw_ode_slot("ode_f",rhs_left,rhs_right,bottom_y)
        elif self.template_kind=="ode_details":
            c.config(height=max(1,int(round(S(84)))))
            label_font=self._font("lcd",10,"bold")
            value_font=self._font("lcd",12,"bold")
            rows=(
                ("equation","ODE",S(15),S(84),w-S(7)),
                ("dependent_variable","y",S(43),S(32),S(125)),
                ("independent_variable","x",S(43),S(155),S(248)),
                ("initial_conditions","IC",S(70),S(84),w-S(7)),
            )
            for key,label,y,left,right in rows:
                c.create_text(S(8),y,text=f"{label}:",font=label_font,anchor="w",fill="#333333")
                box=(left,y-S(11),right,y+S(11))
                self._draw_edit_text(
                    c,key,f.get(key,""),left+S(3),y,value_font,box,
                    max_text_width=max(S(8),right-left-S(6)),empty_placeholder="",
                )
        elif self.template_kind=="polynomial":
            c.config(height=max(1,int(round(S(72 if f["degree"] == 4 else 62)))))
            coefficient_font=self._font("lcd",12,"bold")
            formula_font=self._font("lcd",14,"bold")
            degree=f["degree"]
            if degree==4:
                # Quartics need five readable boxes.  A 3+2 layout preserves
                # the 381px calculator LCD width without collapsing terms.
                slots=(
                    (0,S(6),S(58),"x⁴",S(20)),
                    (1,S(108),S(160),"x³",S(20)),
                    (2,S(210),S(262),"x²",S(20)),
                    (3,S(54),S(112),"x",S(52)),
                    (4,S(182),S(240),"",S(52)),
                )
                for index,left,right,suffix,y in slots:
                    key=f"polynomial_{index}"
                    box=(left,y-S(13),right,y+S(13))
                    c.create_rectangle(*box,outline="#9b9b9b",width=max(1,int(round(S(1)))))
                    self._draw_edit_text(
                        c,key,f.get(key,""),left+S(4),y,coefficient_font,box,
                        max_text_width=max(S(6),right-left-S(8)),empty_placeholder="",
                    )
                    if suffix:
                        c.create_text(right+S(3),y,text=suffix,font=formula_font,anchor="w",fill="#111111")
                for x,y in ((S(83),S(20)),(S(185),S(20)),(S(30),S(52)),(S(148),S(52))):
                    c.create_text(x,y,text="+",font=formula_font,anchor="w",fill="#111111")
                c.create_text(S(270),S(52),text="= 0",font=formula_font,anchor="w",fill="#111111")
                c.focus_set()
                return
            slots=(
                ((S(6),S(58),"x³"),(S(99),S(151),"x²"),(S(192),S(244),"x"),(S(276),S(328),""))
                if degree==3 else
                ((S(22),S(82),"x²"),(S(121),S(181),"x"),(S(220),S(280),""))
            )
            plus_x=(S(84),S(177),S(261)) if degree==3 else (S(106),S(205))
            equals_x=S(334) if degree==3 else S(295)
            for index,(left,right,suffix) in enumerate(slots):
                key=f"polynomial_{index}"
                box=(left,S(16),right,S(48))
                c.create_rectangle(*box,outline="#9b9b9b",width=max(1,int(round(S(1)))))
                self._draw_edit_text(
                    c,key,f.get(key,""),left+S(4),S(32),coefficient_font,box,
                    max_text_width=max(S(6),right-left-S(8)),empty_placeholder="",
                )
                if suffix:
                    c.create_text(right+S(4),S(32),text=suffix,font=formula_font,anchor="w",fill="#111111")
            for x in plus_x:
                c.create_text(x,S(32),text="+",font=formula_font,anchor="w",fill="#111111")
            c.create_text(equals_x,S(32),text="= 0",font=formula_font,anchor="w",fill="#111111")
        elif self.template_kind=="simultaneous":
            size=cast(int, f["size"])
            active_index=self.template_index
            row=active_index//(size+1)
            coefficient_font=self._font("lcd",11,"bold")
            formula_font=self._font("lcd",13,"bold")
            if size==4:
                # Two terms per row retain full editable boxes for a 4×4
                # system rather than nesting five fields into one thin line.
                c.config(height=max(1,int(round(S(72)))))
                box_width=S(76)

                def draw_simul_slot(column,left,y):
                    key=f"simul_{row}_{column}"
                    right=left+box_width
                    box=(left,y-S(13),right,y+S(13))
                    c.create_rectangle(*box,outline="#9b9b9b",width=max(1,int(round(S(1)))))
                    self._draw_edit_text(
                        c,key,f.get(key,""),left+S(3),y,coefficient_font,box,
                        max_text_width=max(S(6),box_width-S(6)),empty_placeholder="",
                    )
                    c.create_text(right+S(3),y,text=f"x{column+1}",font=formula_font,anchor="w",fill="#111111")

                top_y=S(20); bottom_y=S(52)
                draw_simul_slot(0,S(6),top_y)
                c.create_text(S(110),top_y,text="+",font=formula_font,anchor="w",fill="#111111")
                draw_simul_slot(1,S(128),top_y)
                c.create_text(S(6),bottom_y,text="+",font=formula_font,anchor="w",fill="#111111")
                draw_simul_slot(2,S(24),bottom_y)
                c.create_text(S(128),bottom_y,text="+",font=formula_font,anchor="w",fill="#111111")
                draw_simul_slot(3,S(146),bottom_y)
                c.create_text(S(250),bottom_y,text="=",font=formula_font,anchor="w",fill="#111111")
                rhs_left=S(270); rhs_right=min(w-S(6),rhs_left+S(82))
                rhs_key=f"simul_b_{row}"
                rhs_box=(rhs_left,bottom_y-S(13),rhs_right,bottom_y+S(13))
                c.create_rectangle(*rhs_box,outline="#9b9b9b",width=max(1,int(round(S(1)))))
                self._draw_edit_text(
                    c,rhs_key,f.get(rhs_key,""),rhs_left+S(3),bottom_y,coefficient_font,rhs_box,
                    max_text_width=max(S(6),rhs_right-rhs_left-S(6)),empty_placeholder="",
                )
            else:
                # A 2×2 equation fits on one comfortably spaced row.  A 3×3
                # equation does not: squeezing it used to overlap x1/x2 with
                # the following plus sign.  Give its final term a second row,
                # matching the clear two-row treatment used by the 4×4 form.
                box_width=S(70)

                def draw_simul_slot(column,left,y):
                    key=f"simul_{row}_{column}"
                    right=left+box_width
                    box=(left,y-S(13),right,y+S(13))
                    c.create_rectangle(*box,outline="#9b9b9b",width=max(1,int(round(S(1)))))
                    self._draw_edit_text(
                        c,key,f.get(key,""),left+S(3),y,coefficient_font,box,
                        max_text_width=max(S(6),box_width-S(6)),empty_placeholder="",
                    )
                    c.create_text(right+S(4),y,text=f"x{column+1}",font=formula_font,anchor="w",fill="#111111")

                if size==2:
                    c.config(height=max(1,int(round(S(62)))))
                    row_y=S(32)
                    draw_simul_slot(0,S(6),row_y)
                    c.create_text(S(108),row_y,text="+",font=formula_font,anchor="w",fill="#111111")
                    draw_simul_slot(1,S(126),row_y)
                    c.create_text(S(228),row_y,text="=",font=formula_font,anchor="w",fill="#111111")
                    rhs_left=S(248); rhs_right=min(w-S(6),rhs_left+S(100))
                    rhs_key=f"simul_b_{row}"
                    rhs_box=(rhs_left,row_y-S(13),rhs_right,row_y+S(13))
                else:
                    c.config(height=max(1,int(round(S(72)))))
                    top_y=S(20); bottom_y=S(52)
                    draw_simul_slot(0,S(6),top_y)
                    c.create_text(S(108),top_y,text="+",font=formula_font,anchor="w",fill="#111111")
                    draw_simul_slot(1,S(126),top_y)
                    c.create_text(S(6),bottom_y,text="+",font=formula_font,anchor="w",fill="#111111")
                    draw_simul_slot(2,S(24),bottom_y)
                    c.create_text(S(126),bottom_y,text="=",font=formula_font,anchor="w",fill="#111111")
                    rhs_left=S(146); rhs_right=min(w-S(6),rhs_left+S(120))
                    rhs_key=f"simul_b_{row}"
                    rhs_box=(rhs_left,bottom_y-S(13),rhs_right,bottom_y+S(13))

                c.create_rectangle(*rhs_box,outline="#9b9b9b",width=max(1,int(round(S(1)))))
                self._draw_edit_text(
                    c,rhs_key,f.get(rhs_key,""),rhs_left+S(3),
                    row_y if size==2 else bottom_y,coefficient_font,rhs_box,
                    max_text_width=max(S(6),rhs_right-rhs_left-S(6)),empty_placeholder="",
                )
        else:
            c.config(height=max(1,int(round(S(62)))))
            var=f.get("var") or "x"
            c.create_text(S(12),S(31),text=f"d/d{var} ",font=self._font("lcd",17,"bold"),anchor="w",fill="#111111")
            body_x=S(70)
            close_x=w-S(138)
            body_right=max(body_x+S(12),close_x-S(7))
            self._draw_edit_text(
                c,"body",f.get("body",""),body_x,S(31),
                self._font("lcd",18),
                (S(64),S(16),body_right,S(48)),
                max_text_width=body_right-body_x
            )
            c.create_text(close_x,S(31),text=f"| {var}=",font=self._font("lcd",16),anchor="w",fill="#111111")
            point_x=min(close_x+S(52),w-S(56))
            self._draw_edit_text(
                c,"point",f.get("point",""),point_x,S(31),
                self._font("lcd",16,"bold"),
                (point_x-S(4),S(17),w-S(8),S(48)),
                max_text_width=max(1,(w-S(8))-point_x)
            )
            if self._active_template_field()=="var":
                c.create_rectangle(
                    w-S(70),S(1),w-S(8),S(16),
                    outline="#222222",width=max(1,int(round(S(1))))
                )
            c.create_text(w-S(12),S(8),text=f"d/d{var}",font=self._font("lcd",9),anchor="e",fill="#333333")
        c.focus_set()

    def template_cursor_move(self, direction):
        """Move the caret inside the active LCD field without crossing its edge."""
        if not self.template_kind:
            return
        key = cast(str, self._active_template_field())
        text = str(self.template_fields.get(key, ""))
        cursor = self.template_cursors.get(key, len(text))
        self.template_cursors[key] = max(0, min(len(text), cursor + direction))
        self.render_template()

    def template_move(self,d):
        if not self.template_kind:return
        self.template_index=(self.template_index+d)%len(self.template_order)
        session=self.__dict__.get("_template_session")
        if isinstance(session,TemplateSession):
            session.index=self.template_index
        key=cast(str, self._active_template_field())
        self.template_cursors.setdefault(key,len(str(self.template_fields.get(key,""))))
        self.render_template()

    def template_insert(self,s):
        if not self.template_kind:return
        self._clear_template_error()
        # ``self.template_kind`` truthy here guarantees a non-None field key.
        key=cast(str, self._active_template_field())
        if key=="var" or key.endswith("_var"):
            candidate=s.strip()
            if candidate and candidate[-1].isalpha():
                self.template_fields[key]=candidate[-1]
                self.template_cursors[key]=1
        else:
            text=str(self.template_fields.get(key,""))
            cur=max(0,min(len(text),self.template_cursors.get(key,len(text))))
            self.template_fields[key]=text[:cur]+s+text[cur:]
            self.template_cursors[key]=cur+len(s)
        self.render_template()

    def template_backspace(self,delete_forward=False):
        if not self.template_kind:return
        self._clear_template_error()
        key=cast(str, self._active_template_field())
        if key=="var" or key.endswith("_var"):
            self.template_fields[key]=""; self.template_cursors[key]=0; self.render_template(); return
        text=str(self.template_fields.get(key,""))
        cur=max(0,min(len(text),self.template_cursors.get(key,len(text))))
        if delete_forward:
            if cur<len(text): text=text[:cur]+text[cur+1:]
        else:
            if cur>0:
                text=text[:cur-1]+text[cur:]; cur-=1
        self.template_fields[key]=text; self.template_cursors[key]=cur
        self.render_template()

    @staticmethod
    def _repair_integral_body(text):
        return entry_rules.repair_integral_body(text)

    def evaluate_template(self):
        kind=self.template_kind; f=dict(self.template_fields)
        if kind=="integral":
            body=self._repair_integral_body(f.get("body", "")); var=str(f.get("var","")).strip()
            self.template_fields["body"]=body
            self.template_cursors["body"]=min(self.template_cursors.get("body",len(body)),len(body))
            lo=str(f.get("lower","")).strip(); hi=str(f.get("upper","")).strip()
            if not body: raise CalculatorError("Syntax ERROR: Integral function is empty")
            if len(var)!=1 or not var.isalpha(): raise CalculatorError("Argument ERROR: Enter the differential variable")
            if bool(lo)!=bool(hi): raise CalculatorError("Argument ERROR: Enter both lower and upper bounds, or leave both blank")
            if lo and hi:
                operation="complex_definite_integral" if self.mode=="Complex" else "definite_integral_result"

                def show_integral(result):
                    if self.mode == "Complex":
                        self._show_completed_result(f"∫={self.core.format_result(result, True)}")
                    elif result.exists:
                        suffix = "Improper integral • Convergent" if result.metadata.get("kind") == "improper" else "Definite integral"
                        # The engine retains exact symbolic values for history
                        # and subsequent calculations; the LCD result is a
                        # calculator display, so show a directly usable decimal.
                        self._show_completed_result(f"∫={self.core.format_result(result.value, True)}\n{suffix}")
                    elif result.status.name == "INTEGRAL_DIVERGES":
                        self._show_completed_result("DIVERGES\nImproper integral • Divergent")
                    elif result.status.name == "INTEGRAL_UNDEFINED":
                        self._show_completed_result("UNDEFINED\nIntegral outside real domain")
                    else:
                        self._show_completed_result("UNDETERMINED\nImproper integral • Convergence undetermined")
                    self.cancel_template()

                self._run_background_calculation(
                    operation, (body,lo,hi,var),
                    show_integral,
                )
            else:
                self._run_background_calculation(
                    "symbolic_integral", (body,var),
                    lambda r:(self._show_completed_result(f"{self.core.format_result(r)} + C"),self.cancel_template()),
                )
            return
        if kind=="multiple_integral":
            body=self._repair_integral_body(f.get("body", ""))
            if not body:
                raise CalculatorError("Syntax ERROR: Integral function is empty")
            order=f["order"]
            layer_names=["outer", "inner"] if order=="double" else ["outer", "middle", "inner"]
            bound_keys=[f"{name}_{side}" for name in layer_names for side in ("lower","upper")]
            variable_keys=[f"{name}_var" for name in layer_names]
            if any(not str(f.get(key,"")).strip() for key in bound_keys):
                raise CalculatorError("Argument ERROR: Enter every integral bound")
            if any(len(str(f.get(key,"")).strip())!=1 or not str(f.get(key,"")).strip().isalpha() for key in variable_keys):
                raise CalculatorError("Argument ERROR: Enter every differential variable")
            if order=="double":
                method="double_integral"
                args=(
                    body,f["outer_lower"],f["outer_upper"],f["inner_lower"],f["inner_upper"],
                    f["outer_var"],f["inner_var"],
                )
                prefix="∫∫"
            else:
                method="triple_integral"
                args=(
                    body,f["outer_lower"],f["outer_upper"],f["middle_lower"],f["middle_upper"],
                    f["inner_lower"],f["inner_upper"],f["outer_var"],f["middle_var"],f["inner_var"],
                )
                prefix="∫∫∫"
            self._run_background_calculation(
                method,args,lambda result:(self._show_completed_result(f"{prefix}={self.core.format_result(result,True)}"),self.cancel_template()),
            )
            return
        if kind=="ode":
            coefficients={key:str(f.get(key,"")).strip() for key in ("ode_a","ode_b","ode_c","ode_f")}
            if any(not value for value in coefficients.values()):
                raise CalculatorError("Argument ERROR: Enter every ODE coefficient")
            equation=(
                f"({coefficients['ode_a']})*d2y/dx2+({coefficients['ode_b']})*dy/dx"
                f"+({coefficients['ode_c']})*y=({coefficients['ode_f']})"
            )
            self._run_background_calculation(
                "solve_ode",(equation,),
                lambda result:(self._show_completed_result(self.core.format_result(result)),self.cancel_template()),
            )
            return
        if kind=="ode_details":
            equation=str(f.get("equation","")).strip()
            dependent=str(f.get("dependent_variable","")).strip()
            independent=str(f.get("independent_variable","")).strip()
            conditions=str(f.get("initial_conditions","")).strip()
            if not equation:
                raise CalculatorError("Syntax ERROR: Differential equation is empty")
            if len(dependent)!=1 or not dependent.isalpha() or len(independent)!=1 or not independent.isalpha():
                raise CalculatorError("Argument ERROR: Enter one-letter dependent and independent variables")
            self._run_background_calculation(
                "solve_ode",
                (equation,dependent,independent,conditions or None),
                lambda result:(self._show_completed_result(self.core.format_result(result)),self.cancel_template()),
            )
            return
        if kind=="polynomial":
            degree=cast(int, f["degree"])
            coefficients=[
                self._lcd_real(f.get(f"polynomial_{index}",""),f"coefficient {degree-index}")
                for index in range(degree+1)
            ]
            if coefficients[0]==0:
                raise CalculatorError("Argument ERROR: leading polynomial coefficient cannot be zero")
            # Roots are individual LCD result rows so ▲/▼ visits x1, x2, …
            # without forcing a long polynomial result into one tiny line.
            self._lcd_flow={"mode":"Equation/Func","values":{},"draft":{},"last_error":""}
            self._lcd_show_results("POLYNOMIAL",self._polynomial_result_lines(degree,coefficients))
            self.cancel_template()
            return
        if kind=="simultaneous":
            size=cast(int, f["size"])
            completed_rows=int(cast(Any, f.get("completed_rows",0)))
            current_row=min(max(completed_rows,0),size-1)
            current_row_values=[
                f.get(f"simul_{current_row}_{column}","") for column in range(size)
            ]+[f.get(f"simul_b_{current_row}","")]
            if any(not str(value).strip() for value in current_row_values):
                raise CalculatorError(f"Argument ERROR: Enter every value in equation {current_row+1}")
            if current_row<size-1:
                self.template_fields["completed_rows"]=current_row+1
                self.template_index=(current_row+1)*(size+1)
                self.render_template()
                return
            matrix=np.array([
                [self._lcd_real(f.get(f"simul_{row}_{column}",""),f"x{column+1} coefficient") for column in range(size)]
                for row in range(size)
            ])
            constants=np.array([
                self._lcd_real(f.get(f"simul_b_{row}",""),f"equation {row+1} result") for row in range(size)
            ])
            result=self.core.simultaneous(matrix,constants)
            self._lcd_flow={"mode":"Equation/Func","values":{},"draft":{},"last_error":""}
            self._lcd_show_results("SIMULTANEOUS",[f"x{index+1} = {value:.12g}" for index,value in enumerate(result)])
            self.cancel_template()
            return
        elif kind=="derivative":
            body=str(f.get("body","")).strip(); var=str(f.get("var") or "x").strip(); point=str(f.get("point","")).strip()
            if not body: raise CalculatorError("Syntax ERROR: Derivative function is empty")
            if self.__dict__.get("mode","Calculate")=="Complex":
                def complex_success(result):
                    value=getattr(result,"value",None)
                    text=self.core.format_result(value) if value is not None else result.message_code.replace("_"," ")
                    self._show_completed_result(f"d/d{var}={text}")
                    self.cancel_template()
                self._run_background_calculation("complex_derivative_result", (body,var,point or None), complex_success)
            elif point:
                self._run_background_calculation("derivative", (body,point,var), lambda r:(self._show_completed_result(f"d/d{var}={self.core.format_result(r,True)}"), self.cancel_template()))
            else:
                self._run_background_calculation("symbolic_derivative", (body,var), lambda r:(self._show_completed_result(self.core.format_result(r)), self.cancel_template()))
        if not self.__dict__.get("_calculation_busy",False): self.cancel_template()

    def _recall_structured_history(self, entry):
        """Restore user-entered calculus fields; never reverse-parse display text."""
        metadata = entry.metadata
        if entry.kind in {"integral_single", "integral_indefinite"}:
            restored_fields={"var":str((metadata.get("variables") or ["x"])[0])}
            bounds = metadata.get("bounds")
            if isinstance(bounds, tuple) and bounds and isinstance(bounds[0], dict):
                restored_fields["lower"] = str(bounds[0].get("lower", ""))
                restored_fields["upper"] = str(bounds[0].get("upper", ""))
            starter=self.start_integral_template
            if getattr(starter,"__func__",None) is App.start_integral_template:
                starter(metadata.get("integrand", ""),restored_fields=restored_fields)
            else:
                # Preserve lightweight test and extension seams that still
                # provide the original one-argument starter contract.
                starter(metadata.get("integrand", ""))
                self.template_fields.update(restored_fields)
                self.template_cursors={key:len(str(value)) for key,value in self.template_fields.items()}
            self._show_completed_result(entry.result)
            return True
        if entry.kind == "derivative":
            self.start_derivative_template(metadata.get("expression", ""))
            self.template_fields["var"] = str(metadata.get("variable", "x"))
            point = metadata.get("evaluation_point")
            self.template_fields["point"] = "" if point is None else str(point)
            self.template_cursors = {key: len(str(value)) for key, value in self.template_fields.items()}
            self._show_completed_result(entry.result)
            return True
        if entry.kind in {"integral_double", "integral_triple"}:
            order = "double" if entry.kind == "integral_double" else "triple"
            restored_fields={"body":str(metadata.get("integrand", ""))}
            bounds = metadata.get("bounds")
            if isinstance(bounds, tuple):
                names = ["outer", "inner"] if order == "double" else ["outer", "middle", "inner"]
                for name, bound in zip(names, bounds, strict=False):
                    if isinstance(bound, dict):
                        restored_fields[f"{name}_var"] = str(bound.get("variable", ""))
                        restored_fields[f"{name}_lower"] = str(bound.get("lower", ""))
                        restored_fields[f"{name}_upper"] = str(bound.get("upper", ""))
            starter=self.start_multiple_integral_template
            if getattr(starter,"__func__",None) is App.start_multiple_integral_template:
                starter(order,restored_fields=restored_fields)
            else:
                starter(order)
                self.template_fields.update(restored_fields)
                self.template_cursors={key:len(str(value)) for key,value in self.template_fields.items() if key!="order"}
            self._show_completed_result(entry.result)
            return True
        if entry.kind == "ode":
            self.start_ode_template(
                metadata.get("equation", ""),
                metadata.get("dependent_function", "y"),
                metadata.get("independent_variable", "x"),
                metadata.get("initial_conditions", ""),
            )
            self._show_completed_result(entry.result)
            return True
        if entry.kind == "complex_calculus":
            operation = metadata.get("operation")
            if operation == "derivative":
                self.start_derivative_template(metadata.get("expression", ""))
                self.template_fields["var"] = str(metadata.get("variable", "z"))
                point = metadata.get("point")
                self.template_fields["point"] = "" if point is None else str(point)
            elif operation == "integral":
                self.start_integral_template(metadata.get("integrand", ""))
                self.template_fields["var"] = str(metadata.get("variable", "z"))
                self.template_fields["lower"] = str(metadata.get("lower", ""))
                self.template_fields["upper"] = str(metadata.get("upper", ""))
            else:
                self.set_expr(str(metadata.get("expression", entry.expression)))
            self.template_cursors = {key: len(str(value)) for key, value in self.template_fields.items()}
            self._show_completed_result(entry.result)
            return True
        return False

    def history_move(self,d):
        entries=self._history_entries()
        if not entries or d==0:
            return
        cursor=max(0,min(len(entries),self.__dict__.get("history_pos",len(entries))))
        if d<0:
            cursor=len(entries)-1 if cursor==len(entries) else max(0,cursor-1)
        else:
            if cursor==len(entries):
                return
            cursor=min(len(entries),cursor+1)
        self.history_pos=cursor
        if cursor==len(entries):
            return
        entry = entries[cursor]
        if not self._recall_structured_history(entry):
            self._recall_expression(entry.expression)
            self._show_completed_result(entry.result)

    def show_history(self):
        if self.__dict__.get("mode","Calculate") not in {"Calculate","Complex"}:
            self.consume()
            return
        self._start_lcd_flow("History")
        self.consume()

    def del_key(self):
        if self._history_lcd_active():
            self.consume()
            return
        if self.template_kind:
            self.template_backspace(delete_forward=False); self.consume(); return
        flow=self.__dict__.get("_lcd_flow")
        if flow and flow.get("phase")=="sheet" and flow.get("sheet_phase")=="browse":
            flow["editing"]=True
        if self.shift: self.overwrite=not self.overwrite; self.consume(); return
        if self.alpha:
            if self.undo:
                cur=self._expression_document_for_entry() if self._document_editing_active() else self.expr.get()
                prev=self.undo.pop(); self.undo.append(cur)
                if isinstance(prev,ExpressionDocument):
                    self._set_expression_document(prev)
                else:
                    self.set_expr(prev)
            self.consume(); return
        self._begin_independent_edit()
        self._lcd_prepare_direct_entry()
        p=self.expr.index(tk.INSERT)
        if p>0:
            self.remember()
            if self._document_editing_active():
                self._set_expression_document(self._expression_document_for_entry().delete_backward(p),p-1)
            else:
                self.expr.delete(p-1,p)

    def _reset_active_mode_after_ac(self):
        """Return to the active mode's clean starting screen after AC/cancel."""
        self.cancel_template()
        self._reset_lcd_flow()
        self.set_expr("")
        self._reset_history_browsing()
        if self.mode in {"Calculate","Complex"}:
            self._set_lcd_label("0")
        elif self.mode in self.LCD_WORKSPACE_MODES:
            self._start_lcd_flow(self.mode)
        else:
            self._set_lcd_label(self.MODE_HINTS.get(self.mode,""))
        self.consume()

    def ac_key(self):
        # Cancellation deliberately wins over SHIFT (whose normal AC action is
        # close) and over every template/LCD flow while a calculation runs.
        if self.__dict__.get("_calculation_busy",False):
            self.calculation_controller.cancel()
            self._reset_active_mode_after_ac()
            return
        if self.shift: self._on_close(); return
        flow=self.__dict__.get("_lcd_flow")
        if flow:
            self._reset_active_mode_after_ac()
            return
        self._reset_active_mode_after_ac()

    def _clear_before_interaction_transition(self):
        """Apply AC-style cancellation and clearing before opening new work."""
        entry=self.__dict__.get("expr")
        source=entry.get().strip() if entry is not None else ""
        controller=self.__dict__.get("calculation_controller")
        if controller and (
            self.__dict__.get("_calculation_busy",False) or getattr(controller,"busy",False)
        ):
            controller.cancel()
        self._calculation_busy=False
        self.cancel_template()
        App._reset_lcd_flow(self)
        App._begin_independent_edit(self)
        if entry is not None:
            App._set_lcd_expression(self,"")
            self._set_lcd_label("")
        elif "result" in self.__dict__:
            # Keep minimal non-Tk contract doubles compatible with the same
            # reset semantics without asking them to implement Label options.
            self.result.config(text="")
        if "core" in self.__dict__:
            App._reset_history_browsing(self)
        else:
            self.history_pos=0
        self.consume()
        return source
    def _restart_application(self):
        controller = self.__dict__.get("calculation_controller")
        # Unlike normal AC cancellation, a restart immediately destroys the
        # Tk scheduler.  ``close`` terminates and reaps a live worker before
        # that happens, whereas ``cancel`` defers cleanup through ``after``.
        if controller: controller.close()
        self.save_settings_file(False)
        restart_application()
        # ``execv`` normally never returns. This keeps injected test/fallback
        # launchers from leaving the old Tk instance active.
        self.destroy()

    def on_key(self): self._restart_application()

    def menu_key(self):
        if self._history_lcd_active():
            self.consume()
            return
        if self.shift:
            self.consume()
            self.setup_dialog()
            return
        m=tk.Menu(self,tearoff=0)
        for x in self.MODES:
            m.add_command(label=x,command=lambda n=x:self.select_mode(n))
        if self.__dict__.get("mode","Calculate") in {"Calculate","Complex"}:
            m.add_separator()
            m.add_command(label="History",command=self.show_history)
        m.add_command(label="Setup...",command=self.setup_dialog)
        try:
            m.tk_popup(self.winfo_pointerx(),self.winfo_pointery())
        finally:
            m.grab_release()

    def select_mode(self,m,w=None):
        # Mode changes are AC-style transitions: never carry visible input,
        # a template, or a live worker into the newly selected mode.
        App._clear_before_interaction_transition(self)
        self.mode=m; self.status_refresh();
        # Some headless contract tests deliberately use a minimal stand-in
        # rather than an App instance.  Keep the production path routed
        # through the width-aware LCD renderer while retaining that harmless
        # compatibility fallback.
        if hasattr(self,"_set_lcd_label"):
            self._set_lcd_label(self.MODE_HINTS[m])
        else:
            self.result.config(text=self.MODE_HINTS[m])
        if w:w.destroy()
        if m in App.LCD_WORKSPACE_MODES:
            self._start_lcd_flow(m)

    def setup_dialog(self):
        w=tk.Toplevel(self); w.title("SETUP"); w.geometry("460x775"); w.resizable(False,False)
        vars={}
        def combo(label,vals,cur,attr):
            f=ttk.Frame(w); f.pack(fill="x",padx=12,pady=3)
            ttk.Label(f,text=label,width=22).pack(side="left")
            v=tk.StringVar(value=cur); vars[attr]=v
            ttk.Combobox(f,textvariable=v,values=vals,state="readonly").pack(side="left",fill="x",expand=True)

        s=self.core.settings
        combo("Input / Output",["MathI/MathO","MathI/DecimalO","LineI/LineO","LineI/DecimalO"],s.input_output,"input_output")
        combo("Angle Unit",["DEG","RAD","GRA"],s.angle_unit,"angle_unit")
        combo("Number Format",["Norm","Fix","Sci"],s.number_format,"number_format")
        combo("Number Digits",[str(i) for i in range(10)],str(s.number_digits),"number_digits")
        combo("Engineer Symbol",["On","Off"],"On" if s.engineer_symbol else "Off","engineer_symbol")
        combo("Complex",["a+bi","r∠θ"],s.complex_format,"complex_format")
        combo("Statistics Frequency",["On","Off"],"On" if s.statistics_freq else "Off","statistics_freq")
        combo("Spreadsheet Auto Calc",["On","Off"],"On" if s.spreadsheet_auto_calc else "Off","spreadsheet_auto_calc")
        combo("Spreadsheet Show Cell",["Formula","Value"],s.spreadsheet_show_cell,"spreadsheet_show_cell")
        combo("Equation Complex",["On","Off"],"On" if s.equation_complex else "Off","equation_complex")
        combo("Table",["f(x)","f(x),g(x)"],"f(x),g(x)" if s.table_two_functions else "f(x)","table_two_functions")
        combo("Decimal Mark",["Dot","Comma"],s.decimal_mark,"decimal_mark")
        combo("Digit Separator",["On","Off"],"On" if s.digit_separator else "Off","digit_separator")
        combo("MultiLine Font",["Normal","Small"],s.multiline_font,"multiline_font")
        combo("Scientific Constants",list(CONSTANTS_DATASET_LABELS),s.constant_dataset,"constant_dataset")
        combo("Calculator Skin",list(self.SKINS),self.skin_name,"skin_name")
        combo("UI Scale",[str(value) for value in reversed(self.UI_SCALES)],str(self.__dict__.get("requested_ui_scale",self.ui_scale)),"ui_scale")

        def save():
            original_settings=copy.copy(s)
            original_scale=self.ui_scale
            original_requested_scale=self.__dict__.get("requested_ui_scale",self.ui_scale)
            original_skin=self.skin_name
            new_scale=original_requested_scale
            for k,v in vars.items():
                val=v.get()
                if k=="ui_scale":
                    new_scale=int(val); continue
                if k=="skin_name":
                    self.skin_name=self._validated_skin_name(val); continue
                if k in self.BOOLEAN_SETTINGS:
                    val=self._coerce_boolean_setting(k,val)
                elif k=="table_two_functions":
                    val=val=="f(x),g(x)"
                elif k=="number_digits":
                    val=int(val)
                setattr(s,k,val)
            self.requested_ui_scale=self._validated_ui_scale(new_scale)
            self.ui_scale=self._fit_ui_scale_to_display(self.requested_ui_scale)
            if not self.save_settings_file(False):
                self.core.settings=original_settings
                self.ui_scale=original_scale
                self.requested_ui_scale=original_requested_scale
                self.skin_name=original_skin
                self.err(CalculatorError("Settings ERROR: save failed"), clear_input=False)
                return
            w.destroy()
            self._rebuild_scaled_ui()
            self._lcd_message("Settings saved")

        def reset():
            if self.reset_app_settings():
                w.destroy()

        def clear_history():
            if messagebox.askyesno(
                "Clear History",
                "Delete the saved calculation history? This cannot be undone.",
                parent=w,
            ):
                self.clear_calculation_history()

        buttons=ttk.Frame(w); buttons.pack(fill="x",padx=12,pady=12)
        ttk.Button(buttons,text="Save",command=save).pack(side="left",expand=True,fill="x",padx=(0,4))
        ttk.Button(buttons,text="Clear History",command=clear_history).pack(side="left",expand=True,fill="x",padx=4)
        ttk.Button(buttons,text="Reset to Defaults",command=reset).pack(side="left",expand=True,fill="x",padx=(4,0))

    def _left_context(self):
        if self.template_kind:
            key=cast(str, self._active_template_field()); txt=str(self.template_fields.get(key,""))
            pos=max(0,min(len(txt),self.template_cursors.get(key,len(txt))))
            return txt[:pos]
        txt=self.expr.get()
        try: pos=self.expr.index(tk.INSERT)
        except Exception: pos=len(txt)
        return txt[:pos]

    def _insert_function_token(self, token):
        left=self._left_context(); prefix=""
        if left:
            last=left[-1]
            if last==")" or last.isdigit() or last in ("x","y","π","e"):
                prefix="×"
        self.insert(prefix+token)

    def num_key(self,n):
        if self.shift and n=="7": self.consume(); self.constants_dialog(); return
        if self.shift and n=="8": self.consume(); self.conversions_dialog(); return
        if self.shift and n=="9": self.consume(); self.reset_dialog(); return
        self.insert(n)
    def x_key(self):
        if self._history_lcd_active():
            self.consume()
            return
        if self.shift: self.consume(); self.sum_dialog(); return
        self.insert("x")
    def fraction_key(self): self.insert(" + 1/2" if self.shift else "/")
    def sqrt_key(self): self._insert_function_token("cbrt(" if self.shift else "sqrt(")
    def square_key(self):
        if self.mode=="Base-N": self.base=10; self.consume(); self.status_refresh(); return
        self.insert("^3" if self.shift else "^2")
    def power_key(self):
        if self.mode=="Base-N": self.base=16; self.consume(); self.status_refresh(); return
        if self.shift:
            n=simpledialog.askstring("nth Root","Root degree n =",parent=self)
            if n:self.insert(f"^(1/({n}))")
            else:self.consume()
        else:self.insert("^")
    def log_key(self):
        if self.mode=="Base-N": self.base=2; self.consume(); self.status_refresh(); return
        self._insert_function_token("10^(" if self.shift else "log(")
    def ln_key(self):
        if self.mode=="Base-N": self.base=8; self.consume(); self.status_refresh(); return
        self._insert_function_token("e^(" if self.shift else "ln(")
    def neg_key(self):
        if self.alpha:self.insert("A"); return
        self.insert("log(" if self.shift else "-")
    def dms_key(self):
        if self.alpha:self.insert("B"); return
        if self.shift:
            try:
                f=self.core.prime_factorization(self.core.ans); self._show_completed_result(" × ".join(f"{p}^{e}" if e>1 else str(p) for p,e in f.items()))
            except Exception as e:self.err(e)
            self.consume(); return
        self.dms_dialog()
    def inv_key(self):
        if self.alpha:self.insert("C"); return
        self.insert("factorial(" if self.shift else "^(-1)")
    def trig_key(self,n):
        if self.alpha:self.insert({"sin":"D","cos":"E","tan":"F"}[n]); return
        self._insert_function_token(("a"+n if self.shift else n)+"(")
    def sto_key(self):
        if self.shift:
            self.consume(); self.recall_dialog(); return
        name=simpledialog.askstring("STO","Memory: A,B,C,D,E,F,M,x,y",parent=self)
        if name:
            try:self.core.store(name.strip(),self.core.ans); self._show_completed_result(f"{name}={self.core.format_result(self.core.ans)}")
            except Exception as e:self.err(e)
        self.consume()
    def eng_key(self):
        if self.mode=="Complex": self.insert("∠" if self.shift else "i"); return
        try:
            value=float(sp.N(self.core.ans))
            if not math.isfinite(value):
                raise CalculatorError("Math ERROR: engineering display requires a finite real result")
            previous=self.__dict__.get("_engineering_exponent")
            if value==0:
                exponent=0
            elif previous is None:
                exponent=int(math.floor(math.log10(abs(value))/3)*3)
            else:
                exponent=previous+(3 if self.shift else -3)
            self._engineering_exponent=exponent
            self._show_completed_result(f"{value/(10**exponent):.10g}×10^{exponent}")
        except Exception as e:self.err(e)
        self.consume()
    def lparen_key(self):
        if self.shift: self._insert_function_token("Abs(")
        else: self.insert("(")
    def rparen_key(self):
        if self.alpha:self.insert("x"); return
        self.insert("," if self.shift else ")")
    def sd_key(self):
        if self.alpha:self.insert("y"); return
        if self.shift:self.insert("z"); return
        try:
            v=sp.nsimplify(self.core.ans)
            cur=self.__dict__.get("_completed_result_text") or self.result.cget("text")
            if "/" in cur or "√" in cur or "pi" in cur: self._show_completed_result(self.core.format_result(sp.N(v,15),True))
            else:self._show_completed_result(self.core.format_result(v,False))
        except Exception as e:self.err(e)
        self.consume()
    def mplus_key(self):
        if self.alpha:self.insert("M"); return
        try:v=self.core.m_minus() if self.shift else self.core.m_plus(); self._show_completed_result(f"M={self.core.format_result(v)}")
        except Exception as e:self.err(e)
        self.consume()
    def mul_key(self):
        if self.shift:
            self.consume(); self.comb_dialog("nPr"); return
        self.insert("×")
    def div_key(self):
        if self.shift:
            self.consume(); self.comb_dialog("nCr"); return
        self.insert("÷")
    def comb_dialog(self,kind):
        n=simpledialog.askinteger(kind,"n =",parent=self); r=simpledialog.askinteger(kind,"r =",parent=self)
        if n is None or r is None:return
        try:
            expr=f"{kind}({n},{r})"; self.set_expr(expr); self.show(self.core.evaluate(expr)); self._persist_calculation_history()
        except Exception as e:self.err(e)
    def plus_key(self):
        if self.shift:self.consume(); self.pol_dialog(); return
        self.insert("+")
    def minus_key(self):
        if self.shift:self.consume(); self.rec_dialog(); return
        self.insert("−")
    def dot_key(self):
        if self.alpha:
            a=simpledialog.askinteger("RanInt#","Lower bound",parent=self); b=simpledialog.askinteger("RanInt#","Upper bound",parent=self)
            if a is not None and b is not None:
                try:self.insert(str(self.core.random_int(a,b)))
                except Exception as error:self.err(error)
            else:self.consume()
            return
        if self.shift:self.insert(str(self.core.random_number())); return
        self.insert(".")
    def sci_key(self):
        if self.alpha:self.insert("e"); return
        self.insert("π" if self.shift else "×10^")
    def ans_key(self): self.insert("%" if self.shift else "Ans")

    def equals(self):
        if self.__dict__.get("_calculation_busy",False):
            return
        if self._history_lcd_active():
            self._lcd_recall_history_entry()
            self.consume()
            return
        if self._lcd_flow_active():
            self.shift=False; self.status_refresh(); self._lcd_submit(); self.consume(); return
        if self.shift:
            self.shift=False; self.status_refresh(); self.approx(); return
        if self.template_kind:
            try:self.evaluate_template()
            except Exception as e:self.err(e)
            self.consume(); return
        text=self._expression_source().strip()
        if not text:return
        if self.mode=="Base-N":
            try:
                v=self.core.evaluate_base(text,self.base)
                self.core.ans=sp.Integer(v)
                self._show_completed_result(self.core.format_base(v,self.base))
                self._record_submitted_expression(text)
            except Exception as e:self.err(e)
            self.consume(); return
        if self.mode=="Complex":
            self._run_background_calculation(
                "complex_eval",(text,),lambda result:(self.show(result),self._record_submitted_expression(text)),
            )
            self.consume(); return
        self._run_background_calculation(
            "evaluate", (text,), lambda result: (self.show(result),self._record_submitted_expression(text)),
        )
        self.consume()
    def approx(self):
        self._run_background_calculation("evaluate", (self._expression_source(), False), lambda result:self.show(result,True))
        self.consume()

    def calc_key(self):
        if self._history_lcd_active():
            self.consume()
            return
        if self.alpha:self.insert("="); return
        if self.shift:self.consume(); self.solve_dialog(); return
        self.consume(); self.calc_dialog()
    def calc_dialog(self):
        text=self._expression_source().strip(); vars_found=[v for v in "ABCDEFMxy" if re.search(rf'(?<![A-Za-z]){v}(?![A-Za-z])',text)]
        vals={}
        for v in vars_found:
            x=simpledialog.askfloat("CALC",f"{v} =",initialvalue=float(self.core.memory[v]),parent=self)
            if x is None:return
            vals[v]=x
        if vars_found:
            self._run_background_calculation("evaluate_with_values",(text,vals),self.show)
        else:
            self._run_background_calculation("evaluate",(text,),self.show)
    def solve_dialog(self):
        if self.mode!="Calculate":self.err("SOLVE is available only in Calculate mode"); return
        if self.template_kind:
            self.err("Exit the integral/derivative template with AC before using SOLVE"); return
        eq=self._expression_source().strip()
        if not eq:self.err("Enter an equation"); return
        try: syms=self.core.equation_symbols(eq)
        except Exception as e:self.err(e); return
        if not syms:
            self.err("Variable ERROR: no variable to solve in the equation"); return
        initial="x" if "x" in syms else syms[0]
        if len(syms)==1:
            var=syms[0]
        else:
            var=simpledialog.askstring("SOLVE",f"Variable to solve ({', '.join(syms)}):",initialvalue=initial,parent=self)
            if not var:return
            var=var.strip()
            if var not in syms:self.err("Variable ERROR: selected variable is not in the equation"); return
        default_guess=float(sp.N(self.core.memory.get(var,0))) if var in self.core.memory else 0.0
        guess=simpledialog.askfloat("SOLVE",f"Initial guess for {var}",initialvalue=default_guess,parent=self)
        if guess is None:return
        known={}
        for name in syms:
            if name==var:continue
            default=float(sp.N(self.core.memory.get(name,0))) if name in self.core.memory else 0.0
            value=simpledialog.askfloat("SOLVE",f"{name} =",initialvalue=default,parent=self)
            if value is None:return
            known[name]=value
        self._run_background_calculation(
            "solve", (eq,var,guess,known),
            lambda result:self._show_completed_result(f"{var}={result[0]:.12g}   L-R={result[1]:.4g}"),
        )

    def integral_key(self):
        if self._history_lcd_active():
            self.consume()
            return
        if self.alpha:self.insert(":"); return
        mode=self.__dict__.get("mode","Calculate")
        if mode not in {"Calculate","Complex"}:
            self.consume()
            return
        if self.shift:
            source=self._clear_before_interaction_transition()
            self.start_derivative_template(source)
            return
        flow_mode="Integral" if mode=="Calculate" else "Complex Integral"
        self._open_calculus_flow(flow_mode)

    def _open_calculus_flow(self,flow_mode):
        """Use an AC-style reset before opening a mode-scoped calculus menu."""
        source=self._clear_before_interaction_transition()
        self._start_lcd_flow(flow_mode,source_expression=source)

    def integral_menu(self):
        """Compatibility entry point for callers of the former pop-up menu.

        Calculus choices now stay in the calculator LCD rather than opening a
        transient Tk menu or a chain of input windows.
        """
        mode=self.__dict__.get("mode","Calculate")
        if mode in {"Calculate","Complex"}:
            self._open_calculus_flow("Integral" if mode=="Calculate" else "Complex Integral")

    def sum_dialog(self):
        f=simpledialog.askstring("Σ","f(x)=",initialvalue=self.expr.get() or "x+1",parent=self); a=simpledialog.askstring("Σ","Lower=",initialvalue="1",parent=self); b=simpledialog.askstring("Σ","Upper=",initialvalue="5",parent=self)
        if None in (f,a,b):return
        self._run_background_calculation("summation", (f,a,b),lambda result:self.show(result))
    def pol_dialog(self):
        x=simpledialog.askfloat("Pol","x=",parent=self); y=simpledialog.askfloat("Pol","y=",parent=self)
        if x is not None and y is not None:
            r,t=self.core.pol(x,y); self._show_completed_result(f"r={r:.12g}, θ={t:.12g}")
    def rec_dialog(self):
        r=simpledialog.askfloat("Rec","r=",parent=self); t=simpledialog.askfloat("Rec","θ=",parent=self)
        if r is not None and t is not None:
            x,y=self.core.rec(r,t); self._show_completed_result(f"x={x:.12g}, y={y:.12g}")
    def dms_dialog(self):
        try:
            if self.expr.get().strip():
                expression = self._expression_source()

                def show_dms(value):
                    d, m, s = self.core.dms_from_decimal(float(value))
                    degree_text = "-0" if d == 0 and math.copysign(1.0, float(d)) < 0 else str(int(d))
                    self._show_completed_result(f"{degree_text}° {m}′ {s:.8g}″")

                self._run_background_calculation("evaluate", (expression,), show_dms)
            else:
                d=simpledialog.askfloat("DMS","Degrees",parent=self); m=simpledialog.askfloat("DMS","Minutes",parent=self); s=simpledialog.askfloat("DMS","Seconds",parent=self)
                if None not in (d,m,s): self._show_completed_result(str(self.core.decimal_from_dms(d,m,s)))
        except Exception as e:self.err(e)
        self.consume()

    def optn_key(self):
        if self.shift:
            self.insert("∞")
            self.consume()
            return
        if self._history_lcd_active():
            self.consume()
            return
        if self._lcd_flow_active():
            self._lcd_options(); self.consume(); return
        menu=tk.Menu(self,tearoff=False)
        if self.mode=="Calculate":
            hyp=tk.Menu(menu,tearoff=False)
            for x in ["sinh","cosh","tanh","asinh","acosh","atanh"]: hyp.add_command(label=x,command=lambda n=x:self._insert_function_token(n+'('))
            menu.add_cascade(label="Hyperbolic Func",menu=hyp)
            ang=tk.Menu(menu,tearoff=False)
            for label,u in [("° Degree","DEG"),("r Radian","RAD"),("g Gradian","GRA")]: ang.add_command(label=label,command=lambda uu=u:self.set_angle(uu))
            menu.add_cascade(label="Angle Unit",menu=ang)
            engineering=tk.Menu(menu,tearoff=False)
            for symbol,exponent in (("f",-15),("p",-12),("n",-9),("μ",-6),("m",-3),("k",3),("M",6),("G",9),("T",12),("P",15),("E",18)):
                engineering.add_command(label=f"{symbol}  ×10^{exponent}",command=lambda value=symbol:self._insert_engineering_prefix(value))
            menu.add_cascade(label="Engineer Symbol",menu=engineering)
        elif self.mode=="Complex":
            for label,fn in [("Conj","conjugate("),("Arg","arg("),("Re","re("),("Im","im(")]: menu.add_command(label=label,command=lambda f=fn:self.insert(f))
            menu.add_separator(); menu.add_command(label="Calculus",command=lambda:self._start_lcd_flow("Complex Integral")); menu.add_separator(); menu.add_command(label="Rect→Polar",command=self.complex_to_polar); menu.add_command(label="Polar→Rect",command=self.complex_from_polar)
        elif self.mode=="Base-N":
            for op in ["and","or","xor","xnor","Not","Neg"]: menu.add_command(label=op,command=lambda o=op:self.base_logic_dialog(o))
        else: menu.add_command(label=f"Open {self.mode} workspace",command=lambda:self.mode_workspace(self.mode))
        try:menu.tk_popup(self.winfo_pointerx(),self.winfo_pointery())
        finally:menu.grab_release(); self.consume()
    def set_angle(self,u): self.core.settings.angle_unit=u; self.status_refresh()
    def complex_to_polar(self):
        def show_polar(value):
            r,a=self.core.to_polar(complex(value))
            self._show_completed_result(f"{r:.12g}∠{a:.12g}")
        self._run_background_calculation("complex_eval",(self._expression_source(),),show_polar)
    def complex_from_polar(self):
        r=simpledialog.askfloat("r∠θ","r=",parent=self); a=simpledialog.askfloat("r∠θ","θ=",parent=self)
        if r is not None and a is not None:self._show_completed_result(self.core.format_result(self.core.from_polar(r,a)))
    def base_logic_dialog(self,op):
        try:
            a=self.core.evaluate_base(self.expr.get() or "0",self.base); b=None
            if op not in ("Not","Neg"):
                s=simpledialog.askstring(op,"Second value",parent=self)
                if s is None:return
                b=self.core.evaluate_base(s,self.base)
            r=self.core.base_operation(a,b,op); self.core.ans=sp.Integer(r); self._show_completed_result(self.core.format_base(r,self.base))
        except Exception as e:self.err(e)

    def constants_dialog(self):
        dataset=self.core.settings.constant_dataset
        constants=constants_for_dataset(dataset)
        w=tk.Toplevel(self); w.title(f"CONST – {len(constants)} Scientific Constants"); lb=tk.Listbox(w,width=65,height=22); lb.pack(padx=8,pady=8,fill="both",expand=True)
        ttk.Label(w,text=dataset).pack(padx=8,pady=(6,0))
        keys=list(constants)
        for k in keys: lb.insert(tk.END,f"{k:10s}  {constants[k][0]}")
        def choose():
            if not lb.curselection():return
            k=keys[lb.curselection()[0]]; val=constants[k][1]; self.insert(f"({val:.15g})"); w.destroy()
        ttk.Button(w,text="Insert",command=choose).pack(pady=5)
    def conversions_dialog(self):
        w=tk.Toplevel(self); w.title("CONV – 40 Unit Conversions"); val=tk.StringVar(value=self.core.format_result(self.core.ans,True)); ttk.Entry(w,textvariable=val).pack(fill="x",padx=8,pady=4)
        lb=tk.Listbox(w,width=50,height=20); lb.pack(padx=8,pady=4,fill="both",expand=True); keys=list(CONVERSIONS)
        for k in keys:lb.insert(tk.END,k)
        def go():
            try:k=keys[lb.curselection()[0]]; r=self.core.convert(k,float(val.get().replace(',','.'))); self.core.ans=sp.Float(r); self._show_completed_result(self.core.format_result(r,True)); w.destroy()
            except Exception as e:self.err(e)
        ttk.Button(w,text="Convert",command=go).pack(pady=5)
    def recall_dialog(self): messagebox.showinfo("RECALL","\n".join(f"{k} = {self.core.format_result(v)}" for k,v in self.core.memory.items()),parent=self)
    def reset_dialog(self):
        w=tk.Toplevel(self); w.title("RESET")
        ttk.Button(w,text="Setup Data",command=lambda:(setattr(self.core,'settings',type(self.core.settings)()),w.destroy(),self.status_refresh())).pack(fill="x",padx=10,pady=3)
        ttk.Button(w,text="Memory",command=lambda:(self.core.reset_memory(),w.destroy())).pack(fill="x",padx=10,pady=3)
        ttk.Button(w,text="Initialize All",command=lambda:(self.core.initialize_all(),self.sheet.delete_all(),w.destroy(),self.status_refresh())).pack(fill="x",padx=10,pady=3)

    def mode_workspace(self,m):
        if m in self.LCD_WORKSPACE_MODES:
            self._start_lcd_flow(m)
            return

    def _spreadsheet_display_value(self,address):
        if self.core.settings.spreadsheet_show_cell=="Formula":
            return self.sheet.cells.get(address,"")
        if address not in self.sheet.cells:
            return ""
        value=self.sheet.cache.get(address,"")
        return f"{value} *" if address in getattr(self.sheet,"dirty_cells",set()) else value
    def help_key(self):
        messagebox.showinfo("Quick help","MENU: 12 modes\nSHIFT+MENU: SETUP\nLCD modes: = next/run • ▲▼ field/result • ◀▶ choice/cell • OPTN action • AC restart\nALPHA+CALC: red =\nSHIFT+CALC: SOLVE\n∫: LCD calculus menu (single, double, triple)\n  Select type with ◀▶, then enter variables and bounds\nSHIFT+∫: derivative template; empty point: symbolic\nEquation/Func: polynomial, simultaneous, or differential equation\nSHIFT+x: Σ\nSHIFT+7: CONST\nSHIFT+8: CONV\nSHIFT+9: RESET",parent=self)


def run_smoke_test() -> None:
    """Validate frozen runtime essentials without opening a Tk window."""
    # PyInstaller does not always discover Pillow's Tk bridge solely through
    # ``ImageTk``. This makes that required frozen dependency explicit.
    import PIL._tkinter_finder  # noqa: F401

    frozen_base=getattr(sys,"_MEIPASS",None)
    asset_base=frozen_base or os.path.abspath(os.path.join(os.path.dirname(__file__),"..","..","assets"))
    for asset in ("icons/app.ico",*App.SKINS.values()):
        asset_path=os.path.join(asset_base,asset)
        if not os.path.isfile(asset_path):
            raise RuntimeError(f"Required packaged asset is missing: {asset}")
    with Image.open(os.path.join(asset_base,"skins","skin_graphite.png")) as skin:
        if skin.size != (480,980):
            raise RuntimeError("Graphite skin has an unexpected size")
    # SciPy reaches this NumPy extension through a lazy import. Exercise it in
    # the packaged smoke check so a missing PyInstaller hidden import cannot
    # pass unnoticed.
    if not isinstance(np.random.default_rng(0).integers(1), np.integer):
        raise RuntimeError("NumPy random runtime smoke check failed")
    engine=_lazy("ScientificCalculatorEngine")()
    # SciPy loads sparse C extensions dynamically. Build-time collection and
    # this runtime assertion protect packaged startup from missing extensions.
    from scipy import sparse
    if sparse.csr_matrix([[1]]).nnz != 1:
        raise RuntimeError("SciPy sparse runtime smoke check failed")
    if engine.evaluate("2+2") != 4:
        raise RuntimeError("Calculation engine smoke check failed")
    # stats and integrate are the SciPy subpackages the calculator actually
    # uses, and both now load lazily. Exercise them here so a narrower
    # PyInstaller collection cannot drop them without failing the build.
    from scipy import stats
    if not 0.0 < float(stats.norm.pdf(0.0)) < 1.0:
        raise RuntimeError("SciPy stats runtime smoke check failed")
    from scipy.integrate import quad
    value, _error = quad(lambda x: x, 0.0, 1.0)
    if abs(value - 0.5) > 1e-9:
        raise RuntimeError("SciPy integrate runtime smoke check failed")


def run_gui_smoke_test() -> None:
    """Exercise the real Tcl/Pillow image bridge in an available display."""
    root=tk.Tk()
    try:
        root.withdraw()
        image=Image.new("RGBA",(1,1),(0,0,0,0))
        photo=ImageTk.PhotoImage(image,master=root)
        if photo.width()!=1 or photo.height()!=1:
            raise RuntimeError("Pillow/Tk image bridge returned an invalid image")
        root.update_idletasks()
    finally:
        root.destroy()


def main() -> None:
    multiprocessing.freeze_support()
    if "--smoke-test" in sys.argv:
        try:
            run_smoke_test()
        except Exception as exc:
            print(f"Scientific Calculator smoke test failed: {exc}",file=sys.stderr)
            raise SystemExit(1) from exc
    elif "--gui-smoke-test" in sys.argv:
        try:
            run_gui_smoke_test()
        except Exception as exc:
            print(f"Scientific Calculator GUI smoke test failed: {exc}",file=sys.stderr)
            raise SystemExit(1) from exc
    else:
        App().mainloop()


if __name__=='__main__':
    main()
