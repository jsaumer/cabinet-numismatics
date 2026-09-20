# Contributing to Cabinet

Thanks for taking an interest. Cabinet is a single-user, self-hosted
numismatics collection manager; it is intentionally small and stays that way.
Contributions that keep it simple are very welcome.

## Before you start

- **Bugs**: open an issue with steps to reproduce. If it involves data, say
  what the item looked like (no need to share photos).
- **Features**: check [docs/roadmap.md](docs/roadmap.md) first: the intended
  scope, what's built, and what's deliberately deferred are all recorded
  there. Opening an issue before a large PR saves everyone time. An
  application login is out of scope: Cabinet runs on a trusted network or
  behind an authenticating reverse proxy, and v1.0.0 will ship that way.
- **Questions**: open a discussion or issue; there's no separate forum.

## Development setup

You need Docker. You do *not* need Node or Python on the host: the frontend
compiles inside the image and the backend runs in a container.

```bash
git clone https://github.com/jsaumer/cabinet-numismatics.git
cd cabinet-numismatics
cp .env.example .env          # edit the secrets
docker compose up --build
```

The backend applies database migrations itself on startup.

The app is at http://localhost/ and the API docs at
http://localhost/api/docs. To load sample data for a populated dashboard:

```bash
python scripts/seed_demo.py
```

### Working on the backend

```bash
cd backend
python -m venv .venv && .venv/bin/pip install -e ".[dev]"   # Windows: .venv\Scripts\pip
pytest                 # about 280 tests, no database required
ruff check .           # lint
ruff format .          # format
```

Tests run against in-memory SQLite with the schema created from the models,
and never touch the network: external price/rate APIs are mocked, and an
autouse fixture fails any unmocked exchange-rate fetch. SQLite timestamps
have one-second resolution, so backdate rows when a test depends on order.

To run the API outside a container: `uvicorn app.main:app --reload` with
`DATABASE_URL`, `PHOTO_DIR`, and `DOCUMENT_DIR` set, and
`REQUIRE_DOCUMENT_MOUNT=false`.

If you change the dependencies in `pyproject.toml`, regenerate the
hash-pinned `backend/requirements.txt` (the image installs exactly that
file) with the command in [docs/security.md](docs/security.md#dependencies).

### Working on the frontend

```bash
cd frontend
npm ci                 # installs exactly what package-lock.json pins
npm run dev            # proxies /api to localhost:8000
npm run build          # typecheck (tsc), then the production build
npm run e2e            # Playwright smoke tests, against a running stack
```

[frontend/README.md](frontend/README.md) covers the source layout and the
styling conventions (design tokens, system fonts only, inline SVG icons,
`money()` for amounts).

If you change dependencies, commit the updated `package-lock.json`: CI and
the container build both use `npm ci` and will fail if it's out of sync.

`docker compose up --build` also type-checks the frontend, so a clean build is
a valid substitute if you'd rather not install Node.

The Playwright tests in `frontend/e2e/` drive the pages of a running stack
(`docker compose up`, then `npm run e2e`; `BASE_URL` points them at another
host; the first run needs `npx playwright install chromium`). When a page's
behaviour or wording changes, update them in the same change.

### Database changes

Every schema change is an Alembic revision, never create-on-startup:

```bash
cd backend
alembic revision --autogenerate -m "what changed"   # with DATABASE_URL set
alembic upgrade head
```

Review the generated migration by hand; autogenerate misses server defaults
and data migrations.

## Conventions

- **Docs travel with the change.** If you alter behavior, update every
  affected document in the same commit: `README.md` (features),
  `docs/api.md`, `docs/data-model.md`, `docs/roadmap.md`,
  `docs/implementation-notes.md`, `frontend/README.md`, and the topic doc it
  touches, plus `CHANGELOG.md`. They are expected to match the code.
- **No em dashes** in interface text, docs, comments, or commit messages.
  Write the sentence so it doesn't need one (a comma, colon, period, or
  parentheses). An empty value in a table or field shows an en dash.
- **Keep the stack at three services.** Redis, object storage, and similar
  were deliberately cut; reintroducing one needs a stated reason.
- **Comments are sparse and explain *why*.** Match the density of the
  surrounding code.
- **Money is per row.** `acquisition_price`, `sold_price`, and
  `estimated_value` describe the whole lot, never a single piece.
- **Estimates are append-only.** Never overwrite value history.
- **Secrets never appear in responses, logs, or URLs.** See
  [docs/security.md](docs/security.md).
- **Price sources** go through `pricing.run_adapter`, keep their local
  checks in a `prerequisite(db, item)`, cache upstream responses with
  `pricing.cached_fetch`, and are never sent collection data. See
  [docs/price-sources.md](docs/price-sources.md).
- Tests are expected for behavior changes.

## What CI runs

`.github/workflows/ci.yml`, on every push to `main` and every pull request:

- **backend**: `ruff check`, `ruff format --check`, and `pytest` on Python
  3.10 (the floor in `pyproject.toml`) and 3.14 (what the image runs).
- **frontend**: `npm ci` and `npm run build` (typecheck and build) on
  Node 22.
- **stack**: builds and starts the compose stack, waits for
  `/api/health`, confirms the schema migrated itself, smoke-tests the API
  with curl through the proxy (create, trash, restore, permanent delete,
  settings, metrics, the test alert), rehearses an in-app backup and
  `scripts/restore.sh` with an attached PDF, then runs the Playwright tests.
  If you change an endpoint those steps use, update them: pytest won't
  catch it.
- **publish**: on a `v*` tag only, after the three jobs pass, pushes the
  backend and proxy images to GHCR.

`.github/workflows/security.yml` runs on the same events and weekly:
`pip-audit` against `backend/requirements.txt`, `npm audit` on the frontend's
runtime dependencies, and Trivy scans of both images (high and critical,
fixable only). It is separate from CI so a newly published CVE doesn't block
an unrelated change.

## Pull requests

1. Branch off `main`.
2. Keep the change focused; unrelated cleanups belong in their own PR.
3. Make sure `ruff check .`, `ruff format --check .`, and `pytest` pass, and
   that the frontend builds if you touched it.
4. Describe what changed and how you verified it.

By contributing you agree that your work is licensed under the MIT License,
the same as the rest of the project.
