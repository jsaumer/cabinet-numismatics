## What this changes

<!-- A sentence or two. Link the issue if there is one. -->

## How it was verified

<!-- Tests added/updated, and anything checked by hand against a running stack. -->

## Checklist

- [ ] `ruff check .` and `ruff format --check .` pass in `backend/`
- [ ] `pytest` passes in `backend/`
- [ ] Tests cover the behavior change (or it's a docs/refactor-only change)
- [ ] Docs in `docs/` updated in this same commit if behavior changed
- [ ] Schema changes are an Alembic revision, reviewed by hand
- [ ] No secrets in responses, logs, or URLs
