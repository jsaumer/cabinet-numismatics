# Backend

FastAPI application: REST API (OpenAPI title: "Cabinet API") under `/api/`,
plus in-process background tasks for thumbnail generation and price lookups
(later phases). On startup it ensures `PHOTO_DIR` exists.

## Layout

```
backend/
├── Dockerfile
├── pyproject.toml
├── alembic.ini
├── alembic/           # migrations (baseline 0001 is empty)
├── tests/
└── app/
    ├── main.py        # FastAPI app + lifespan (ensure PHOTO_DIR)
    ├── config.py      # env settings (DATABASE_URL, PHOTO_DIR)
    ├── db.py          # engine, session factory, Base
    ├── models/        # SQLAlchemy models (Phase 1)
    ├── routers/       # health; items/photos/estimates arrive in Phase 1+
    └── services/      # photo processing, price sources (later phases)
```

## Commands (run in `backend/`)

- Install for dev: `pip install -e .[dev]`
- Run: `uvicorn app.main:app --reload` (needs `DATABASE_URL`, `PHOTO_DIR`)
- Test: `pytest` (no database required)
- Lint/format: `ruff check .` / `ruff format .`
- Migrate: `alembic upgrade head` (needs `DATABASE_URL`)
