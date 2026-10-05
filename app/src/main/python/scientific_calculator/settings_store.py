"""Small, typed SQLite store for Scientific Calculator preferences.

The store deliberately serializes only the primitive settings supplied by the
application. It never deserializes arbitrary Python objects.
"""
from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .history import CalculationHistoryEntry


class DatabaseMigrationError(sqlite3.DatabaseError):
    """The on-disk database cannot be safely upgraded by this application."""


class SettingsStore:
    # This version belongs only to SQLite tables/columns. The semantic settings
    # payload version is owned by ``App.SETTINGS_DATA_VERSION``.
    DB_SCHEMA_VERSION = 3
    HISTORY_LIMIT = 10

    def __init__(self, path: str | os.PathLike[str], log_issue: Callable[[str, Exception], None] | None = None):
        self.path = Path(path)
        self._log_issue = log_issue or (lambda _operation, _error: None)

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            connection.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            row = connection.execute("SELECT value FROM meta WHERE key = 'db_schema_version'").fetchone()
            if row is None:
                # v1 already had the current table shapes but did not distinguish
                # its database version from settings-data semantics.
                legacy = connection.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
                version = 1 if legacy is not None else self.DB_SCHEMA_VERSION
            else:
                try:
                    version = int(row[0])
                except (TypeError, ValueError) as exc:
                    raise DatabaseMigrationError("invalid database schema version") from exc
            if version < 1 or version > self.DB_SCHEMA_VERSION:
                raise DatabaseMigrationError("unsupported database schema version")
            self._create_current_tables(connection)
            while version < self.DB_SCHEMA_VERSION:
                version = self._migrate(connection, version)
            connection.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES ('db_schema_version', ?)",
                (str(version),),
            )
            connection.commit()
            return connection
        except Exception:
            connection.close()
            raise

    @staticmethod
    def _create_current_tables(connection: sqlite3.Connection) -> None:
        connection.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value_type TEXT NOT NULL, value_text TEXT NOT NULL)")
        connection.execute(
            "CREATE TABLE IF NOT EXISTS calculation_history "
            "(position INTEGER PRIMARY KEY, expression TEXT NOT NULL, result TEXT NOT NULL, "
            "kind TEXT NOT NULL DEFAULT 'legacy', metadata TEXT NOT NULL DEFAULT '{}')"
        )

    def _migrate(self, connection: sqlite3.Connection, version: int) -> int:
        if version == 1:
            return 2
        if version == 2:
            columns = {row[1] for row in connection.execute("PRAGMA table_info(calculation_history)")}
            if "kind" not in columns:
                connection.execute("ALTER TABLE calculation_history ADD COLUMN kind TEXT NOT NULL DEFAULT 'legacy'")
            if "metadata" not in columns:
                connection.execute("ALTER TABLE calculation_history ADD COLUMN metadata TEXT NOT NULL DEFAULT '{}'")
            return 3
        raise DatabaseMigrationError("no migration is available")

    @staticmethod
    def _encode(value: Any) -> tuple[str, str]:
        if type(value) is bool:
            return "bool", "1" if value else "0"
        if type(value) is int:
            return "int", str(value)
        if type(value) is str:
            return "str", value
        raise TypeError(f"Unsupported setting type: {type(value).__name__}")

    @staticmethod
    def _decode(value_type: str, value_text: str) -> Any:
        if value_type == "bool" and value_text in {"0", "1"}:
            return value_text == "1"
        if value_type == "int":
            return int(value_text)
        if value_type == "str":
            return value_text
        raise ValueError("Invalid typed setting")

    def load(self) -> dict[str, Any] | None:
        try:
            connection = self._connect()
            try:
                rows = connection.execute("SELECT key, value_type, value_text FROM settings").fetchall()
            finally:
                connection.close()
            if not rows:
                return None
            return {key: self._decode(value_type, value_text) for key, value_type, value_text in rows}
        except (sqlite3.DatabaseError, OSError, ValueError) as error:
            self._log_issue("load", error)
            return None

    def save(self, values: dict[str, Any]) -> None:
        encoded = {key: self._encode(value) for key, value in values.items()}
        connection = self._connect()
        try:
            with connection:
                connection.execute("DELETE FROM settings")
                connection.executemany("INSERT INTO settings (key, value_type, value_text) VALUES (?, ?, ?)", ((key, value_type, value_text) for key, (value_type, value_text) in encoded.items()))
        finally:
            connection.close()

    @classmethod
    def _validated_history(cls, entries: object) -> list[CalculationHistoryEntry]:
        """Validate display text plus a primitive-only structured recall payload."""
        if not isinstance(entries, (list, tuple)):
            raise TypeError("History must be a list of expression/result pairs")
        validated: list[CalculationHistoryEntry] = []
        for entry in entries[-cls.HISTORY_LIMIT:]:
            normalized = CalculationHistoryEntry.from_legacy(entry)
            if len(normalized.expression) > 4096 or len(normalized.result) > 4096:
                raise ValueError("History entry is too large")
            metadata = json.dumps(normalized.metadata, ensure_ascii=False, separators=(",", ":"))
            if len(normalized.kind) > 128 or len(metadata) > 16384:
                raise ValueError("History metadata is too large")
            validated.append(normalized)
        return validated

    def load_history(self) -> list[CalculationHistoryEntry] | None:
        try:
            connection = self._connect()
            try:
                rows = connection.execute(
                    "SELECT expression, result, kind, metadata FROM calculation_history "
                    "ORDER BY position ASC LIMIT ?", (self.HISTORY_LIMIT,)
                ).fetchall()
            finally:
                connection.close()
            entries = []
            for expression, result, kind, metadata in rows:
                decoded = json.loads(metadata)
                if not isinstance(decoded, dict):
                    raise ValueError("History metadata must be an object")
                entries.append(CalculationHistoryEntry(expression, result, kind, decoded))
            return self._validated_history(entries)
        except (sqlite3.DatabaseError, OSError, TypeError, ValueError) as error:
            self._log_issue("load history", error)
            return None

    def save_history(self, entries: list[CalculationHistoryEntry]) -> None:
        history = self._validated_history(entries)
        connection = self._connect()
        try:
            with connection:
                connection.execute("DELETE FROM calculation_history")
                connection.executemany(
                    "INSERT INTO calculation_history (position, expression, result, kind, metadata) VALUES (?, ?, ?, ?, ?)",
                    ((position, entry.expression, entry.result, entry.kind, json.dumps(entry.metadata, ensure_ascii=False, separators=(",", ":"))) for position, entry in enumerate(history)),
                )
        finally:
            connection.close()

    def save_state(self, values: dict[str, Any], entries: list[CalculationHistoryEntry]) -> None:
        """Atomically replace settings and calculation history together."""
        encoded = {key: self._encode(value) for key, value in values.items()}
        history = self._validated_history(entries)
        connection = self._connect()
        try:
            with connection:
                connection.execute("DELETE FROM settings")
                connection.executemany(
                    "INSERT INTO settings (key, value_type, value_text) VALUES (?, ?, ?)",
                    ((key, value_type, value_text) for key, (value_type, value_text) in encoded.items()),
                )
                connection.execute("DELETE FROM calculation_history")
                connection.executemany(
                    "INSERT INTO calculation_history (position, expression, result, kind, metadata) VALUES (?, ?, ?, ?, ?)",
                    ((position, entry.expression, entry.result, entry.kind, json.dumps(entry.metadata, ensure_ascii=False, separators=(",", ":"))) for position, entry in enumerate(history)),
                )
        finally:
            connection.close()

    def reset_defaults(self) -> None:
        """Clear only this app's stored values; called solely by Setup."""
        connection = self._connect()
        try:
            with connection:
                connection.execute("DELETE FROM settings")
                connection.execute("DELETE FROM calculation_history")
        finally:
            connection.close()
