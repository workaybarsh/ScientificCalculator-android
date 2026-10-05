"""Small, width-aware LCD layout primitives.

The calculator's LCD needs two deliberately separate behaviours: interface
labels may wrap so their meaning is not lost, while mathematical results must
remain one continuous value that can be inspected through a horizontal
viewport.  Keeping those rules free of Tk widgets makes their state and edge
cases straightforward to test.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

TextMeasure = Callable[[str], int]


def normalize_label(text: object) -> str:
    """Return a single-line semantic label without discarding any words."""
    return " ".join(str(text).replace("\n", " ").split())


def wrap_label(text: object, available_width: int, measure: TextMeasure, *, max_lines: int = 2) -> str:
    """Wrap a UI label by measured width instead of character count.

    Labels never receive an ellipsis here.  If a single word is wider than the
    available area it remains intact; callers can then supply a documented
    concise canonical label instead of silently changing its meaning.
    """
    label = normalize_label(text)
    if not label or available_width <= 0 or max_lines < 2 or measure(label) <= available_width:
        return label

    words = label.split(" ")
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = word if not current else f"{current} {word}"
        if current and measure(candidate) > available_width and len(lines) < max_lines - 1:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return "\n".join(lines)


def _last_view_offset(text: str, available_width: int, measure: TextMeasure) -> int:
    """Find the earliest character position that reveals the complete suffix."""
    if not text:
        return 0
    start = len(text)
    while start > 0 and measure(text[start - 1 :]) <= available_width:
        start -= 1
    # A very wide glyph still needs a non-empty final viewport.  In that case
    # the complete suffix cannot fit, so reveal its final glyph instead.
    return len(text) - 1 if start == len(text) else start


def _visible_end(text: str, offset: int, available_width: int, measure: TextMeasure) -> int:
    """Return the exclusive endpoint of the largest measured viewport slice."""
    if offset >= len(text):
        return offset
    if available_width <= 0:
        return offset + 1
    end = offset
    while end < len(text) and measure(text[offset : end + 1]) <= available_width:
        end += 1
    # A glyph wider than a pathological display width is still shown rather
    # than producing an empty viewport.
    return end if end > offset else offset + 1


@dataclass(frozen=True)
class ResultViewport:
    """The visible portion of a complete, immutable result string."""

    full_text: str
    offset: int
    end: int

    @property
    def text(self) -> str:
        return self.full_text[self.offset : self.end]

    @property
    def can_scroll_left(self) -> bool:
        return self.offset > 0

    @property
    def can_scroll_right(self) -> bool:
        return self.end < len(self.full_text)


def result_viewport(text: object, offset: int, available_width: int, measure: TextMeasure) -> ResultViewport:
    """Create a clamped, full-text-preserving horizontal result viewport."""
    full_text = str(text)
    usable_width=max(1,int(available_width))
    last = _last_view_offset(full_text, usable_width, measure)
    clamped = max(0, min(int(offset), last))
    return ResultViewport(full_text, clamped, _visible_end(full_text, clamped, usable_width, measure))


def scroll_result(text: object, offset: int, direction: int, available_width: int, measure: TextMeasure) -> ResultViewport:
    """Move a result viewport one readable character step without wrapping."""
    current = result_viewport(text, offset, available_width, measure)
    if direction < 0:
        target = current.offset - 1
    elif direction > 0:
        target = current.offset + 1
    else:
        target = current.offset
    return result_viewport(current.full_text, target, available_width, measure)


def caret_text_view(
    text: object, cursor: int, available_width: int | None, measure: TextMeasure, empty_placeholder: str = "□"
) -> tuple[str, int]:
    """Return a one-line slice of *text* that keeps the caret visible.

    Used by constrained template slots, which reserve a fixed pixel budget.
    That budget is measured against a font the host may not have, so the view
    must stay correct when a substituted font is wider than the layout assumed.
    """
    text = str(text) if text else ""
    cursor = max(0, min(len(text), cursor))
    if not text:
        return empty_placeholder, 0
    if available_width is None or measure(text) <= available_width:
        return text, measure(text[:cursor])

    ellipsis = "…"
    # Keep the caret just to the right of centre where possible, then use the
    # remaining width for the expression after it.
    start = 0
    before_budget = max(1, int(available_width * 0.55))
    while start < cursor and measure((ellipsis if start else "") + text[start:cursor]) > before_budget:
        start += 1
    end = len(text)

    def display_width() -> int:
        return measure((ellipsis if start else "") + text[start:end] + (ellipsis if end < len(text) else ""))

    while end > cursor and display_width() > available_width:
        end -= 1
    while start < cursor and display_width() > available_width:
        start += 1
    # A budget too narrow for even one glyph must still show a character. Both
    # loops can meet, leaving an ellipsis that hides the value entirely.
    if end <= start:
        start = min(cursor, len(text) - 1)
        end = start + 1
    prefix = ellipsis if start else ""
    suffix = ellipsis if end < len(text) else ""
    return prefix + text[start:end] + suffix, measure(prefix + text[start:cursor])


# Unicode superscript forms for the characters an exponential argument
# commonly needs.  Lowercase "q" has no superscript codepoint, and operators
# such as "*", "/", "." and "√" have none either, so those exponents are left
# in the plain exp(...) form rather than rendered incorrectly.
#
# The digits and operators are part of every font the LCD may resolve to.  The
# letters are *patchy*: they live in the Unicode modifier-letter blocks
# (U+02B0-U+02E3 and U+1D43-U+1D5B) that a substituted family may not cover, so
# the display only uses them when the resolved family is known to have them
# (see ``fonts.supports_letter_superscripts``).
_SUPERSCRIPT_SAFE_CHARACTERS = {
    "0": "\u2070", "1": "\u00b9", "2": "\u00b2", "3": "\u00b3", "4": "\u2074",
    "5": "\u2075", "6": "\u2076", "7": "\u2077", "8": "\u2078", "9": "\u2079",
    "+": "\u207a", "-": "\u207b", "(": "\u207d", ")": "\u207e",
}
_SUPERSCRIPT_LETTER_CHARACTERS = {
    "a": "\u1d43", "b": "\u1d47", "c": "\u1d9c", "d": "\u1d48", "e": "\u1d49",
    "f": "\u1da0", "g": "\u1d4d", "h": "\u02b0", "i": "\u2071", "j": "\u02b2",
    "k": "\u1d4f", "l": "\u02e1", "m": "\u1d50", "n": "\u207f", "o": "\u1d52",
    "p": "\u1d56", "r": "\u02b3", "s": "\u02e2", "t": "\u1d57", "u": "\u1d58",
    "v": "\u1d5b", "w": "\u02b7", "x": "\u02e3", "y": "\u02b8", "z": "\u1dbb",
}
_SUPERSCRIPT_CHARACTERS = {**_SUPERSCRIPT_SAFE_CHARACTERS, **_SUPERSCRIPT_LETTER_CHARACTERS}


def superscript_exponentials(text: object, *, superscript_letters: bool = True) -> str:
    """Render ``exp(argument)`` as ``e`` plus a Unicode superscript argument.

    Only arguments whose every character has a Unicode superscript form are
    rewritten (simple exponents such as ``x``, ``-x``, ``2x`` or ``x+1``).
    Anything more complex, including exponents with ``*``, ``/``, ``.`` or a
    radical, keeps the plain ``exp(...)`` spelling because no plain-text
    superscript exists for those glyphs.

    Letter superscripts live in patchy Unicode blocks, so callers whose font
    may not cover them pass ``superscript_letters=False``.  The exponent then
    uses the safe bracketed power form (``e^(x)``) rather than a glyph Tk would
    render as a missing-character box.
    """
    source = str(text)
    table = _SUPERSCRIPT_CHARACTERS if superscript_letters else _SUPERSCRIPT_SAFE_CHARACTERS
    if "exp(" not in source:
        return source
    pieces: list[str] = []
    index = 0
    length = len(source)
    while index < length:
        start = source.find("exp(", index)
        if start == -1:
            pieces.append(source[index:])
            break
        # ``exp`` inside a longer identifier is not a function call here.
        if start > 0 and (source[start - 1].isalnum() or source[start - 1] == "_"):
            pieces.append(source[index : start + 1])
            index = start + 1
            continue
        depth = 0
        end = -1
        for position in range(start + 4, length):
            character = source[position]
            if character == "(":
                depth += 1
            elif character == ")":
                if depth == 0:
                    end = position
                    break
                depth -= 1
        if end == -1:
            pieces.append(source[index:])
            break
        argument = source[start + 4 : end]
        mapped = "".join(table.get(character, "") for character in argument)
        pieces.append(source[index:start])
        if argument and "exp(" not in argument and len(mapped) == len(argument):
            pieces.append("e" + mapped)
        elif argument and "exp(" not in argument:
            # The exponent has a glyph with no superscript form (a radical,
            # ``*``, ``/``, ``^`` …).  Fall back to the bracketed power form,
            # which still reads as e-to-the-power and is shorter than exp(...).
            pieces.append("e^(" + argument + ")")
        else:
            pieces.append(source[start : end + 1])
        index = end + 1
    return "".join(pieces)


# A single power term: a base (letter, digit, or a closing parenthesis) raised
# to a signed integer.  A chained power such as ``x^2^3`` or ``(x^2)^2`` does
# not match, because the exponent must not be followed by another power, a
# decimal point, or a digit, and the base must not itself sit directly after a
# ``^``.
_POWER_TERM = re.compile(r"(?<![\w\^])([A-Za-z0-9_)]+)\^([+-]?\d+)(?![\^\d.]|\)\^)")


def superscript_powers(text: object) -> str:
    """Render a single integer power as a Unicode superscript.

    ``x^2`` becomes ``x`` with a superscript two, and ``x^10`` likewise.  Nested
    or chained powers (``x^2^3``, ``(x^2)^2``) and non-integer exponents are left
    untouched, because plain text has no way to stack them.
    """
    source = str(text)
    if "^" not in source:
        return source

    def replace(match: re.Match[str]) -> str:
        base, exponent = match.group(1), match.group(2)
        # Every character of a signed integer exponent has a superscript form.
        mapped = "".join(_SUPERSCRIPT_CHARACTERS[character] for character in exponent)
        return base + mapped

    return _POWER_TERM.sub(replace, source)


def render_math_text(text: object, *, superscript_letters: bool = True) -> str:
    """Apply every plain-text math presentation rule to a display string."""
    return superscript_powers(superscript_exponentials(text, superscript_letters=superscript_letters))


