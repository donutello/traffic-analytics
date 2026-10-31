# 0007. The frontend is built against the API response shapes from day one

- Status: accepted
- Date: 2026-10-31
- Author: @donutello

## Context

The backend side of the data path is not there yet: database tables (#3), the import (#4) and the API endpoints (#5–#7) are open, the contract is still draft v0 (#1). Waiting for all of that would idle the frontend for weeks. At the same time we want the switch to the real backend to be trivial, and we do not want throwaway mock-only components rewritten later.

## Decision

The frontend is a pure consumer of the final API response shapes, served from static files while the endpoints do not exist:

- Components never build URLs or parse raw module output. Everything goes through `frontend/src/api/index.ts`, whose one `get()` and one `urls` object mirror the endpoints of issues #5 and #6 with the same names; switching to FastAPI means editing that one file.
- `frontend/public/mock/` holds the response bodies, generated from `analysis/output/_example/` by `tools/gen_mock.py` (`uv run python tools/gen_mock.py` from the repo root; it validates through the contract models first). The generator precomputes what the endpoints will compute — hour/day/week grouping of the series, per-sensor anomaly counts and mega flags, GeoJSON features, the event resolved into the anomaly detail — and attaches the Russian display labels (level, category, type, "N дней назад" pieces). The backend serves display data, not raw codes: formatting and localization stay in exactly one implementation, and the UI contains no lookup tables that could drift from the contract.
- The raw response is shown in the anomaly detail dialog next to the rendered fields, so the data the API will send is visible while the UI is being designed around it.

## Alternatives

- **MSW or a mock-service-worker layer:** a real fetch interceptor with fixtures, but a test-only dependency in production code and logic invisible in the built app.
- **A tiny mock server (FastAPI or Vite middleware):** closer to production, but another process to run for everyone, and its data would not exist in `npm run build` / `vite preview`, which is how the prototype gets demoed on the train.
- **Mock data as TypeScript constants with Russian joined in the components:** quickest to start, but bakes mock shapes into components, drags localization out of the backend, and every shape change becomes a component diff.

## Consequences

- The prototype works with `npm run build` + static file serving, no backend, offline except OSM tiles (NFR10 fallback covers that).
- Static files cannot filter, so the query parameters in `urls` are documentation of the future filters, not behavior. All example data sits inside every file.
- When #5–#7 land, two things change: the builders in `api/index.ts` switch to `/api/...` (query strings start working), and the mock folder and `tools/gen_mock.py` get deleted. Until then `gen_mock.py` must be rerun whenever the example output changes.
- The label choice (backend sends display data) is now also the backend's contract: whoever implements #5–#7 takes it from this ADR and the generated files, and technostd will shape the response models accordingly.
