"""Cross-platform font family resolution for the LCD.

The LCD was designed against Windows-only typefaces (``Consolas`` and
``Cambria Math``).  Neither ships on macOS or Linux, so Tk silently substitutes
an arbitrary family and the LCD geometry slips.  A substituted family can also
lack some of the Unicode superscript codepoints the LCD uses for natural
notation, which makes Tk fall back per glyph and draw a single character such
as the exponent letter in a different face.

This module keeps the platform decision pure and testable: callers pass the
family names Tk actually reports and receive the best available choice.  It
never imports Tk, so it can be exercised without a display.
"""

from __future__ import annotations

from collections.abc import Iterable

# First installed family wins.  Each list ends with families that ship on the
# target platforms and cover the LCD glyph set, so a Linux or macOS host still
# gets a monospaced family with stable measurement.
LCD_FAMILIES: tuple[str, ...] = (
    "Consolas",          # Windows design reference
    "Cascadia Mono",     # Windows 11
    "Menlo",             # macOS
    "SF Mono",           # macOS
    "DejaVu Sans Mono",  # Ubuntu default
    "Liberation Mono",   # Linux
    "Noto Sans Mono",    # Linux
    "Courier New",       # last resort
)

# The integral sign is the only math glyph the LCD draws from a math font, so
# this list prefers families that render it cleanly on each platform.
MATH_FAMILIES: tuple[str, ...] = (
    "Cambria Math",      # Windows design reference
    "STIX Two Math",
    "Latin Modern Math",
    "XITS Math",
    "DejaVu Sans",       # Linux math coverage
    "DejaVu Serif",
    "Times New Roman",
)

DEFAULT_FALLBACK = "TkDefaultFont"

# Families that ship the modifier-letter superscripts natural notation uses
# (U+02B0-U+02E3 and U+1D43-U+1D5B).  ``Consolas`` was verified on Windows; the
# rest ship with the platforms this application targets.  When the resolved LCD
# family is not listed here the LCD keeps the safe bracketed power form instead
# (``e^(x)``) so a missing glyph never appears as a box.
SUPERSCRIPT_FAMILIES: frozenset[str] = frozenset(
    family.casefold() for family in LCD_FAMILIES
)


def choose_family(
    available: Iterable[str],
    candidates: Iterable[str],
    *,
    fallback: str = DEFAULT_FALLBACK,
) -> str:
    """Return the first candidate that *available* reports, else *fallback*.

    Comparison is case-insensitive because Tk spells families differently across
    platforms (``Consolas`` vs ``consolas`` on some X servers).
    """
    available_lower = {str(name).casefold() for name in available}
    for candidate in candidates:
        if candidate.casefold() in available_lower:
            return candidate
    return fallback


def supports_letter_superscripts(family: str) -> bool:
    """Report whether *family* is known to cover the LCD superscript letters."""
    return str(family).casefold() in SUPERSCRIPT_FAMILIES
