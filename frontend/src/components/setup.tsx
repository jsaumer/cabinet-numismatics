import { ReactNode, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../api";

interface Check {
  key: string;
  text: ReactNode;
}

const DISMISS_KEY = "cabinet.setup.dismissed";

function readDismissed(): boolean {
  try {
    return window.localStorage.getItem(DISMISS_KEY) === "1";
  } catch {
    return false;
  }
}

/** What's still switched off on a fresh install — shown on the dashboard
 * until it's all done, or until it's dismissed for good (per browser). */
export function SetupChecklist({ itemCount }: { itemCount: number }) {
  const [checks, setChecks] = useState<Check[] | null>(null);
  const [dismissed, setDismissed] = useState<boolean>(readDismissed);

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

  if (dismissed || !checks || checks.length === 0) return null;

  function hide() {
    try {
      window.localStorage.setItem(DISMISS_KEY, "1");
    } catch {
      /* private mode: hides for this page view only */
    }
    setDismissed(true);
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
        Don't show this again
      </button>
    </div>
  );
}
