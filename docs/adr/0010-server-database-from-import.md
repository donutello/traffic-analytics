# 0010. The deployed server builds its database during the deploy

- Status: accepted
- Date: 2026-11-15
- Author: @donutello

## Context

Issue #9 asks how the production server gets its database: a Turso Cloud database, an embedded replica of one, or a local file built by the import during deploy ([ADR 0005](0005-database-turso.md) left this open). What the server can use is limited by what is in the repository: the customer's raw data is private and never committed, while the modules' results in `analysis/output/` are committed and publishable (they are what the dashboard shows anyway). The database has always been disposable: the import rebuilds it from those files ([ADR 0004](0004-data-flow-through-files.md)), and we only show the dashboard to the customer, never the raw exports.

## Decision

- The server gets a **local libSQL file that the deploy itself builds**: after `git pull`, the deploy runs `uv run python -m backend.load`, which loads every committed set in `analysis/output/` into the file at `DATABASE_PATH`. Then FastAPI serves the API and the built frontend from that one file. `docs/deploy.md` has the steps.
- A **Turso Cloud database and an embedded replica are deferred**, not rejected: they become interesting when the raw data can be shipped to a server privately or the results outgrow a rebuilt file. Nothing about the decision blocks the switch: `backend/db.py` already uses the `libsql` client, which connects to both a file and a hosted database ([ADR 0005](0005-database-turso.md)); only the connection target and a token in the environment change.

## Alternatives

- **Turso Cloud database.** One account and one secret for a database that is read-only and rebuildable from the repository in seconds. The cloud would store a copy of exactly what git already has.
- **Embedded replica of a cloud database.** Its point is fast reads from a local copy that syncs from the cloud; our local copy is simply the file the import writes, with no cloud to sync from.
- **Ship the `.db` file as a build artifact.** Then the database is something we carry around and can forget to refresh; the import in the deploy is one command and always matches the checked-out `main`.

## Consequences

- The server shows the publishable results of all roads, never raw data — which is what the customer asked to see anyway.
- The import is idempotent, so every deploy that runs it refreshes the data: pulling `main` and re-running the import is the whole update story.
- No database account, token or sync to babysit during the semester; with today's setup the server needs no secrets (if Turso comes later, `TURSO_AUTH_TOKEN` lives outside the repository).
- The results of a road reach the demo and the server as soon as the analyst commits them to `main` and CI is green; nothing is deployable "early" outside the repository.
- ADR 0001 (FastAPI) and ADR 0005 (Turso/libSQL) stay valid untouched: this ADR only picks the option ADR 0005 already prepared for the local file.
