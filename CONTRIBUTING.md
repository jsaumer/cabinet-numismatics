# Contributing to Cabinet

Thanks for taking an interest. Cabinet is a single-user, self-hosted
numismatics collection manager; it is intentionally small and stays that way.
Contributions that keep it simple are very welcome.

## Before you start

- **Bugs**: open an issue with steps to reproduce. If it involves data, say
  what the item looked like (no need to share photos).
- **Features**: check [docs/roadmap.md](docs/roadmap.md) first: the intended
  scope, what's built, and what's deliberately deferred are all recorded
  there. Opening an issue before a large PR saves everyone time. Cabinet now
  has its own sign-in (one admin, scoped API tokens; roadmap Phase 7, P8
  A1); single sign-on (P8 A2) is next. Talk to us before starting on
  authentication work.
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

The app is at http://localhost/, and the OpenAPI schema at
http://localhost/api/openapi.json for a signed-in session (there is no
interactive docs page). The sample `.env` sets `PUBLIC_ORIGINS`, which the
stack needs. Cabinet needs a sign-in: nothing but the setup page is served
until the admin exists. Open the app and enter the setup code from
`docker compose logs backend` (or the `SETUP_CODE` you set), or claim it
directly with `POST /api/auth/setup`. To load sample data for a populated
dashboard, mint a write-scoped API token (`POST /api/auth/tokens`, or reuse
the one `scripts/ci/stack-smoke.sh bootstrap` mints), then:

```bash
python scripts/seed_demo.py --token cabinet_...
# or: CABINET_TOKEN=cabinet_... python scripts/seed_demo.py
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
`DATABASE_URL`, `PHOTO_DIR`, and `DOCUMENT_DIR` set,
`REQUIRE_DOCUMENT_MOUNT=false`, and, for the Vite dev server,
`PUBLIC_ORIGINS=http://localhost:5173` with `AUTH_INSECURE_HTTP=true`.

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
host; the first run needs `npx playwright install chromium`). Cabinet needs a
sign-in, so `e2e/global-setup.ts` claims an unclaimed stack with `SETUP_CODE`
or signs in with `CABINET_USER`/`CABINET_PASSWORD` (default `owner` /
`correct horse battery`) before the suite runs, and saves the session for
every spec. Export `SETUP_CODE` when the stack is still unclaimed. When a
page's behaviour or wording changes, update them in the same change.

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
- **stack**: builds and starts the compose stack, then runs
  `scripts/ci/stack-smoke.sh` (`bootstrap`, `smoke`, `outside-in`,
  `backup-restore`, `restore-drill`, `photos`, `share`, `trusted`, in that
  order) through the
  proxy: bootstrap signs in and mints tokens; smoke covers create, trash,
  restore, permanent delete, settings, metrics, the test alert; outside-in
  checks every anonymous route is refused, each token's scope holds (read,
  write, metrics, and the session, one route per class), a revoked token is
  refused, and a spoofed `X-Forwarded-For`/`X-Real-IP` never reaches the
  audit log; backup-restore and restore-drill rehearse an in-app backup,
  `scripts/restore.sh`, and an in-app restore, each checking the admin
  password and the write token still work afterwards; photos checks nginx's
  `auth_request` gate; share checks the public share view; trusted checks,
  with the trusted-header mode off, that its routes answer 404, that no
  gateway identity header reaches the backend, that the proxy's start
  script renders the identity include (and refuses a header nginx sets),
  and that a sign-in callback's code never reaches a log. Then Playwright
  runs against the same stack. The
  script runs the same way locally, and locally it also has a `race` phase
  (two concurrent `POST /api/auth/setup` calls on a fresh stack must leave
  exactly one `201` and one `409`; it skips itself with a message on a stack
  that's already claimed, since that's what CI's stack always is by the
  time it runs). If you change an endpoint any of these steps use, update
  them: pytest won't catch it.
- **upgrade**: starts the last release before sign-in (v0.29.1, pulled from
  GHCR) against a fresh database, adds an item anonymously (that release has
  no login), switches to the images built from the commit under test, claims
  the instance, and checks both migration chains reached head and the item
  is still there. Runs `scripts/ci/upgrade-test.sh`, independent of the
  `stack` job's compose project.
- **publish**: on a `v*` tag only, after the earlier jobs pass, pushes the
  backend and proxy images to GHCR.

### Running the stack checks locally

Both scripts talk to whatever compose project you point them at with `-p`,
so they're safe to run against a scratch stack without touching one you're
already using for manual testing. Never point them at a project you rely on:
`stack-smoke.sh`'s `smoke` phase deletes items it created itself, but
`restore-drill` and the `race` phase are destructive to whatever is signed
in when they run, and `upgrade-test.sh` rebuilds the stack's images in
place. For a throwaway project (a different `-p` name and `CABINET_PORT`
than any stack you're already running):

```bash
export PUBLIC_ORIGINS=http://localhost:8081,http://proxy
export ALLOWED_HOSTS=localhost,proxy
export AUTH_INSECURE_HTTP=true
export SETUP_CODE=<32+ hex characters>
export CABINET_PORT=8081
docker compose -p cabinet-ci up --build -d
BASE=http://localhost:8081 STACK_SMOKE_STATE=/tmp/cabinet-ci-smoke \
  scripts/ci/stack-smoke.sh race
BASE=http://localhost:8081 STACK_SMOKE_STATE=/tmp/cabinet-ci-smoke \
  scripts/ci/stack-smoke.sh all
docker compose -p cabinet-ci down -v
```

```bash
COMPOSE_PROJECT_NAME=cabinet-upgrade CABINET_PORT=8082 scripts/ci/upgrade-test.sh
docker compose -p cabinet-upgrade down -v
```

Both scripts prefer variables you export in the shell over anything in
`.env` (compose does too), so they never need their own `.env` file, and
running them this way never touches one you already have.

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
