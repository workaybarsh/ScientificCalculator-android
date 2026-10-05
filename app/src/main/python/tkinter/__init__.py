"""Minimal virtual Tkinter used to run the real desktop App headlessly.

Only the API surface that ``scientific_calculator.app`` touches is implemented.
Widgets store their state in Python so the bridge can read the LCD text after
dispatching a key press.  Drawing calls on a Canvas are recorded as items.

Beyond the basic surface, this layer also supports the desktop's modal dialogs:

* ``simpledialog`` / ``messagebox`` route through ``headless_app`` so Compose
  can answer them interactively.
* Widgets are registered with stable ids and Toplevels are tracked, so a whole
  dialog tree can be serialized and its button/combobox commands invoked.
"""

from __future__ import annotations

END = "end"
INSERT = "insert"
ANCHOR = "anchor"
SEL_FIRST = "sel.first"
SEL_LAST = "sel.last"
LEFT = "left"
RIGHT = "right"
TOP = "top"
BOTTOM = "bottom"
CENTER = "center"
NORMAL = "normal"
DISABLED = "disabled"
NONE = "none"

WIDGETS: dict[int, "Misc"] = {}
TOPLEVELS: list["Toplevel"] = []
_IDS = {"next": 1}


def _register(widget):
    widget_id = _IDS["next"]
    _IDS["next"] += 1
    widget._widget_id = widget_id
    WIDGETS[widget_id] = widget
    return widget_id


class TclError(Exception):
    pass


class Variable:
    def __init__(self, master=None, value=None, name=None):
        self._value = value

    def get(self):
        return self._value

    def set(self, value):
        self._value = value


class StringVar(Variable):
    def __init__(self, master=None, value="", name=None):
        super().__init__(master, "" if value is None else value, name)


class IntVar(Variable):
    def __init__(self, master=None, value=0, name=None):
        super().__init__(master, 0 if value is None else value, name)


class BooleanVar(Variable):
    def __init__(self, master=None, value=False, name=None):
        super().__init__(master, bool(value), name)


class DoubleVar(Variable):
    def __init__(self, master=None, value=0.0, name=None):
        super().__init__(master, 0.0 if value is None else value, name)


class Misc:
    def __init__(self, master=None, **kwargs):
        self.master = master
        self.tk = self
        self._kind = type(self).__name__
        self._options = dict(kwargs)
        self._binds = {}
        self._after = []
        self._placed = {}
        self._children = []
        self._destroyed = False
        _register(self)
        if master is not None and hasattr(master, "_children"):
            master._children.append(self)

    # --- configuration -------------------------------------------------
    def config(self, **kwargs):
        if "text" in kwargs and hasattr(self, "_text"):
            self._text = kwargs["text"]
        self._options.update(kwargs)
        return None

    configure = config

    def cget(self, key):
        if key == "text" and hasattr(self, "_text"):
            return self._text
        return self._options.get(key, "")

    def __setitem__(self, key, value):
        self.config(**{key: value})

    def __getitem__(self, key):
        return self.cget(key)

    # --- geometry ------------------------------------------------------
    def place(self, **kwargs):
        self._placed.update(kwargs)
        return None

    def pack(self, **kwargs):
        return None

    def grid(self, **kwargs):
        return None

    def place_forget(self):
        return None

    def pack_forget(self):
        return None

    # --- events --------------------------------------------------------
    def bind(self, sequence=None, func=None, add=None):
        self._binds.setdefault(sequence, []).append(func)
        return None

    def unbind(self, sequence, funcid=None):
        self._binds.pop(sequence, None)

    def after(self, ms, func=None, *args):
        if func is not None:
            self._after.append((ms, func, args))
        return "after#0"

    def after_cancel(self, identifier=None):
        return None

    def update(self):
        return None

    def update_idletasks(self):
        return None

    def focus_set(self):
        return None

    focus_force = focus_set

    def focus_get(self):
        return None

    def destroy(self):
        self._destroyed = True
        WIDGETS.pop(getattr(self, "_widget_id", None), None)

    # --- introspection ------------------------------------------------
    def winfo_width(self):
        value = self._placed.get("width")
        if callable(value):
            value = value()
        if isinstance(value, (int, float)):
            return int(value)
        if hasattr(self, "_canvas_width"):
            return self._canvas_width
        return 381

    def winfo_height(self):
        value = self._placed.get("height")
        if callable(value):
            value = value()
        if isinstance(value, (int, float)):
            return int(value)
        if hasattr(self, "_canvas_height"):
            return self._canvas_height
        return 58

    def winfo_reqwidth(self):
        return self.winfo_width()

    def winfo_reqheight(self):
        return self.winfo_height()

    def winfo_children(self):
        return list(self._children)

    def winfo_ismapped(self):
        return True

    def winfo_rootx(self):
        return 0

    def winfo_rooty(self):
        return 0

    def winfo_screenwidth(self):
        return 1920

    def winfo_screenheight(self):
        return 1080

    def winfo_pointerx(self):
        return 0

    def winfo_pointery(self):
        return 0

    def winfo_exists(self):
        return 0 if self._destroyed else 1

    def tk_call(self, *args):  # pragma: no cover - thin shim
        if len(args) >= 2 and args[0] == "tk" and args[1] == "scaling":
            return "1.3333333333333333"
        return ""

    call = tk_call

    def clipboard_clear(self):
        self._clipboard = ""

    def clipboard_append(self, text):
        self._clipboard = getattr(self, "_clipboard", "") + text

    def clipboard_get(self):
        return getattr(self, "_clipboard", "")

    def bell(self):
        return None

    def wait_visibility(self, window=None):
        return None

    def title(self, text=None):
        if text is not None:
            self._options["title"] = text
        return self._options.get("title", "")

    def geometry(self, spec=None):
        if spec is not None:
            self._options["geometry"] = spec
        return self._options.get("geometry", "")

    def resizable(self, *args):
        return None

    def protocol(self, name=None, func=None):
        return None

    def iconbitmap(self, *args, **kwargs):
        return None

    def iconphoto(self, *args, **kwargs):
        return None

    def withdraw(self):
        return None

    def deiconify(self):
        return None

    def attributes(self, *args, **kwargs):
        return None

    def lift(self):
        return None

    def mainloop(self, n=0):
        return None

    def quit(self):
        return None


class Widget(Misc):
    pass


class Frame(Widget):
    pass


class Label(Widget):
    def __init__(self, master=None, **kwargs):
        self._text = kwargs.get("text", "")
        super().__init__(master, **kwargs)

    def config(self, **kwargs):
        if "text" in kwargs:
            self._text = kwargs["text"]
        self._options.update(kwargs)

    configure = config

    def cget(self, key):
        if key == "text":
            return self._text
        return self._options.get(key, "")


class Entry(Widget):
    def __init__(self, master=None, **kwargs):
        self._buffer = kwargs.get("text", "")
        self._cursor = 0
        self._variable = kwargs.get("textvariable")
        self._state = kwargs.get("state", "normal")
        super().__init__(master, **kwargs)

    def get(self):
        if self._variable is not None:
            return self._variable.get()
        return self._buffer

    def _sync(self):
        if self._variable is not None:
            self._variable.set(self._buffer)

    def insert(self, index, text):
        text = "" if text is None else str(text)
        if index in ("end", END):
            self._buffer += text
            self._cursor = len(self._buffer)
        else:
            try:
                position = int(index)
            except (TypeError, ValueError):
                position = len(self._buffer)
            self._buffer = self._buffer[:position] + text + self._buffer[position:]
            self._cursor = position + len(text)
        self._sync()

    def delete(self, first, last=None):
        if first == 0 and (last in ("end", END) or last is None):
            self._buffer = ""
            self._cursor = 0
            self._sync()
            return
        try:
            start = int(first)
        except (TypeError, ValueError):
            start = 0
        if last in ("end", END):
            end = len(self._buffer)
        else:
            try:
                end = int(last)
            except (TypeError, ValueError):
                end = len(self._buffer)
        self._buffer = self._buffer[:start] + self._buffer[end:]
        self._cursor = start
        self._sync()

    def icursor(self, index):
        if index in ("end", END):
            self._cursor = len(self._buffer)
        else:
            try:
                self._cursor = int(index)
            except (TypeError, ValueError):
                pass

    def index(self, index):
        if index in ("end", END):
            return len(self._buffer)
        if index in ("insert", INSERT):
            return self._cursor
        try:
            return int(index)
        except (TypeError, ValueError):
            return 0

    def selection_range(self, start, end):
        return None

    def xview(self, *args):
        return None


class Canvas(Widget):
    def __init__(self, master=None, **kwargs):
        self._items = []
        self._canvas_width = kwargs.get("width", 381)
        self._canvas_height = kwargs.get("height", 58)
        super().__init__(master, **kwargs)

    def config(self, **kwargs):
        if "width" in kwargs and isinstance(kwargs["width"], (int, float)):
            self._canvas_width = int(kwargs["width"])
        if "height" in kwargs and isinstance(kwargs["height"], (int, float)):
            self._canvas_height = int(kwargs["height"])
        self._options.update(kwargs)
        return None

    configure = config

    def _add(self, kind, *coords, **kwargs):
        item = {"kind": kind, "coords": list(coords), "options": kwargs, "id": len(self._items) + 1}
        self._items.append(item)
        return item["id"]

    def create_image(self, *coords, **kwargs):
        return self._add("image", *coords, **kwargs)

    def create_text(self, *coords, **kwargs):
        return self._add("text", *coords, **kwargs)

    def create_rectangle(self, *coords, **kwargs):
        return self._add("rectangle", *coords, **kwargs)

    def create_line(self, *coords, **kwargs):
        return self._add("line", *coords, **kwargs)

    def create_oval(self, *coords, **kwargs):
        return self._add("oval", *coords, **kwargs)

    def create_window(self, *coords, **kwargs):
        return self._add("window", *coords, **kwargs)

    def delete(self, *args):
        if not args or args[0] == "all":
            self._items = []
            return
        targets = {int(a) for a in args if str(a).isdigit()}
        self._items = [item for item in self._items if item["id"] not in targets]

    def itemconfig(self, item, **kwargs):
        for entry in self._items:
            if entry["id"] == item:
                entry["options"].update(kwargs)
        return None

    itemconfigure = itemconfig

    def coords(self, item, *args):
        for entry in self._items:
            if entry["id"] == item:
                if args:
                    entry["coords"] = list(args)
                return list(entry["coords"])
        return []

    def bbox(self, *args):
        xs, ys = [], []
        for entry in self._items:
            if entry["kind"] == "text" and len(entry["coords"]) >= 2:
                x, y = entry["coords"][0], entry["coords"][1]
                text = str(entry["options"].get("text", ""))
                width = 8 * len(text)
                xs.extend([x, x + width])
                ys.extend([y - 10, y + 4])
        if not xs:
            return None
        return (min(xs), min(ys), max(xs), max(ys))

    def move(self, item, dx, dy):
        for entry in self._items:
            if entry["id"] == item and len(entry["coords"]) >= 2:
                entry["coords"][0] += dx
                entry["coords"][1] += dy

    def bind(self, sequence=None, func=None, add=None):
        return None

    def focus_set(self):
        return None


class Listbox(Widget):
    def __init__(self, master=None, **kwargs):
        self._items = []
        self._selection = None
        super().__init__(master, **kwargs)

    def insert(self, index, *elements):
        for element in elements:
            if index in ("end", END):
                self._items.append(element)
            else:
                self._items.insert(int(index), element)

    def delete(self, first, last=None):
        if first == 0 and (last in ("end", END) or last is None):
            self._items = []
        else:
            del self._items[int(first): (int(last) + 1 if last not in (None, "end", END) else len(self._items))]

    def get(self, first=0, last=None):
        if last is None:
            return self._items[int(first)]
        return tuple(self._items[int(first): int(last) + 1])

    def curselection(self):
        return () if self._selection is None else (self._selection,)

    def selection_set(self, index):
        self._selection = int(index)

    def selection_clear(self, *args):
        self._selection = None

    def see(self, index):
        return None

    def size(self):
        return len(self._items)


class Menu(Widget):
    def __init__(self, master=None, **kwargs):
        self._entries = []
        super().__init__(master, **kwargs)
        MENUS.append(self)

    def add_command(self, **kwargs):
        self._entries.append(kwargs)

    def add_cascade(self, **kwargs):
        self._entries.append(kwargs)

    def add_separator(self, **kwargs):
        self._entries.append({"separator": True})

    def tk_popup(self, x, y, entry=""):
        global ACTIVE_MENU
        ACTIVE_MENU = self
        return None

    def post(self, x, y):
        global ACTIVE_MENU
        ACTIVE_MENU = self
        return None

    def unpost(self):
        return None

    def grab_release(self):
        return None


MENUS: list[Menu] = []
ACTIVE_MENU: "Menu | None" = None


class Button(Widget):
    def __init__(self, master=None, **kwargs):
        self._text = kwargs.get("text", "")
        super().__init__(master, **kwargs)

    def invoke(self):
        command = self._options.get("command")
        if command:
            command()

    def config(self, **kwargs):
        if "text" in kwargs:
            self._text = kwargs["text"]
        self._options.update(kwargs)

    configure = config

    def cget(self, key):
        if key == "text":
            return self._text
        return self._options.get(key, "")


class Toplevel(Widget):
    def __init__(self, master=None, **kwargs):
        super().__init__(master, **kwargs)
        TOPLEVELS.append(self)

    def destroy(self):
        super().destroy()
        if self in TOPLEVELS:
            TOPLEVELS.remove(self)

    def transient(self, master=None):
        return None

    def grab_set(self):
        return None

    def grab_release(self):
        return None

    def wait_window(self, window=None):
        return None


class PhotoImage:
    def __init__(self, *args, **kwargs):
        self._args = args
        self._kwargs = kwargs

    def width(self):
        return 480

    def height(self):
        return 980


class Tk(Misc):
    def __init__(self, *args, **kwargs):
        self._children = []
        self._options = {}
        self._binds = {}
        self._after = []
        self._placed = {}
        self._destroyed = False
        self._kind = "Tk"
        self.master = None
        self.tk = self

    def mainloop(self, n=0):
        return None
