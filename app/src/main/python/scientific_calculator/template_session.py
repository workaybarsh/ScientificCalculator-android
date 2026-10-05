"""Pure state holder for the calculator's structured math templates."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class TemplateSession:
    """Editable template data, independent of canvas geometry and Tk events."""

    kind: str
    fields: dict[str, object]
    order: list[str]
    index: int = 0
    cursors: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.order:
            raise ValueError("template order must not be empty")
        if not 0 <= self.index < len(self.order):
            raise ValueError("template index must identify an editable field")
        if any(key not in self.fields for key in self.order):
            raise ValueError("template order must reference known fields")
        self.cursors = {
            key: max(0, min(len(str(self.fields[key])), int(self.cursors.get(key, len(str(self.fields[key]))))))
            for key in self.order
        }

    @property
    def active_key(self) -> str:
        return self.order[self.index]

    def move(self, direction: int) -> bool:
        target = max(0, min(len(self.order) - 1, self.index + direction))
        changed = target != self.index
        self.index = target
        return changed

    def snapshot(self) -> TemplateSession:
        return TemplateSession(self.kind, dict(self.fields), list(self.order), self.index, dict(self.cursors))
