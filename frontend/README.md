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
  main.tsx, App.tsx   entry; the header, navigation, theme toggle, and routes
  styles.css          the one stylesheet, design tokens first
  api/                the API client; import everything from "../api"
    types/              response and payload types by area (items, settings,
                        stats, imports); settings.ts also holds the backup
                        and restore types (BackupFile, RestoreStatus,
                        RestoreInspection, RestoreOutcome)
    client.ts           the fetch wrapper and error handling
    calls.ts            one function per endpoint, exported as `api`
    index.ts            re-exports it all, plus helpers such as money()
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
                      Stack, Report, Import, Trash, Settings
    item-form/          the item form's parts: model.ts (form state,
                        toPayload, fromItem, the designation and problem
                        lists), NumistaFill.tsx, PcgsFill.tsx
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
                        checklist
    restore.tsx         Settings → Backups → Restore: useRestore (inspect,
                        confirm, run, poll the status every 2 s through the
                        503s) and RestoreBlock; hidden when the deployment
                        switches restore off
e2e/                  Playwright smoke tests (smoke.spec.ts)
playwright.config.ts, vite.config.ts, tsconfig.json
```

Routes: `/` is the dashboard, `/collection` the list (its filters, sort, and
page live in the URL), `/items/new`, `/items/run`, `/items/:id`,
`/items/:id/edit`, `/pricing`, `/stack`, `/report`, `/checklists`, `/import`,
`/trash`, and `/settings`. `/dashboard` redirects to `/`.

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
security headers, every Settings section, and, last, an in-app restore of a
backup taken a moment earlier (last so a failure can't disturb the others;
it leaves the collection as it found it, plus a safety backup). The tests
run against a running stack (`docker compose up`), not the dev server, and
they create and delete their own items; the stack test asserts on ounces
and cost only, never on a live spot price.

```bash
npm run e2e                            # http://localhost, through the proxy
BASE_URL=http://proxy npm run e2e      # another host
```

The first run needs `npx playwright install chromium`. CI runs them in the
compose stack job after the API smoke test and the backup and restore
drills; a failed run
keeps its report as a workflow artifact. When a page's behaviour or wording
changes, update the spec in the same commit: pytest won't catch it.
