# Backend

FastAPI application (to be scaffolded): REST API (OpenAPI title: "Cabinet API") under `/api/`, plus in-process
background tasks for thumbnail generation and price lookups.

Planned layout:

```
backend/
├── Dockerfile
├── pyproject.toml
└── app/
    ├── main.py        # FastAPI app + startup (ensure PHOTO_DIR)
    ├── models/        # SQLAlchemy models
    ├── routers/       # items, photos, estimates, reference
    └── services/      # photo processing, price sources
```
