"""Apply ``wwnn/db/migrations/*.sql`` in order; idempotent."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from loguru import logger

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def connect(db_path: str | Path) -> sqlite3.Connection:
    db_path = Path(db_path)
    if str(db_path) != ":memory:":
        db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=30, isolation_level=None)  # autocommit
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    if str(db_path) != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL")   # bot + orchestrator share the file
    return conn


def migrate(conn: sqlite3.Connection) -> list[str]:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations (name TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    done = {r["name"] for r in conn.execute("SELECT name FROM schema_migrations")}
    applied = []
    for sql_file in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if sql_file.name in done:
            continue
        logger.info(f"applying migration {sql_file.name}")
        conn.executescript("BEGIN;\n" + sql_file.read_text(encoding="utf-8") +
                           f"\nINSERT INTO schema_migrations VALUES ('{sql_file.name}', datetime('now'));\nCOMMIT;")
        applied.append(sql_file.name)
    return applied


def open_db(db_path: str | Path) -> sqlite3.Connection:
    conn = connect(db_path)
    migrate(conn)
    return conn
