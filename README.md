# Traffic Analytics

A dashboard of traffic volume anomalies, built on data from the road radar sensors of JSC "Minimaks-94". Analysis modules (one per road section) find anomalies and fill in gaps in the data, and the dashboard shows the result: time series, a map of anomalies and a comparison with the customer's corporate system. Requirements: [docs/requirements.md](docs/requirements.md).

## Stack

- **Backend:** Python 3.13, [FastAPI](https://fastapi.tiangolo.com/), [Turso](https://turso.tech/) (libSQL, a local file in development).
- **Frontend:** [React](https://react.dev/), TypeScript, [Vite](https://vite.dev/).
- **Analysis:** Python, pandas.
- **Tools:** [uv](https://docs.astral.sh/uv/) for Python, npm for the frontend.

Why these: [docs/adr/](docs/adr/).

## How it works

```
analysis/<road>/  →  analysis/output/<road>/  →  import  →  database  →  FastAPI  →  React
  (module)            (files, by the contract)
```

The analysis modules know nothing about the web: each one writes files to `analysis/output/<road>/` following the shared [data contract](docs/contract.md), and the backend imports them into the database. The customer's raw exports stay on your computer in `analysis/data/raw/` and never go into the repository.

| Path | What's there |
| --- | --- |
| `backend/` | FastAPI app |
| `frontend/` | React app |
| `contract/` | the data contract (Pydantic models) and its check |
| `analysis/a133/` | module for A-133, approach to Lipetsk |
| `analysis/a134/` | module for A-134, approach to Voronezh |
| `analysis/r298/` | module for R-298 Kursk – Borisoglebsk |
| `analysis/r22/` | module for R-22 "Caspian", approach to Saratov |
| `analysis/output/` | results of the modules (committed) |
| `analysis/data/raw/` | the customer's raw data (not committed) |
| `docs/` | requirements, contract, decisions in `docs/adr/` |

## Getting started

You need [uv](https://docs.astral.sh/uv/getting-started/installation/) and [Node.js](https://nodejs.org/) 24. uv installs the right Python version by itself.

```sh
uv sync                                       # Python packages for everything, into .venv
uv run uvicorn backend.main:app --reload      # backend: http://localhost:8000, API docs at /docs
```

In a second terminal:

```sh
cd frontend
npm install
npm run dev                                   # dashboard: http://localhost:5173
```

An analysis module:

```sh
uv run python -m analysis.a134                # run the module
uv run python -m contract.validate            # check every set in analysis/output/
```

## Checks

Run them before you open a pull request:

```sh
uv run ruff check                             # Python lint
uv run ruff format --check                    # Python formatting (fix with: uv run ruff format)
uv run pytest                                 # Python tests
cd frontend && npm run lint && npm run build  # frontend lint, types and build
```

## Team

| Who | Area |
| --- | --- |
| @donutello | repository, CI/CD, frontend |
| @technostd | backend, data contract (shared models) |
| @mmsh55 | module A-133, its part of the contract |
| @Lexandrine | module A-134, its part of the contract |
| @nastGU | module R-298, its part of the contract |
| @Kishulia | module R-22, its part of the contract |

The plan is in the issues and in the pinned "Roadmap" issue.

## How we work

- One branch per task: `<area>/<short-name>`, for example `analysis/a134-gaps` or `frontend/map`. Changes reach `main` only through a pull request.
- Commit messages: `type(area): what changed`, for example `feat(a134): detect stuck sensors` or `fix(backend): empty series`.
- Everything is in English (code, comments, commits, docs, issues), except the text users see in the dashboard, which is in Russian.
- In the pull request, name the issue it closes: `Closes #12`.

## License

[MIT](LICENSE)
