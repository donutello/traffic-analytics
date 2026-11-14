# 0009. Backend: one package per feature, controller / service / repository inside

- Status: accepted
- Date: 2026-11-14
- Author: @technostd (the shape follows @Lexandrine's PRs #51 and #52)

## Context

The teacher asked to break the backend into modules and to implement a three-layer architecture. At the same time the API must not change at all: the frontend (`frontend/src/api/index.ts`) and the prototype files in `frontend/public/mock/` stay as they are ([ADR 0007](0007-frontend-api-shapes-from-day-one.md)), and `tools/gen_mock.py`, the README commands and the tests all use the module paths `backend.main`, `backend.load` and `backend.db`.

@Lexandrine explored exactly this shape first. PR #51 added A-134-only endpoints (`/api/v1/a134/...`) and `backend/import_a134.py`; PR #52 split them into `backend/sensors/`, `backend/series/`, `backend/anomalies/`, `backend/importer/` packages with `controllers` / `services` / `repositories` layers per road. Then the generic API of issues #5–#7 was built in `backend/main.py` (all roads, mock-verified responses) and merged over her branch: her road-specific routes and her import had no users left, because the generic endpoints and `backend/load.py` do the same work for every road, a134 included.

## Decision

One package per feature, three plain modules inside, the nomenclature (controller/service/repository) from @Lexandrine's PR #52:

```
backend/
├── main.py            # composes the app: includes the feature routers, /api/health
├── db.py              # the single storage access point: connect, schema, get_db (ADR 0005)
├── schema.sql
├── load.py            # CLI shell: python -m backend.load calls the importer service
├── common/            # helpers the features share (time/period parsing, query params)
├── meta/              # GET /api/meta
├── series/            # GET /api/series: hour rows, day/week rollups
├── sensors/           # GET /api/sensors: the map
├── anomalies/         # GET /api/anomalies and /api/anomalies/{id}
├── comparison/        # GET /api/comparison: ours against the corporate system
└── importer/          # the import: files → database (called by load.py)
```

- `controllers.py` — the feature's `APIRouter` under `/api`: route paths, query parameter validation and parsing only.
- `services.py` — the business logic: granularity rollups, period overlap matching, Russian display labels, the import's validate → transform steps.
- `repositories.py` — SQL only. Response models (Pydantic) live with their controller, because they are part of the API surface.
- Cross-feature reuse goes one way: `comparison` reads anomalies through the `anomalies` package (its item builder and its anomaly query); the import reuses the stored-time format from `common`. No other imports between features.
- Dependency injection stays plain: FastAPI's `Depends(get_db)` from `backend/db.py` passed down to services as a normal argument, without a DI framework.
- The CLI shells keep their stable paths: `python -m backend.load` and `python -m backend.db` (the README, CI and tests use them); `load.py` imports the importer's service.
- `db.py` stays what it was and is now written down as such: the one place that opens a connection. Every other backend file gets the connection passed in.
- What #51 brought is retired deliberately, not silently: the `/api/v1/a134/...` controllers (the generic `/api/...` routes serve every road, a134 included), `backend/import_a134.py` (one more copy of `backend/load.py`), and her a134 import/SQL modules (the generic import reads the same files through the contract, and her SQL ideas — filter-by-`road`, one table for both anomaly sources — were already how the generic code works). Her `analysis/output/a134/` data stays and flows through the generic import.

## Alternatives

- **Keep the road-specific routers of #51.** They were the right first step (a working vertical slice with tests), but once the generic API existed they were dead code: two endpoints for the same data, and the frontend only ever calls `/api/...`.
- **Her #52 layer packages kept as-is, one file per road inside** (`controllers/a134.py`): a natural shape while every road grows its own API. With one generic API there is exactly one controller per feature, so a whole package per layer for a single file is one nesting level for nothing — hence plain `controllers.py` / `services.py` / `repositories.py` modules.
- **One `main.py` for everything** (what was merged first): simple, but 600+ lines mixing five features, HTTP plumbing and Russian labels — this is exactly what the teacher asked to break apart.
- **Layers as top-level packages** (`backend/controllers/`, `backend/services/`, `backend/repositories/`): classic textbook split, but every new feature then means edits in three unrelated packages, while the feature-first split keeps a feature in one folder.
- **A DI framework (dependency-injector, fastapi-injector):** more concepts than a student project needs; plain functions plus `Depends` already cover it.

## Consequences

- More files, but each has one job and can be read alone; a new endpoint touches only its own feature folder.
- The tests kept their promise: `backend/test_main.py` still compares every `/api/...` response with the mock files, unchanged, because the routes, models and logic were moved, not rewritten.
- `load.py` re-exports the importer's `main`; `test_main.py` and `test_load.py` keep working, `test_load.py` now imports `backend.importer.services` where it monkeypatches internals.
- Two module paths are now frozen promises (README and teammates' habits): `backend.load` and `backend.db`. Anything else may move.
- Thanks to @Lexandrine for trying the shape first: the package names, the controller/service/repository naming and her per-road slice (#51) are what made the generic split an obvious next step.
