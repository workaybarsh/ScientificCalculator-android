"""Minimal virtual PIL.ImageTk: keeps a reference, reports a size."""

from __future__ import annotations


class PhotoImage:
    def __init__(self, image=None, size=None, **kwargs):
        self._image = image
        self._size = getattr(image, "size", (480, 980))

    def width(self):
        return self._size[0]

    def height(self):
        return self._size[1]

    def zoom(self, *args):
        return self

    def subsample(self, *args):
        return self
