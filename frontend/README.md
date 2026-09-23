# Frontend

Cabinet's user interface: a React 19 + Vite single-page application in
TypeScript, routed with react-router. It talks to the backend only through
`/api/` and loads photos from `/photos/`. There is no component library, no
chart library, and no CSS framework: three runtime dependencies (`react`,
`react-dom`, `react-router-dom`), one stylesheet, and hand-rolled SVG charts.

In the compose stack, `frontend/Dockerfile` builds the app and produces the
nginx image used as the `proxy` service (the build context is the repo root,
so `proxy/nginx.conf` is baked in too). No host Node install is needed to run
Cabinet, only to work on the frontend outside the container.

## Commands

Run in `frontend/`, after `npm ci` (which installs exactly what
`package-lock.json` pins; CI and the image build use it too).

| Command           | What it does |
|-------------------|--------------|
| `npm run dev`     | Vite dev server on :5173. Proxies `/api` to localhost:8000 (a backend run with uvicorn) and `/photos` to http://localhost (the compose stack's nginx) |
| `npm run build`   | `tsc && vite build`: the typecheck, then static files in `dist/`. There is no separate typecheck script; this is the one CI and the image build run |
| `npm run preview` | Serves the built `dist/` locally |
| `npm run e2e`     | The Playwright smoke tests, against a running stack |

## Layout

```
index.html            the shell: data-theme="dark", favicon and touch icon
public/               served at the site root, copied into dist/ as is
  logo.svg              the logo (header, README, SVG favicon)
  favicon.ico           browser-tab icon
  logo-512.png          for dashboards such as a Homepage tile
  apple-touch-icon.png  iOS home-screen icon
  logo-tile.svg         the logo on its tile background, the source of the PNGs
src/
  main.tsx, App.tsx   entry; the boot gate (setup/sign-in/restoring/signed in),
                      the header, navigation, theme toggle, and routes
  styles.css          the one stylesheet, design tokens first
  api/                the API client; import everything from "../api"
    types/              response and payload types by area (items, settings,
                        stats, imports, auth); settings.ts also holds the
                        backup and restore types (BackupFile, BackupKey,
                        RestoreStatus, RestoreInspection, RestoreOutcome);
                        auth.ts holds Me, LoginResult, AuthSession, ApiToken,
                        AuditEntry
    client.ts           the fetch wrapper and error handling: also where a
                        401 or a 403 reauth_required is caught, see "Sign-in"
                        below
    calls.ts            one function per endpoint, exported as `api`
    index.ts            re-exports it all, plus helpers such as money()
  auth/               sign-in plumbing, see "Sign-in" below: AuthContext.tsx
                      (AuthProvider, useAuth), ConfirmDialog.tsx (the
                      confirm-password dialog and its promise-based
                      service), FreshLink.tsx (a download link that confirms
                      first when it needs to), Brand.tsx (the logo and name
                      above the setup, sign-in, and boot screens),
                      failedNotice.ts (carries the
                      failed-sign-ins count from the sign-in page to the app)
  dashboard/          the customisable dashboard: registry.tsx (every widget
                      type, its catalogue entry, default size and options),
                      widgets/ (one file per group, including showcase.tsx:
                      piece of the day, oldest/newest, on this day, the
                      photo mosaic, and most valuable), WidgetFrame.tsx (the
                      card, lazy mount, per-widget error), data.ts (the
                      per-page request cache), options.ts, edit.tsx (edit
                      mode, the drag, the catalogue and options dialogs)
  pages/              one file per route: Dashboard, ItemList (/collection),
                      ItemDetail, ItemForm, AddRun, Checklists, Pricing,
                      Stack, Report, Import, Trash, Settings, Setup, Login
    item-form/          the item form's parts: model.ts (form state,
                        toPayload, fromItem, the designation and problem
                        lists), NumistaFill.tsx, PcgsFill.tsx
    settings/           Settings, routed into sections (v0.30.2): shared.tsx
                        (the section list, Section, SettingRow, the
                        useSettings load/apply hook), and one file per
                        section (General.tsx, Pricing.tsx, Backups.tsx,
                        Alerts.tsx, Account.tsx, About.tsx); Alerts.tsx and
                        Account.tsx are thin wrappers around
                        components/alerts.tsx and components/account.tsx,
                        which already render their own single-h2 card
  components/         shared pieces
    item-hero.tsx       the item page's top: photo, title, grade, value
    item-facts.tsx      the rest of an item's fields, grouped, empty ones
                        hidden behind a "Show empty fields" toggle
    icons.tsx           inline SVG icons
    controls.tsx        FileButton (a file picker that looks like a button)
                        and Menu
    theme.ts            initialTheme / applyTheme
    charts.tsx          hand-rolled SVG bar and line charts
    photo-gallery.tsx, photos.tsx
                        the item page's gallery; lightbox, crop/turn/
                        straighten editor, webcam capture
    value-history.tsx, provenance.tsx, sales.tsx
                        estimates and their provenance (also timeSince,
                        sourceKey, latestBySource); the sales log
    documents.tsx, duplicates.tsx, lookup.tsx
                        attached documents; the duplicate warning; outbound
                        lookup links (eBay sold, Photograde, CoinFacts, and
                        a web search for a note's Friedberg or Pick number)
    serial-traits.tsx   fancy-serial badges (TraitBadges) and
                        useSerialTraits, which fetches the trait labels
                        once per session
    alerts.tsx, setup.tsx
                        Settings → Alerts & metrics; the dashboard's setup
                        checklist (setup.tsx's setupChecks also flags an
                        unsaved backup key)
    account.tsx         Settings → Account: password, username, sessions,
                        API tokens, the audit log
    restore.tsx         Settings → Backups → Restore: useRestore (inspect,
                        confirm, run, poll the status every 2 s through the
                        503s) and RestoreBlock; hidden when the deployment
                        switches restore off
e2e/                  Playwright tests: auth.spec.ts (sign-in, sign-out, the
                       confirm dialog, the Account section, none of it
                       touching the shared session) and smoke.spec.ts (the
                       rest, its last two tests changing and reverting the
                       admin's password and username); the sign-in global
                       setup (global-setup.ts)
playwright.config.ts, vite.config.ts, tsconfig.json
```

Routes: `/` is the dashboard, `/collection` the list (its filters, sort, and
page live in the URL), `/items/new`, `/items/run`, `/items/:id`,
`/items/:id/edit`, `/pricing`, `/stack`, `/report`, `/checklists`, `/import`,
`/trash`, and `/settings/:section` (`general`, `pricing`, `backups`,
`alerts`, `account`, `about`; `/settings` redirects to `/settings/general`,
and an unknown section falls back to it too). `/dashboard` redirects to `/`.
`/setup` and
`/login` render outside the app shell (brand only, no nav); everything else
is gated on being signed in, see "Sign-in" below.

## Sign-in (v0.30.0)

The backend denies every route by default (`docs/specs/SPEC_0300.md`); the
frontend's job is to make that unsurprising rather than working around it.

- **Boot order** (`auth/AuthContext.tsx`'s `AuthProvider`, used by `App.tsx`'s
  `Gate`): `GET /api/auth/state`, then `GET /api/auth/me`.
  `setup_required` renders `/setup` for every path; a `503` (a restore is
  running) shows a plain message and retries every 5 seconds; a `401` from
  `/me` renders `/login` for every path, with `?next=` carrying the page that
  was asked for (only a same-app relative path is honoured, checked in
  `pages/Login.tsx`'s `safeNext`, never an absolute URL); otherwise the app
  renders as before, with the header showing the signed-in username and a
  Sign out button. `/setup` and `/login` are the only routes rendered without
  the header; a remembered light theme still applies to them (`App.tsx`'s
  `Gate`, not `AuthedApp`, owns the theme effect, precisely so it isn't
  header-only).
- **`api/client.ts`'s `req()`** reacts to two statuses everywhere except the
  auth boot check and the setup/sign-in calls themselves (which pass
  `{ raw: true }` and handle 401/403 as ordinary form answers): a `401`
  calls a handler `AuthProvider` registers once, which does a full page load
  to `/login?next=...` (so every in-memory cache goes with it, the same as
  signing out); a `403` with `{"reauth_required": true}` calls a handler the
  confirm dialog registers, awaits it, and **retries the original request
  once**. Errors are `ApiError`, carrying `status` and `retryAfter` (from the
  `Retry-After` header) for the sign-in/setup pages' countdown text.
- **The confirm-password dialog** (`auth/ConfirmDialog.tsx`) is a promise-
  based service (`requestConfirm()`) plus one component
  (`<ConfirmDialogHost/>`, mounted once, inside the signed-in app only) that
  answers it: `POST /api/auth/confirm`, a wrong password shown inline
  without closing, Cancel rejects the promise with a clear message. Both
  `req()`'s automatic retry and `auth/FreshLink.tsx` (below) open it through
  the same `requestConfirm()`, so there is only ever one dialog.
- **`auth/FreshLink.tsx`** wraps a plain download link (the two exports, a
  backup, a stored archive) that reaches a "fresh" route: before navigating,
  it checks `GET /api/auth/me`'s `confirmed_until` (a 30-second margin) and
  opens the confirm dialog first only if that window has lapsed, then clicks
  a real anchor so the browser's own download handling still applies. Plain
  links can't be retried the way `req()` retries a JSON call, hence the
  separate helper.
- **New files**: `api/types/auth.ts` (`Me`, `LoginResult`, `AuthSession`,
  `ApiToken`, `NewApiToken`, `AuditEntry`, …), `auth/AuthContext.tsx`,
  `auth/ConfirmDialog.tsx`, `auth/FreshLink.tsx`, `auth/failedNotice.ts`,
  `pages/Setup.tsx`, `pages/Login.tsx`, `components/account.tsx`.
- **The failed-sign-ins notice**: `pages/Login.tsx` writes
  `{count, since}` to `sessionStorage` (`auth/failedNotice.ts`) when a
  successful sign-in's `failed_since_previous > 0`; `App.tsx`'s
  `FailedSignInsNotice` reads and clears it once, right after the
  navigation that follows sign-in, and is dismissible.

## Styling conventions

- **Design tokens.** Colours and the typeface are CSS variables on `:root`
  at the top of `styles.css`, with the dark values under
  `:root[data-theme="dark"]`. Use a token, never a literal colour, so both
  themes keep working. The accent is bronze (`--accent`) on warm surfaces;
  charts take `--series`, `--chart-grid`, `--chart-axis`, and
  `--chart-muted`.
- **One system typeface.** `--font` is a Calibri-first system stack
  (Calibri, Carlito, Segoe UI, system-ui, and so on) with
  `font-size-adjust`. No fonts are downloaded: nginx's
  Content-Security-Policy allows nothing from outside the app.
- **Dark by default.** `index.html` sets `data-theme="dark"` so there is no
  light flash, `components/theme.ts` applies the theme, and the header
  toggle switches to light and remembers the choice in `localStorage`
  (`theme`). The operating system's preference is not consulted.
- **No sideways shift.** `html` has `scrollbar-gutter: stable` (with
  `overflow-y: scroll` where that isn't supported), so the header stays put
  between a short page and one that scrolls.
- **Icons are inline SVG** from `components/icons.tsx`, never emoji (emoji
  differ by system) and never an icon font. They take the text colour and
  size of what they sit in. Add new ones there.
- **Money goes through `money(value, currency)`** from `../api`: it formats
  with `Intl.NumberFormat` in currency style (the browser's locale,
  formatters cached per code) and falls back to `12.50 XYZ` for a code the
  browser rejects. Don't format amounts by hand.
- **The dashboard is a six-column grid.** A widget spans 6, 3, or 2 columns
  (full, half, a third); a third becomes a half under 900px and everything is
  full width under 720px. `grid-auto-flow` stays `row`, never `dense`, so the
  drawn order is the saved order. The layout itself lives on the server
  (`/api/dashboard/layout`), not in the browser.
- **The CSP is strict.** New inline scripts, external scripts or fonts, or
  iframes will trip it. The e2e header test visits the main pages and fails
  on any policy violation.
- **Writing.** No em dashes in interface text or comments; an empty value in
  a table or field shows an en dash.

## End-to-end tests

`e2e/smoke.spec.ts` drives the real pages in Chromium: the dashboard, adding
an item, recording a value, rearranging the dashboard and resetting it, the
duplicate warning, a generated checklist
filling itself, search, trash and restore, a note with a radar serial
number getting its badge and its size and printer showing on the item page,
a wishlist coin showing its target price, an
undated piece taking ND with no year, a silver piece showing its fine ounces
on the Stack page, the
security headers, every Settings section, an in-app restore of a backup
taken a moment earlier, and, last of all, changing the admin's password and
username and putting each back (see "Sign-in tests" below for why those two
are last). The tests run against a running stack (`docker compose up`), not
the dev server, and they create and delete their own items; the stack test
asserts on ounces and cost only, never on a live spot price.

`e2e/auth.spec.ts` drives the sign-in side on its own: the sign-in page and
`?next=`, a wrong password then the right one and the failed-attempts
notice, signing out (and that going back afterwards doesn't show cached
collection data), a signed-out photo request (`401`), the confirm-password
dialog appearing once for a fresh download and not again inside its window
(covering the CSV export and `backup.zip` while signed in too), creating and
revoking an API token, and ending another session (a second browser context
it signs in itself, distinguished by a custom `User-Agent`). The setup page
itself isn't covered here: CI's curl claim already exercises it, and by the
time Playwright runs the instance is claimed.

Cabinet needs a sign-in (v0.30.0). `global-setup.ts` runs once before the
whole suite, claims an unclaimed stack with `SETUP_CODE` or signs in with
`CABINET_USER`/`CABINET_PASSWORD` (default `owner` / `correct horse
battery`), and saves the session as `playwright.config.ts`'s
`use.storageState`, so every spec's page starts signed in. A spec that
reaches a "fresh" route (the recent-password window,
`docs/specs/SPEC_0300.md` section 5) now goes through the app's own
confirm-password dialog instead of confirming out of band; most specs do
this through a small helper (`withPasswordConfirm` in `smoke.spec.ts`) that
performs the action and answers the dialog only if it appears (it doesn't,
within the window an earlier action already opened).

**`playwright.config.ts` sets `workers: 1`.** Every spec shares one backend
and one database, and two things in the suite aren't safe to run
concurrently with anything else: `smoke.spec.ts`'s restore test replaces the
whole database mid-suite, and its last two tests change the admin's password
and username for a moment. One worker also makes file order deterministic
(alphabetical), which is how `auth.spec.ts` (touches no shared session)
finishes before `smoke.spec.ts`'s account tests, themselves last in that
file, ever start. Those two tests sign themselves in through the form rather
than trusting `storageState`: the first one's own password change revokes
every *other* session, including the one baked into
`e2e/.auth/storage-state.json` that every other fresh page fixture (the
second test included) would otherwise start from.

```bash
export SETUP_CODE=...                  # only if the stack isn't claimed yet
npm run e2e                            # http://localhost, through the proxy
BASE_URL=http://proxy npm run e2e      # another host
```

The first run needs `npx playwright install chromium`. CI runs them in the
compose stack job after the API smoke test and the backup and restore
drills; a failed run
keeps its report as a workflow artifact. When a page's behaviour or wording
changes, update the spec in the same commit: pytest won't catch it.
