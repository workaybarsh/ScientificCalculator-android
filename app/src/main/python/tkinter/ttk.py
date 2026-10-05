"""Minimal virtual tkinter.ttk built on the base widgets."""

from __future__ import annotations

from . import Button as _Button
from . import Entry as _Entry
from . import Frame as _Frame
from . import Label as _Label
from . import Widget


class Frame(_Frame):
    pass


class Label(_Label):
    pass


class Entry(_Entry):
    pass


class Button(_Button):
    pass


class Combobox(Widget):
    def __init__(self, master=None, **kwargs):
        self._values = list(kwargs.get("values", []))
        self._textvariable = kwargs.get("textvariable")
        self._current = self._values[0] if self._values else ""
        super().__init__(master, **kwargs)

    def set(self, value):
        self._textvariable = value
        self._current = value

    def get(self):
        return self._current

    def current(self, index=None):
        if index is None:
            return self._values.index(self._current) if self._current in self._values else -1
        self._current = self._values[int(index)]
        return None

    def configure(self, **kwargs):
        if "values" in kwargs:
            self._values = list(kwargs["values"])
        self._options.update(kwargs)

    config = configure


class Separator(Widget):
    pass


class Notebook(Widget):
    def add(self, child, **kwargs):
        return None

    def select(self, tab=None):
        return None
