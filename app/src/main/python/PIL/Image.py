"""Minimal virtual PIL.Image: geometry only, no real decoding."""

from __future__ import annotations

from enum import IntEnum


class Resampling(IntEnum):
    NEAREST = 0
    BOX = 4
    BILINEAR = 2
    HAMMING = 5
    BICUBIC = 3
    LANCZOS = 1


class _Image:
    def __init__(self, size=(480, 980), mode="RGBA"):
        self.size = size
        self.mode = mode

    def resize(self, size, resample=None):
        return _Image(size, self.mode)

    def convert(self, mode):
        return _Image(self.size, mode)

    def copy(self):
        return _Image(self.size, self.mode)

    def load(self):
        return None


def open(fp, mode="r", formats=None):  # noqa: A001 - mirror PIL API
    return _Image((480, 980))


def new(mode, size, color=None):
    return _Image(size, mode)
