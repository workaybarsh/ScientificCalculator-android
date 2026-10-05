"""Typed, Tk-free persistence codec for the application's saved settings.

The SQLite store deliberately knows only flattened typed values.  This module
owns the app-shaped configuration schema so loading a profile never needs a
Tk object and migrations can be characterized independently from the UI.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast


@dataclass(frozen=True, slots=True)
class SettingsPolicy:
    """The small set of application-owned settings validation rules."""

    data_version: int
    ui_scales: frozenset[int]
    skins: frozenset[str]
    boolean_settings: frozenset[str]
    enums: Mapping[str, frozenset[str]]


@dataclass(frozen=True, slots=True)
class SettingsCodec:
    """Encode, migrate, and validate plain persisted settings values."""

    policy: SettingsPolicy

    def default_config(self, default_scale: int) -> dict[str, object]:
        return {
            "schema_version": self.policy.data_version,
            "scale": default_scale,
            "skin": "Graphite",
            "calculator_settings": {},
        }

    def coerce_boolean(self, name: str, value: object) -> bool | object:
        if name not in self.policy.boolean_settings:
            return value
        if isinstance(value, bool):
            return value
        if value == "On":
            return True
        if value == "Off":
            return False
        raise ValueError(f"Invalid boolean setting: {name}")

    def validated_ui_scale(self, value: object, *, fallback: int = 100) -> int:
        try:
            candidate = int(cast(Any, value))
        except (TypeError, ValueError):
            return fallback
        return candidate if candidate in self.policy.ui_scales else fallback

    def validated_skin_name(self, value: object) -> str:
        return value if isinstance(value, str) and value in self.policy.skins else "Graphite"

    def sanitize_calculator_settings(self, saved: object) -> dict[str, object]:
        if not isinstance(saved, dict):
            return {}
        clean: dict[str, object] = {}
        for name, value in saved.items():
            if name in self.policy.boolean_settings:
                try:
                    clean[name] = self.coerce_boolean(name, value)
                except ValueError:
                    continue
            elif name == "table_two_functions":
                if type(value) is bool:
                    clean[name] = value
            elif name == "number_digits":
                if type(value) is int and 0 <= value <= 9:
                    clean[name] = value
            elif name in self.policy.enums and value in self.policy.enums[name]:
                clean[name] = value
        return clean

    def sanitize_saved_config(self, saved: object, *, default_scale: int) -> dict[str, object]:
        clean = self.default_config(default_scale)
        if not isinstance(saved, dict):
            return clean
        clean["scale"] = self.validated_ui_scale(saved.get("scale", clean["scale"]))
        clean["skin"] = self.validated_skin_name(saved.get("skin", "Graphite"))
        clean["calculator_settings"] = self.sanitize_calculator_settings(
            saved.get("calculator_settings", {})
        )
        return clean

    def migrate(self, saved: object) -> dict[str, object] | None:
        """Validate a decoded SQLite payload and upgrade supported schemas."""

        if not isinstance(saved, dict):
            return None
        version = saved.get("schema_version", 1)
        # ``bool`` is an ``int`` subclass, but never a schema version.
        if type(version) is not int or version < 1 or version > self.policy.data_version:
            return None
        payload = dict(saved)
        if version < self.policy.data_version:
            payload["schema_version"] = self.policy.data_version
        return payload

    def flatten(self, data: Mapping[str, object]) -> dict[str, object]:
        calculator_settings = data.get("calculator_settings", {})
        if not isinstance(calculator_settings, Mapping):
            calculator_settings = {}
        flat = {
            "schema_version": data.get("schema_version", self.policy.data_version),
            "scale": data.get("scale", 100),
            "skin": data.get("skin", "Graphite"),
        }
        flat.update({f"calculator.{key}": value for key, value in calculator_settings.items()})
        return flat

    def unflatten(self, data: object) -> dict[str, object] | None:
        if not isinstance(data, dict):
            return None
        settings = {
            key.removeprefix("calculator."): value
            for key, value in data.items()
            if isinstance(key, str) and key.startswith("calculator.")
        }
        return {
            "schema_version": data.get("schema_version", self.policy.data_version),
            "scale": data.get("scale", 100),
            "skin": data.get("skin", "Graphite"),
            "calculator_settings": settings,
        }
