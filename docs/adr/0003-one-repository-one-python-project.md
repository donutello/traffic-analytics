# 0003. One repository, one Python project

- Status: accepted
- Date: 2026-10-17
- Author: @donutello

## Context

Six people work on four road modules, the backend and the frontend. The road modules and the backend both need the same data contract. Most teammates work on Windows, and setting up tools should take minutes, not an evening.

## Decision

- Everything lives in one repository: `backend/`, `contract/`, `analysis/<road>/` and `frontend/`.
- All Python code is one [uv](https://docs.astral.sh/uv/) project with one `pyproject.toml` at the root. `uv sync` installs everything into `.venv`, and `uv run ...` runs commands in it. uv installs the right Python version by itself (from `.python-version`).
- One set of checks for all Python code: `uv run ruff check`, `uv run ruff format --check`, `uv run pytest`.
- Each analyst works only inside their own `analysis/<road>/` directory.

## Alternatives

- **A separate project for each part (backend, analysis).** Cleaner borders, but the contract would have to be shared as a package between them, and everyone would set up two environments.
- **A separate repository for each part.** A change to the contract would need several pull requests in different repositories at the same time.
- **pip and requirements.txt.** Works, but there is no lock file by default, and you set up Python and the virtual environment by hand.

## Consequences

- One command to set up and one command to check everything.
- Analysts also install FastAPI and the backend also installs pandas. That costs some disk space and nothing else.
- A dependency added by one person is installed for everyone, so we add one only when an issue needs it.
