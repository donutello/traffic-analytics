# 0006. Data contract as Pydantic models

- Status: accepted
- Date: 2026-10-17
- Author: @donutello

## Context

By [ADR 0004](0004-data-flow-through-files.md), the road modules and the backend exchange files. The format must be easy to write from pandas, checked automatically before import, and cover what the dashboard needs: three states of the data (FR2), mega-anomalies with their causes (FR3) and the comparison with the corporate system (FR4). Both sides are written in Python ([ADR 0001](0001-backend-fastapi.md)).

## Decision

- The contract is a set of [Pydantic](https://docs.pydantic.dev/) models in `contract/models.py`. They are the single source of truth. [docs/contract.md](../contract.md) explains them in plain words.
- The same models are used by the road modules (to check what they wrote: `uv run python -m contract.validate`) and by the backend (to read the files during import). So both sides always follow the same rules.
- The hourly series is CSV (`series.csv`): it is the biggest file, pandas writes it easily and Excel opens it. Sensors, anomalies and events are JSON: there are few of them, and they have nested fields and `null`.
- Time is ISO 8601 with an offset, always at the start of an hour. Anomaly intervals are half-open, `[starts_at, ends_at)`. This avoids time zone mix-ups and the question of whether the last hour counts.
- Every id starts with the road code (`a134-...`), so ids are unique across the whole database.
- Each hour of the series carries its state (`normal`, `anomaly`, `imputed`), and each anomaly has a `category` (`traffic` or `technical`). The dashboard shows them as they are and doesn't repeat the modules' logic.
- The corporate system's anomalies use the same format as ours (`corporate_anomalies.json`).
- Owners: @technostd owns the shared models and the import. Each analyst owns the export of their road. A change to the contract is one pull request that @technostd and every affected analyst approve.
- The first version (draft v0) is ported from an earlier draft. The owners confirm or change it in issue #1.

## Alternatives

- **JSON Schema files.** They work with any language, but both sides are now Python, and Pydantic models are shorter, easier to read and give clear error messages.
- **JSON for everything.** Three years of hourly data for several sensors is several times bigger in JSON and slower to read.
- **Parquet.** Smaller and typed, but binary: no readable diffs and it doesn't open in Excel.
- **The backend works out each hour's state from the anomaly intervals.** Filled-in hours would still have to be marked in the series, and the same rule in two places would drift apart over time.

## Consequences

- A set with mistakes is caught by `contract.validate` before it reaches `main`: the CI runs it on every pull request (issue #2).
- The column order of `series.csv` is fixed: adding a column is a contract change. Adding a new allowed value (a way to fill gaps, an event category) is easy. Renaming or removing a field means changing the import and every module at the same time.
- A Pydantic model is also easy to reuse in the API responses if it fits.
