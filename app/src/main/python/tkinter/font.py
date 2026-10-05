"""Minimal virtual tkinter.font with a measurement that matches the Compose
monospace rendering.

The desktop slices template fields and result viewports against
``Font.measure``.  If this returns a value unrelated to the real glyph width,
those slices overflow the LCD.  A monospace advance is about 0.6 of the font's
pixel size, which is what Compose's ``FontFamily.Monospace`` also uses, so the
desktop's own ellipsis/slicing logic lands correctly when drawn.
"""

from __future__ import annotations


def _pixel_size(font) -> int:
    if isinstance(font, (tuple, list)) and len(font) >= 2:
        try:
            return abs(int(float(font[1])))
        except (TypeError, ValueError):
            return 12
    return 12


def families(root=None, displayof=None):
    """Report the monospaced family this shim renders with.

    The desktop app resolves an LCD font family from the host's installed
    families.  Android draws with Compose's ``FontFamily.Monospace`` whatever
    name is requested, so the resolved family only has to be a known reference.
    """
    return ("Consolas", "Menlo", "DejaVu Sans Mono", "Courier New")


class Font:
    def __init__(self, root=None, font=None, name=None, exists=False, **options):
        self._font = font
        self._options = options
        self.name = name or "TkDefaultFont"
        self._size = _pixel_size(font)

    def measure(self, text):
        return int(round(0.6 * self._size * len(str(text))))

    def metrics(self, *args):
        return self._size

    def actual(self, *args, **kwargs):
        return self._font if isinstance(self._font, dict) else {"size": self._size}

    def cget(self, key):
        if key == "size":
            return self._size
        return self._options.get(key, "")

    def configure(self, **kwargs):
        self._options.update(kwargs)
