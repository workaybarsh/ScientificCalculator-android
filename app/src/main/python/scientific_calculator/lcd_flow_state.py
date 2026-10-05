"""A compatibility-preserving typed vocabulary for LCD flow dictionaries."""

from __future__ import annotations

from typing import Any


class LCDFlowState(dict[str, Any]):
    """Dictionary state with named LCD-flow accessors.

    LCD modes historically shared a flexible dictionary, and several UI tests
    intentionally construct one directly.  Subclassing rather than replacing
    it with a dataclass preserves that compatibility while making common flow
    ownership explicit.  Mode-specific keys (spreadsheet, matrix, and so on)
    deliberately remain ordinary mapping entries.
    """

    @classmethod
    def promote(cls, value: object) -> LCDFlowState | None:
        if value is None:
            return None
        if isinstance(value, cls):
            return value
        return cls(value) if isinstance(value, dict) else None

    def _get(self, name: str, default: Any = None) -> Any:
        return self.get(name, default)

    def _set(self, name: str, value: Any) -> None:
        self[name] = value

    mode = property(lambda self: self._get("mode"), lambda self, value: self._set("mode", value))
    phase = property(lambda self: self._get("phase"), lambda self, value: self._set("phase", value))
    stage = property(lambda self: self._get("stage"), lambda self, value: self._set("stage", value))
    title = property(lambda self: self._get("title"), lambda self, value: self._set("title", value))
    # NOTE: no ``values`` property here.  It would shadow the inherited
    # ``dict.values()``.  The "values" key is read only via subscripting,
    # as ``flow["values"]``, everywhere this class is used.
    draft = property(lambda self: self._get("draft", {}), lambda self, value: self._set("draft", value))
    fields = property(lambda self: self._get("fields", []), lambda self, value: self._set("fields", value))
    index = property(lambda self: self._get("index", 0), lambda self, value: self._set("index", value))
    field_armed = property(lambda self: self._get("field_armed", False), lambda self, value: self._set("field_armed", value))
    result_lines = property(lambda self: self._get("result_lines", []), lambda self, value: self._set("result_lines", value))
    result_index = property(lambda self: self._get("result_index", 0), lambda self, value: self._set("result_index", value))
    result_offset = property(lambda self: self._get("result_offset", 0), lambda self, value: self._set("result_offset", value))
    template = property(lambda self: self._get("template"), lambda self, value: self._set("template", value))
    last_error = property(lambda self: self._get("last_error", ""), lambda self, value: self._set("last_error", value))
