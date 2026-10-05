"""Application-level persistence orchestration without a Tk dependency."""

from __future__ import annotations

from typing import Protocol

from .history import CalculationHistoryEntry


class SettingsStoreLike(Protocol):
    """The narrow database contract used by :class:`ApplicationPersistence`."""

    def load(self) -> dict[str, object] | None: ...

    def load_history(self) -> list[CalculationHistoryEntry] | None: ...

    def save_history(self, entries: list[CalculationHistoryEntry]) -> None: ...

    def save_state(self, values: dict[str, object], entries: list[CalculationHistoryEntry]) -> None: ...

    def reset_defaults(self) -> None: ...


class ApplicationPersistence:
    """Keep store access and history normalisation in one non-UI service.

    The store provider remains a callback rather than a captured instance.
    Existing headless tests can therefore monkeypatch the application's store
    method at any point, and transient SQLite failures retain their prior
    error/rollback handling in ``App``.
    """

    def __init__(self, store_provider, *, history_limit: int) -> None:
        self._store_provider = store_provider
        self._history_limit = history_limit

    def load_settings(self) -> dict[str, object] | None:
        return self._store_provider().load()

    def load_history(self) -> list[CalculationHistoryEntry] | None:
        return self._store_provider().load_history()

    def normalize_history(self, entries: object) -> list[CalculationHistoryEntry]:
        normalized: list[CalculationHistoryEntry] = []
        if not isinstance(entries, list):
            try:
                entries = list(entries)  # type: ignore[arg-type]
            except TypeError:
                return normalized
        for entry in entries:
            try:
                normalized.append(CalculationHistoryEntry.from_legacy(entry))
            except (TypeError, ValueError):
                continue
        return normalized[-self._history_limit :]

    def save_history(self, entries: list[CalculationHistoryEntry]) -> None:
        self._store_provider().save_history(entries)

    def save_state(self, values: dict[str, object], entries: list[CalculationHistoryEntry]) -> None:
        self._store_provider().save_state(values, entries)

    def reset_defaults(self) -> None:
        self._store_provider().reset_defaults()
