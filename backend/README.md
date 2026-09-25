# Backend

Cabinet's API: a FastAPI application serving the REST API under `/api/`
(OpenAPI title "Cabinet API", schema at `/api/openapi.json`, no interactive
docs page). Every request passes a deny-by-default gate
(`app/auth/gate.py`) before routing, and every route declares a permission
(`app/auth/permissions.py`); an undeclared route is refused. Background
work runs in-process rather than in a separate worker: scheduled price
refreshes and an hourly loop for backups, the trash clear-out, alerts, and
the heartbeat (`app/services/scheduled.py`).

## Layout

```
backend/
├── Dockerfile, docker-entrypoint.sh
├── pyproject.toml, requirements.txt   # requirements.txt is hash-pinned; see below
├── alembic.ini, alembic/              # collection schema (public), heads at 0022
├── alembic_auth.ini, alembic_auth/    # sign-in schema (cabinet_auth), heads at a0002
├── tests/                             # pytest suite, SQLite, no network
├── scripts/                           # check_sources.py: probe a live price API
└── app/
    ├── main.py         # FastAPI app, lifespan, middleware
    ├── config.py       # environment settings, startup checks
    ├── db.py           # engine, session factory, Base
    ├── cli.py           # container maintenance commands (see below)
    ├── schemas.py       # Pydantic request/response models
    ├── models/          # SQLAlchemy models (item, auth, grades_seed)
    ├── routers/         # one file per API area (items, photos, estimates,
    │                     auth, sso, share, backup, restore, settings, ...)
    ├── auth/             # gate, permissions, sessions, tokens, passwords,
    │                     oidc, trusted-header verification, audit
    └── services/         # pricing adapters, photos, backup/restore,
                          # dashboard, checklists, stack, insights, ...
```

## Migrations

Two independent Alembic chains, both run from `backend/` with
`DATABASE_URL` set:

```bash
alembic upgrade head                       # collection (schema public), head 0022
alembic upgrade head -c alembic_auth.ini   # sign-in (schema cabinet_auth), head a0002
```

The backend applies both itself on startup, collection first, in one
transaction (`AUTO_MIGRATE=true` by default). Never mix the two: a
collection migration never touches `cabinet_auth`, and vice versa.

## The CLI

`python -m app.cli <command>`, run inside the container: `status`,
`reset-password`, `sign-out-everywhere`, `unlink-identity`, `disable-sso`,
`revoke-tokens`, `backup-key` (`show`/`rotate`), `decrypt-archive`,
`verify-archive`, `write-archive`, `strip-photo-metadata`. These are the
recovery path when the app itself can't be reached: they take effect in
the running backend at once, no restart.

## Commands (run in `backend/`)

- Install for dev: `pip install -e .[dev]`
- Run: `uvicorn app.main:app --reload`, with `DATABASE_URL`, `PHOTO_DIR`,
  and `DOCUMENT_DIR` set, `REQUIRE_DOCUMENT_MOUNT=false`, and
  `PUBLIC_ORIGINS=http://localhost:5173` with `AUTH_INSECURE_HTTP=true`
  for the Vite dev server
- Test: `pytest` (SQLite, created from the models; every outbound call is
  mocked, so no network access is needed or allowed)
- Lint/format: `ruff check .` / `ruff format .`

If you change `pyproject.toml`'s dependencies, regenerate the hash-pinned
`requirements.txt` (the image installs exactly that file) with the command
in [docs/security.md](../docs/security.md#dependencies).
