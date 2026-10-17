# 0001. Backend: FastAPI

- Status: accepted
- Date: 2026-10-17
- Author: @donutello

## Context

The dashboard needs a small backend: load the results of the road modules into a database and serve them to the frontend as JSON (time series, anomalies, the comparison with the corporate system). There is no user input to save, no accounts, no admin pages.

Most of the team writes the road modules in Python with pandas. A first draft of the project used Laravel (PHP), but that meant two languages, two package managers and two ways to describe the same data, all for a backend that only reads data and returns it.

## Decision

The backend is [FastAPI](https://fastapi.tiangolo.com/) on Python, run with uvicorn. It lives in `backend/` and has only API endpoints under `/api/...`. Responses are described with Pydantic models, so FastAPI writes the API documentation by itself at `/docs`.

## Alternatives

- **Laravel (PHP).** A mature framework with a lot built in, but most of it (auth, sessions, queues, templates) we don't need, and the backend developer would have to repeat the data contract in PHP.
- **Django.** Also Python, but it comes with an ORM, admin and templates: more to learn than we use.
- **Flask.** Simple, but without data validation and automatic API docs, which FastAPI gives for free.

## Consequences

- One language for the backend and the road modules: the backend can import the contract models directly ([ADR 0006](0006-data-contract-as-pydantic-models.md)).
- The frontend developer reads the always up-to-date API description at `http://localhost:8000/docs` instead of a hand-written document.
- Things like auth or an admin panel would have to be added by hand, but the requirements don't ask for them.
