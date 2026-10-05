"""Structured calculator input whose display text can differ from parser source."""

from __future__ import annotations

from dataclasses import dataclass

ENGINEERING_PREFIXES = {"f": -15, "p": -12, "n": -9, "μ": -6, "m": -3, "k": 3, "M": 6, "G": 9, "T": 12, "P": 15, "E": 18}


@dataclass(frozen=True, slots=True)
class TextSpan:
    """An ordinary, character-addressable piece of an expression."""

    text: str

    def __post_init__(self) -> None:
        if not self.text:
            raise ValueError("text spans must not be empty")

    @property
    def display(self) -> str:
        return self.text

    @property
    def source(self) -> str:
        return self.text


@dataclass(frozen=True, slots=True)
class EngineeringPrefixSpan:
    """One atomic engineering-symbol token with a parser-safe source form."""

    symbol: str

    def __post_init__(self) -> None:
        if self.symbol not in ENGINEERING_PREFIXES:
            raise ValueError("unsupported engineering prefix")

    @property
    def display(self) -> str:
        return self.symbol

    @property
    def source(self) -> str:
        return f"×10^({ENGINEERING_PREFIXES[self.symbol]})"


Span = TextSpan | EngineeringPrefixSpan


@dataclass(frozen=True, slots=True)
class ExpressionDocument:
    """Immutable display-coordinate editor state for Calculate and Complex."""

    spans: tuple[Span, ...] = ()

    @classmethod
    def from_text(cls, text: object) -> ExpressionDocument:
        value = str(text)
        return cls((TextSpan(value),)) if value else cls()

    @property
    def display(self) -> str:
        return "".join(span.display for span in self.spans)

    @property
    def source(self) -> str:
        return "".join(span.source for span in self.spans)

    def _split_at(self, index: int) -> tuple[list[Span], list[Span]]:
        position = max(0, min(len(self.display), int(index)))
        before: list[Span] = []
        offset = 0
        for number, span in enumerate(self.spans):
            end = offset + len(span.display)
            if position < end:
                if isinstance(span, TextSpan):
                    local = position - offset
                    if local:
                        before.append(TextSpan(span.text[:local]))
                    # ``position < end`` above guarantees this suffix exists.
                    after: list[Span] = [TextSpan(span.text[local:])]
                    after.extend(self.spans[number + 1 :])
                    return before, after
                # Semantic spans are atomic: an interior display coordinate
                # deterministically inserts before rather than splitting it.
                return before, list(self.spans[number:])
            before.append(span)
            offset = end
        return before, []

    @staticmethod
    def _compact(spans: list[Span]) -> tuple[Span, ...]:
        compact: list[Span] = []
        for span in spans:
            if isinstance(span, TextSpan) and compact and isinstance(compact[-1], TextSpan):
                compact[-1] = TextSpan(compact[-1].text + span.text)
            else:
                compact.append(span)
        return tuple(compact)

    def insert_text(self, index: int, text: object) -> ExpressionDocument:
        value = str(text)
        if not value:
            return self
        before, after = self._split_at(index)
        return ExpressionDocument(self._compact(before + [TextSpan(value)] + after))

    def insert_engineering_prefix(self, index: int, symbol: str) -> ExpressionDocument:
        before, after = self._split_at(index)
        return ExpressionDocument(self._compact(before + [EngineeringPrefixSpan(symbol)] + after))

    def delete_backward(self, index: int) -> ExpressionDocument:
        if index <= 0:
            return self
        return self._delete_at(index - 1)

    def delete_forward(self, index: int) -> ExpressionDocument:
        if index >= len(self.display):
            return self
        return self._delete_at(index)

    def _delete_at(self, index: int) -> ExpressionDocument:
        offset = 0
        result: list[Span] = []
        for span in self.spans:
            end = offset + len(span.display)
            if offset <= index < end:
                if isinstance(span, TextSpan):
                    local = index - offset
                    remaining = span.text[:local] + span.text[local + 1 :]
                    if remaining:
                        result.append(TextSpan(remaining))
                # An engineering span is deleted as one indivisible token.
            else:
                result.append(span)
            offset = end
        return ExpressionDocument(self._compact(result))
