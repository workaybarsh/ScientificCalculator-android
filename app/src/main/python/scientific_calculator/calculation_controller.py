"""Android stub for :mod:`scientific_calculator.calculation_controller`.

The desktop controller runs each calculation in an isolated ``multiprocessing``
child process.  Android has no working ``multiprocessing`` (no System V IPC),
and importing it can fail outright, so this module provides an import-compatible
stand-in.  The headless driver replaces ``App._run_background_calculation`` with
an inline call and ``App._build_application_controllers`` with a no-op, so this
class is never used for an actual calculation.
"""
from __future__ import annotations


class CalculationController:
    def __init__(self, app=None):
        self.app = app

    def start_engine_method(self, *args, **kwargs):  # pragma: no cover - unused on Android
        raise RuntimeError("the isolated calculation controller is unavailable on Android")

    def close(self):
        return None
