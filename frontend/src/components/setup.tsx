import { ReactNode, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../api";

interface Check {
  key: string;
  text: ReactNode;
}

const DISMISS_KEY = "cabinet.setup.dismissed";
const DISMISS_DAYS = 30;

interface Dismissal {
  until: string;
  keys: string[];
}

function readDismissal(): Dismissal | null {
  try {
    const raw = window.localStorage.getItem(DISMISS_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Dismissal;
    return new Date(parsed.until).getTime() > Date.now() ? parsed : null;
  } catch {
    return null;
  }
}

/** What's still switched off on a fresh install — shown on the dashboard
 * until it's done or hidden. A new problem brings it back. */
export function SetupChecklist({ itemCount }: { itemCount: number }) {
  const [checks, setChecks] = useState<Check[] | null>(null);
  const [dismissed, setDismissed] = useState<Dismissal | null>(readDismissal);

  useEffect(() => {
    Promise.all([
      api.getSettings(),
      api.listBackups().catch(() => null),
      api.health().catch(() => null),
    ])
      .then(([settings, backups, health]) => {
        const list: Check[] = [];
        if (health && health.schema.status !== "ok") {
          list.push({
            key: "schema",
            text: (
              <>
                The database schema is <b>{health.schema.status}</b> — see Settings → About.
              </>
            ),
          });
        }
        if (health && health.documents !== "ok") {
          list.push({
            key: "documents",
            text: (
              <>
                Document storage isn't a mounted volume, so uploads are refused — bind{" "}
                <code>/data/documents</code> (docs/deployment.md §2).
              </>
            ),
          });
        }
        if (!settings.backup_schedule) {
          list.push({
            key: "backup_schedule",
            text: (
              <>
                Scheduled backups are off — <Link to="/settings">turn them on</Link>, and point{" "}
                <code>/data/backups</code> somewhere off this host.
              </>
            ),
          });
        } else if (backups && !backups.last_run) {
          list.push({
            key: "backup_never",
            text: (
              <>
                No backup has run yet — <Link to="/settings">Back up now</Link> proves the
                directory is writable.
              </>
            ),
          });
        }
        if (backups?.last_run && !backups.last_run.ok) {
          list.push({
            key: "backup_failed",
            text: (
              <>
                The last backup failed: {backups.last_run.error} (<Link to="/settings">Settings</Link>).
              </>
            ),
          });
        }
        if (!settings.alert_webhook_hint && !settings.heartbeat_hint) {
          list.push({
            key: "alerts",
            text: (
              <>
                Failures only reach the log — add an alert webhook or an Uptime Kuma heartbeat in{" "}
                <Link to="/settings">Settings</Link>.
              </>
            ),
          });
        }
        if (!settings.sources.some((s) => (s.key === "numista" || s.key === "pcgs") && s.configured)) {
          list.push({
            key: "source_key",
            text: (
              <>
                No price-source key — a free Numista API key prices items and fills them in from
                the catalogue (<Link to="/settings">Settings → Price sources</Link>).
              </>
            ),
          });
        }
        if (itemCount === 0) {
          list.push({
            key: "empty",
            text: (
              <>
                The collection is empty — <Link to="/items/new">add an item</Link>, or{" "}
                <Link to="/import">import</Link> from Numista, OpenNumismat, or a spreadsheet.
              </>
            ),
          });
        }
        setChecks(list);
      })
      .catch(() => setChecks([]));
  }, [itemCount]);

  if (!checks || checks.length === 0) return null;
  // Hidden only while every current problem was already known when it was hidden.
  if (dismissed && checks.every((c) => dismissed.keys.includes(c.key))) return null;

  function hide() {
    const until = new Date(Date.now() + DISMISS_DAYS * 86_400_000).toISOString();
    const next = { until, keys: checks!.map((c) => c.key) };
    try {
      window.localStorage.setItem(DISMISS_KEY, JSON.stringify(next));
    } catch {
      /* private mode: hides for this page view only */
    }
    setDismissed(next);
  }

  return (
    <div className="card setup-card">
      <h2>Getting set up</h2>
      <ul>
        {checks.map((c) => (
          <li key={c.key}>{c.text}</li>
        ))}
      </ul>
      <button type="button" className="link-button" onClick={hide}>
        Hide for {DISMISS_DAYS} days
      </button>
    </div>
  );
}
