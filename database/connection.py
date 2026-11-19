"""Thread-safe SQLite connection manager with WAL mode and transaction scopes."""
import sqlite3
import os
from contextlib import contextmanager
from typing import Generator
from config.settings import settings


def get_db_path() -> str:
    """Return the absolute path to the SQLite database."""
    # Resolve relative to the current working directory or config settings
    db_path = settings.DATABASE_PATH
    if not os.path.isabs(db_path):
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        db_path = os.path.join(base_dir, db_path)
    return db_path


def init_db(db_path: str | None = None) -> None:
    """Initialize database tables from schema.sql."""
    target_path = db_path or get_db_path()
    schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")

    with open(schema_path, "r", encoding="utf-8") as f:
        schema_sql = f.read()

    conn = sqlite3.connect(target_path)
    try:
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA busy_timeout = 5000;")
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.executescript(schema_sql)
        conn.commit()
    finally:
        conn.close()


def get_db_connection(db_path: str | None = None) -> sqlite3.Connection:
    """Create a SQLite connection configured with WAL and dict-like row access."""
    target_path = db_path or get_db_path()
    conn = sqlite3.connect(target_path, timeout=5.0)
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def transaction_scope(db_path: str | None = None) -> Generator[sqlite3.Connection, None, None]:
    """Transactional context manager with automatic commit on success and rollback on error."""
    conn = get_db_connection(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE;")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
