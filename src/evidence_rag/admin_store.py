"""Persistent admin data store backed by SQLite."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    slug TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    full_name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('superadmin', 'admin', 'editor', 'viewer')),
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_login_at TEXT
);

CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    filename TEXT NOT NULL UNIQUE,
    category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    status TEXT NOT NULL DEFAULT 'indexed',
    size_bytes INTEGER NOT NULL DEFAULT 0,
    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS telegram_users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id TEXT NOT NULL UNIQUE,
    username TEXT,
    first_name TEXT NOT NULL DEFAULT '',
    last_name TEXT NOT NULL DEFAULT '',
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS query_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question TEXT NOT NULL,
    answer TEXT,
    mode TEXT,
    citations_json TEXT NOT NULL DEFAULT '[]',
    latency_ms INTEGER,
    status TEXT NOT NULL DEFAULT 'success',
    error TEXT,
    source TEXT NOT NULL DEFAULT 'api',
    telegram_user_id INTEGER REFERENCES telegram_users(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS document_downloads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_user_id INTEGER NOT NULL REFERENCES telegram_users(id) ON DELETE CASCADE,
    document_id INTEGER REFERENCES documents(id) ON DELETE SET NULL,
    document_name TEXT NOT NULL,
    telegram_file_id TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query_id INTEGER NOT NULL REFERENCES query_history(id) ON DELETE CASCADE,
    rating INTEGER NOT NULL CHECK (rating IN (-1, 1)),
    comment TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    updated_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    actor_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    action TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT,
    details_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_documents_category ON documents(category_id);
CREATE INDEX IF NOT EXISTS idx_queries_created ON query_history(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_downloads_created ON document_downloads(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_downloads_telegram_user ON document_downloads(telegram_user_id);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_logs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
"""


class AdminStore:
    """Small explicit repository used by the admin service and API."""

    def __init__(self, database_path: Path):
        self.database_path = database_path
        database_path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as connection:
            connection.executescript(SCHEMA)
            self._migrate(connection)
        self.seed_settings()

    @staticmethod
    def _migrate(connection: sqlite3.Connection) -> None:
        """Apply additive migrations for databases created by earlier releases."""

        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(query_history)").fetchall()
        }
        if "source" not in columns:
            connection.execute(
                "ALTER TABLE query_history ADD COLUMN source TEXT NOT NULL DEFAULT 'api'"
            )
        if "telegram_user_id" not in columns:
            connection.execute(
                "ALTER TABLE query_history ADD COLUMN telegram_user_id INTEGER "
                "REFERENCES telegram_users(id) ON DELETE SET NULL"
            )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_queries_telegram_user "
            "ON query_history(telegram_user_id)"
        )

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def seed_settings(self) -> None:
        defaults = (
            ("openai_model", "gpt-5.4-mini", "OpenAI generation model"),
            ("default_top_k", "3", "Default number of retrieved evidence chunks"),
            (
                "system_prompt",
                "Answer using only the supplied sources and cite factual claims.",
                "Grounding instruction used for generated answers",
            ),
        )
        now = utc_now()
        with self.connection() as connection:
            connection.executemany(
                """INSERT OR IGNORE INTO settings(key, value, description, updated_at)
                   VALUES (?, ?, ?, ?)""",
                [(*item, now) for item in defaults],
            )

    def one(self, sql: str, parameters: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        with self.connection() as connection:
            row = connection.execute(sql, parameters).fetchone()
        return dict(row) if row else None

    def all(self, sql: str, parameters: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self.connection() as connection:
            rows = connection.execute(sql, parameters).fetchall()
        return [dict(row) for row in rows]

    def execute(self, sql: str, parameters: tuple[Any, ...] = ()) -> int:
        with self.connection() as connection:
            cursor = connection.execute(sql, parameters)
            return int(cursor.lastrowid)

    def audit(
        self,
        actor_id: int | None,
        action: str,
        entity_type: str,
        entity_id: str | int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.execute(
            """INSERT INTO audit_logs
               (actor_id, action, entity_type, entity_id, details_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                actor_id,
                action,
                entity_type,
                str(entity_id) if entity_id is not None else None,
                json.dumps(details or {}, ensure_ascii=False),
                utc_now(),
            ),
        )
