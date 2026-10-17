# Architecture decision records

An ADR is a short note about a decision that affects the whole team: what we chose, why, and what it costs us. We don't rewrite old ADRs. If a decision changes, we write a new ADR and mark the old one as "replaced by ADR NNNN".

| No. | Decision | Status |
| --- | --- | --- |
| [0001](0001-backend-fastapi.md) | Backend: FastAPI | accepted |
| [0002](0002-frontend-react-vite.md) | Frontend: React, TypeScript and Vite | accepted |
| [0003](0003-one-repository-one-python-project.md) | One repository, one Python project | accepted |
| [0004](0004-data-flow-through-files.md) | Road modules hand data to the backend as files | accepted |
| [0005](0005-database-turso.md) | Database: Turso (libSQL) | accepted |
| [0006](0006-data-contract-as-pydantic-models.md) | Data contract as Pydantic models | accepted |

## How to add one

Copy the template below to `NNNN-short-name.md` with the next number, fill it in and add a line to the table. An ADR comes in its own pull request or together with the change it explains.

```markdown
# NNNN. Title

- Status: proposed | accepted | replaced by ADR NNNN
- Date: YYYY-MM-DD
- Author: @nickname

## Context

What problem we have, what limits us, what we know.

## Decision

What we chose.

## Alternatives

What else we considered and why we said no.

## Consequences

What gets easier, what gets harder, what we now have to do.
```
