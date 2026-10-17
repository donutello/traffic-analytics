# 0004. Road modules hand data to the backend as files

- Status: accepted
- Date: 2026-10-17
- Author: @donutello

## Context

Four analysts each write a module for their road. The backend and the frontend need data from the first week, long before the algorithms are ready. The data is not live: a module processes a three-year archive, and the result changes only when the algorithm changes. The customer's raw exports must not be published, and the repository is public.

## Decision

```
analysis/<road>/  →  analysis/output/<road>/  →  import  →  database  →  FastAPI  →  React
  (module)            (files, by the contract)
```

- A module reads the raw export from `analysis/data/raw/<road>/` (ignored by git) and writes its result to `analysis/output/<road>/` following the data contract ([docs/contract.md](../contract.md)). The result is committed.
- An import command (part of the backend) reads these files and loads them into the database. The dashboard only works with the database.

## Alternatives

- **Modules write straight into the database.** Analysts would need to know the database tables, and every change of the tables would break four modules at once.
- **The backend runs the modules itself.** The server would need the customer's raw data, which is not in the repository and must not be.
- **A separate Python service per module with its own API.** More services to run and deploy, for data that changes once every few days.

## Consequences

- Everyone can work separately: an analyst checks their result with `uv run python -m contract.validate`, while the backend and frontend use the `_example` set until real data arrives.
- The results of the modules are visible in pull request diffs and can be rebuilt without access to the customer's system.
- The contract is the main thing the team has to agree on: changing it affects both the modules and the import ([ADR 0006](0006-data-contract-as-pydantic-models.md)).
- The repository grows by the size of the hourly series: a few megabytes per sensor for three years. If that becomes a problem, the series can be compressed or moved to GitHub releases without changing anything else.
