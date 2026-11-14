"""Connection to the database: a local Turso (libSQL) file, see docs/adr/0005-database-turso.md.

The file is rebuilt from analysis/output/ by the import command, so it is never committed.
Set DATABASE_PATH to keep it somewhere else.
"""

import os
import sys
from collections.abc import Iterator
from pathlib import Path

import libsql

DATABASE_PATH = os.environ.get("DATABASE_PATH", str(Path(__file__).parent.parent / "traffic.db"))
SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def connect(path: str = DATABASE_PATH) -> libsql.Connection:
    db = libsql.connect(path)
    db.execute("PRAGMA foreign_keys = ON")
    return db


def ensure_schema(db: libsql.Connection) -> None:
    """Create all tables and indexes of backend/schema.sql. Idempotent, safe to re-run."""
    db.executescript(SCHEMA_PATH.read_text("utf-8"))
    db.commit()


def main() -> int:
    """uv run python -m backend.db: create the tables in the configured database."""
    db = connect()
    try:
        ensure_schema(db)
    finally:
        db.close()
    print(f"tables are ready in {DATABASE_PATH}")
    return 0


def get_db() -> Iterator[libsql.Connection]:
    """FastAPI dependency: one connection per request, `db: Annotated[..., Depends(get_db)]`."""
    db = connect()
    try:
        yield db
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
