# Developing Cabinet with Claude Code

From Phase 0 onward, Cabinet is built and planned in
[Claude Code](https://code.claude.com/docs), Anthropic's agentic coding tool,
run inside the Claude desktop app. It works directly in the repository
(creating and editing files in place, running the compose stack, executing
migrations and tests, and iterating on real code) rather than handing back
files to copy in.

Cabinet is developed using Claude Code inside the **Claude desktop app** (the
Code tab), not the terminal CLI. It is the same Claude Code underneath: the
`CLAUDE.md` context file, `@`-imports, and the `/init`, `/memory`, and
`/context` commands all behave identically; only how you open a session
differs.

None of this is required to contribute. The repository is an ordinary git
project, and [CONTRIBUTING.md](../CONTRIBUTING.md) covers working on it with
any editor.

## One-time setup

1. **Get the repo on disk.**
   ```bash
   git clone https://github.com/jsaumer/cabinet-numismatics.git
   cd cabinet-numismatics
   cp .env.example .env          # edit the secrets
   ```
2. **Open the Claude desktop app** and open the `cabinet-numismatics/` folder as
   the working project in the Code tab. Installation and current setup details
   are in the official docs at https://code.claude.com/docs.
3. **Start a session** pointed at the repo root. Claude Code reads the
   repo-root `CLAUDE.md` automatically at session start.

Docker is the only hard requirement on the host: `docker compose up --build`
builds and runs everything, the frontend included. A Python virtual
environment in `backend/` (`pip install -e ".[dev]"`) lets a session run
`pytest` and `ruff` directly; Node is needed only to run the Vite dev server
or Playwright outside a container.

## How Claude Code loads project context

Claude Code reads a `CLAUDE.md` file at the repository root at the start of
every session and treats it as persistent context. This repo ships one:
architecture, repo layout, conventions, build and test commands, the current
status, and the rules that bite most often. It has grown to about 350
lines; keep it from growing further, and move area rules to
docs/implementation-notes.md. It is loaded into context every session, and
shorter, concrete instructions are followed more reliably.

`CLAUDE.md` imports the deeper docs with `@path` references
(`@docs/roadmap.md`, `@docs/architecture.md`, and
`@docs/implementation-notes.md`), so the roadmap, the architecture, and the
per-release implementation notes load alongside it. The split is deliberate:
`CLAUDE.md` holds what every session needs, and
[implementation-notes.md](implementation-notes.md) holds what each release
added and the rules it left behind, read for whichever area a change
touches. A correction made twice across sessions gets written down in one of
the two.

Useful in-session commands:

- `/init`: generate or improve a `CLAUDE.md` from the codebase.
- `/memory`: view and edit the memory files Claude Code is using.
- `/context`: confirm which memory files actually loaded this session.

## How a change is made

- **In the working tree.** A session edits files in place, runs `pytest` and
  `ruff` in `backend/`, and brings the stack up with
  `docker compose up --build` when a change needs a real database, nginx, or
  a browser. Commits and pushes happen when the owner asks for them.
- **Docs in the same commit.** When behaviour changes, every affected
  document is updated with it: `README.md`, `docs/api.md`,
  `docs/roadmap.md`, `docs/implementation-notes.md`, `frontend/README.md`,
  the topic doc, and `CHANGELOG.md`. Before a release, those are reread
  against the diff since the last tag.
- **CI's other half.** The compose job's curl smoke test, the backup →
  restore drill, and the Playwright tests in `frontend/e2e/` cover what
  pytest can't. When an endpoint or a page changes, they change too.
- **Live price sources.** `docker compose exec backend python
  scripts/check_sources.py` probes Numista or PCGS with the saved key and
  prints the raw response; unit tests only ever see canned ones.
- **Releases.** Bump the version in `backend/pyproject.toml`, add the
  changelog entry, and push a `v*` tag: CI publishes both images to GHCR,
  and a deployment that pins those tags upgrades by changing the tag (the
  backend migrates on startup).
- **What to build.** The road to v1.0.0 in [roadmap.md](roadmap.md) is
  queued (a CI OpenAPI check, two live Numista confirmations, a README
  pass); beyond that, work comes from friction the owner reports while
  entering the collection, and parked or tabled items are not built
  unprompted.

## Conventions that carry over (and one that doesn't)

Carry over: minimal three-service architecture, single/minimal images, docs kept
in sync with the design, concise and direct communication, and no em dashes
anywhere (interface text, docs, comments, commit messages).

Does **not** apply here: the earlier "unzip and restore folders under `docs/`
and `proxy/`" step. That was an artifact of the chat-based file delivery, where
outputs were flattened. In Claude Code the real directory structure is edited in
place, so there is nothing to un-flatten.

## Personal vs. shared instructions

- `CLAUDE.md` is committed and shared: the repository is public, so it
  holds nothing private and no secrets.
- For private, machine-local notes (sandbox URLs, scratch test data), use
  `CLAUDE.local.md` at the repo root. It is already in `.gitignore`, loads
  alongside `CLAUDE.md`, and is never committed.
- Claude Code also keeps its own per-user memory files outside the
  repository (`/memory` shows them). Machine details belong there or in
  `CLAUDE.local.md`, not in `CLAUDE.md`.
