"""Connection to the database: a local Turso (libSQL) file, see docs/adr/0005-database-turso.md.

The file is rebuilt from analysis/output/ by the import command, so it is never committed.
Set DATABASE_PATH to keep it somewhere else.
"""

import os
from collections.abc import Iterator
from pathlib import Path

import libsql

DATABASE_PATH = os.environ.get("DATABASE_PATH", str(Path(__file__).parent.parent / "traffic.db"))


def connect(path: str = DATABASE_PATH) -> libsql.Connection:
    return libsql.connect(path)


def get_db() -> Iterator[libsql.Connection]:
    """FastAPI dependency: one connection per request, `db: Annotated[..., Depends(get_db)]`."""
    db = connect()
    try:
        yield db
    finally:
        db.close()
