# 0005. Database: Turso (libSQL)

- Status: accepted
- Date: 2026-10-17
- Author: @donutello

## Context

The database holds what the import loads from `analysis/output/`: sensors, about a million hourly rows for all roads over three years, anomalies and events. The dashboard only reads it, and it can always be rebuilt from the files ([ADR 0004](0004-data-flow-through-files.md)). Critical endpoints must handle 100 requests per second and answer within one second (NFR3, NFR4). Most teammates work on Windows, and running a database server there (for example PostgreSQL in Docker) is extra work for everyone.

## Decision

- The database is [Turso](https://turso.tech/), used through its Python client [`libsql`](https://pypi.org/project/libsql/). libSQL is an open-source fork of SQLite: the same SQL and the same file format.
- In development and tests it is a local file (`traffic.db`, ignored by git, path set by `DATABASE_PATH`): no server, no account, no Docker. The connection code is in `backend/db.py`.
- In production the same library can connect to a hosted Turso Cloud database, or keep a local copy of it that syncs from the cloud (an "embedded replica"). Which one we use is decided in the deploy issue.
- We write plain SQL, without an ORM. The tables are simple, and the main work (grouping hours into days and weeks) is easiest to read as SQL.
- We use Python 3.13: `libsql` publishes ready-made Windows packages for Python up to 3.13 only.
- No Redis. If an endpoint is too slow, we first add indexes, then a simple in-memory cache in the backend that is cleared after an import.

## Alternatives

- **PostgreSQL.** Powerful, but it is a server that everyone has to install or run in Docker, for data that is read-only and rebuilt from files.
- **Plain SQLite (Python's built-in `sqlite3`).** Works the same locally and needs no extra package, but has no hosted option: in production the database file would live on the server's disk.
- **`pyturso`, the newer Turso engine (a rewrite of SQLite in Rust).** It is where Turso is heading, but it has no ready-made Windows packages yet, so installing it on Windows would mean building it from source. We can switch later: it keeps the SQLite file format and SQL.
- **No database: load the files into memory at startup.** The simplest, but grouping by day and week, filters and the comparison would all be written by hand instead of in SQL.

## Consequences

- Setup is just `uv sync`: the database is a file that the import command creates.
- The data is never edited in the database, so the database is never backed up: the files in `analysis/output/` are the backup.
- `libsql` is a young library, and its last release was in 2025. If it causes trouble, we can switch to the built-in `sqlite3` with almost the same code, because both follow Python's standard database API.
- When `libsql` or `pyturso` ships packages for newer Python versions on Windows, we can move to a newer Python.
