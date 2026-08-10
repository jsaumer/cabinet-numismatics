# Contributing to Cabinet

Thanks for taking an interest. Cabinet is a single-user, self-hosted
numismatics collection manager; it is intentionally small and stays that way.
Contributions that keep it simple are very welcome.

## Before you start

- **Bugs**: open an issue with steps to reproduce. If it involves data, say
  what the item looked like (no need to share photos).
- **Features**: check [docs/roadmap.md](docs/roadmap.md) first — the intended
  scope, what's built, and what's deliberately deferred are all recorded
  there. Opening an issue before a large PR saves everyone time.
- **Questions**: open a discussion or issue; there's no separate forum.

## Development setup

You need Docker. You do *not* need Node or Python on the host — the frontend
compiles inside the image and the backend runs in a container.

```bash
git clone https://github.com/jsaumer/cabinet-numismatics.git
cd cabinet-numismatics
cp .env.example .env          # edit the secrets
docker compose up --build
docker compose exec backend alembic upgrade head
```

The app is at http://localhost/ and the API docs at
http://localhost/api/docs. To load sample data for a populated dashboard:

```bash
python scripts/seed_demo.py
```

### Working on the backend

```bash
cd backend
python -m venv .venv && .venv/bin/pip install -e ".[dev]"   # Windows: .venv\Scripts\pip
pytest                 # 69 tests, no database required
ruff check .           # lint
ruff format .          # format
```

Tests run against in-memory SQLite with the schema created from the models,
and never touch the network — external price/rate APIs are mocked, and an
autouse fixture fails any unmocked exchange-rate fetch.

### Working on the frontend

```bash
cd frontend
npm install
npm run dev            # proxies /api to localhost:8000
```

`docker compose up --build` also type-checks the frontend, so a clean build is
a valid substitute if you'd rather not install Node.

### Database changes

Every schema change is an Alembic revision — never create-on-startup:

```bash
cd backend
alembic revision --autogenerate -m "what changed"   # with DATABASE_URL set
alembic upgrade head
```

Review the generated migration by hand; autogenerate misses server defaults
and data migrations.

## Conventions

- **Docs travel with the change.** If you alter behavior, update the affected
  file in `docs/` in the same commit. `docs/api.md`, `docs/data-model.md`, and
  `docs/roadmap.md` are expected to match the code.
- **Keep the stack at three services.** Redis, object storage, and similar
  were deliberately cut; reintroducing one needs a stated reason.
- **Comments are sparse and explain *why*.** Match the density of the
  surrounding code.
- **Money is per row** — `acquisition_price`, `sold_price`, and
  `estimated_value` describe the whole lot, never a single piece.
- **Estimates are append-only.** Never overwrite value history.
- **Secrets never appear in responses, logs, or URLs.** See
  [docs/security.md](docs/security.md).
- Tests are expected for behavior changes. CI runs ruff and pytest and builds
  both images on every PR.

## Pull requests

1. Branch off `main`.
2. Keep the change focused; unrelated cleanups belong in their own PR.
3. Make sure `ruff check .`, `ruff format --check .`, and `pytest` pass.
4. Describe what changed and how you verified it.

By contributing you agree that your work is licensed under the MIT License,
the same as the rest of the project.
