"""Virtual simpledialog that asks ``headless_app`` for an interactive answer."""

from __future__ import annotations


def _ask(kind, title, prompt, initialvalue=None, **kwargs):
    import headless_app

    return headless_app.request_dialog(kind, title, prompt, initialvalue)


def askfloat(title=None, prompt=None, **kwargs):
    return _ask("float", title, prompt, kwargs.get("initialvalue"))


def askinteger(title=None, prompt=None, **kwargs):
    return _ask("integer", title, prompt, kwargs.get("initialvalue"))


def askstring(title=None, prompt=None, **kwargs):
    return _ask("string", title, prompt, kwargs.get("initialvalue"))
