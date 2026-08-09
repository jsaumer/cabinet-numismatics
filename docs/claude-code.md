# Developing Cabinet with Claude Code

From Phase 0 onward, Cabinet is built and planned in
[Claude Code](https://code.claude.com/docs), Anthropic's agentic coding tool,
run inside the Claude desktop app. It works directly in the repository — creating and editing files in place, running
the compose stack, executing migrations and tests, and iterating on real code —
rather than handing back files to copy in.

Cabinet is developed using Claude Code inside the **Claude desktop app** (the
Code tab), not the terminal CLI. It is the same Claude Code underneath — the
`CLAUDE.md` context file, `@`-imports, and the `/init`, `/memory`, and
`/context` commands all behave identically; only how you open a session
differs.

## One-time setup

1. **Get the repo on disk.** Unzip the scaffold into `cabinet-numismatics/`,
   then initialize git and commit the baseline:
   ```bash
   cd cabinet-numismatics
   git init
   git add -A
   git commit -m "Initial scaffold: compose, proxy, docs, roadmap"
   ```
2. **Open the Claude desktop app** and open the `cabinet-numismatics/` folder as
   the working project in the Code tab. Installation and current setup details
   are in the official docs at https://code.claude.com/docs.
3. **Start a session** pointed at the repo root. Claude Code reads the
   repo-root `CLAUDE.md` automatically at session start.

## How Claude Code loads project context

Claude Code reads a `CLAUDE.md` file at the repository root at the start of
every session and treats it as persistent context. This repo ships one, seeded
from the project brief: architecture, conventions, build commands, and the
current next step. Keep it under ~200 lines and specific — it is loaded into
context every session, and shorter, concrete instructions are followed more
reliably.

`CLAUDE.md` imports the deeper docs with `@path` references (e.g.
`@docs/roadmap.md`), so the roadmap and architecture load alongside it. When the
design changes, update `CLAUDE.md` and the affected `docs/` file in the same
commit.

Useful in-session commands:

- `/init` — generate or improve a `CLAUDE.md` from the codebase.
- `/memory` — view and edit the memory files Claude Code is using.
- `/context` — confirm which memory files actually loaded this session.

## Conventions that carry over (and one that doesn't)

Carry over: minimal three-service architecture, single/minimal images, docs kept
in sync with the design, concise and direct communication.

Does **not** apply here: the earlier "unzip and restore folders under `docs/`
and `proxy/`" step. That was an artifact of the chat-based file delivery, where
outputs were flattened. In Claude Code the real directory structure is edited in
place, so there is nothing to un-flatten.

## Personal vs. shared instructions

- `CLAUDE.md` is committed and shared (relevant if Cabinet is open-sourced
  later).
- For private, machine-local notes (sandbox URLs, scratch test data), use
  `CLAUDE.local.md` at the repo root and add it to `.gitignore` — it loads
  alongside `CLAUDE.md` but is never committed.
