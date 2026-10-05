"""Virtual messagebox.

Informational boxes are recorded so Compose can show them; confirmation boxes
route through ``headless_app`` for an interactive yes/no.
"""

from __future__ import annotations

INFO_MESSAGES: list[dict[str, str]] = []


def _info(kind, title, message):
    INFO_MESSAGES.append({"kind": kind, "title": str(title or ""), "message": str(message or "")})
    return "ok"


def showinfo(title=None, message=None, **kwargs):
    return _info("info", title, message)


def showwarning(title=None, message=None, **kwargs):
    return _info("warning", title, message)


def showerror(title=None, message=None, **kwargs):
    return _info("error", title, message)


def askyesno(title=None, message=None, **kwargs):
    import headless_app

    return bool(headless_app.request_dialog("yesno", title, message, None))


def askokcancel(title=None, message=None, **kwargs):
    import headless_app

    return bool(headless_app.request_dialog("yesno", title, message, None))


def askquestion(title=None, message=None, **kwargs):
    import headless_app

    answer = headless_app.request_dialog("yesno", title, message, None)
    return "yes" if answer else "no"


def askretrycancel(title=None, message=None, **kwargs):
    import headless_app

    return bool(headless_app.request_dialog("yesno", title, message, None))
