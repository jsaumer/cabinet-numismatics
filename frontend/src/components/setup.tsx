import { ReactNode, useState } from "react";
import { Link } from "react-router-dom";

import { AppSettings, BackupList, Health } from "../api";

export interface SetupCheck {
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

/** Dismissed for good in this browser, and the way to dismiss it. */
export function useSetupDismissed(): { dismissed: boolean; dismiss: () => void } {
  const [dismissed, setDismissed] = useState<boolean>(readDismissed);
  return {
    dismissed,
    dismiss: () => {
      try {
        window.localStorage.setItem(DISMISS_KEY, "1");
      } catch {
        /* private mode: hides for this page view only */
      }
      setDismissed(true);
    },
  };
}

/** What's still switched off on a fresh install. The caller supplies the
 * three requests it reads, so the dashboard fetches each of them once. */
export function setupChecks(
  itemCount: number,
  settings: AppSettings,
  backups: BackupList | null,
  health: Health | null,
): SetupCheck[] {
  const list: SetupCheck[] = [];
  if (health && health.schema.status !== "ok") {
    list.push({
      key: "schema",
      text: (
        <>
          The database schema is <b>{health.schema.status}</b>. See Settings → About.
        </>
      ),
    });
  }
  if (health && health.documents !== "ok") {
    list.push({
      key: "documents",
      text: (
        <>
          Document storage isn't a mounted volume, so uploads are refused. Bind{" "}
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
          Scheduled backups are off. <Link to="/settings/backups">Turn them on</Link>, and point{" "}
          <code>/data/backups</code> somewhere off this host.
        </>
      ),
    });
  } else if (backups && !backups.last_run) {
    list.push({
      key: "backup_never",
      text: (
        <>
          No backup has run yet. <Link to="/settings/backups">Back up now</Link> proves the directory is
          writable.
        </>
      ),
    });
  }
  if (backups?.last_run && !backups.last_run.ok) {
    list.push({
      key: "backup_failed",
      text: (
        <>
          The last backup failed: {backups.last_run.error} (<Link to="/settings/backups">Settings</Link>).
        </>
      ),
    });
  }
  if (backups && !backups.key.saved && !backups.key.supplied) {
    list.push({
      key: "backup_key",
      text: (
        <>
          Every backup is encrypted, and the key has no recovery. Save it from{" "}
          <Link to="/settings/backups">Settings → Backups</Link>.
        </>
      ),
    });
  }
  if (!settings.alert_webhook_hint && !settings.heartbeat_hint) {
    list.push({
      key: "alerts",
      text: (
        <>
          Failures only reach the log. Add an alert webhook or an Uptime Kuma heartbeat in{" "}
          <Link to="/settings/alerts">Settings</Link>.
        </>
      ),
    });
  }
  if (!settings.sources.some((s) => (s.key === "numista" || s.key === "pcgs") && s.configured)) {
    list.push({
      key: "source_key",
      text: (
        <>
          No price-source key. A free Numista API key prices items and fills them in from the
          catalogue (<Link to="/settings/pricing">Settings → Price sources</Link>).
        </>
      ),
    });
  }
  if (itemCount === 0) {
    list.push({
      key: "empty",
      text: (
        <>
          The collection is empty. <Link to="/items/new">Add an item</Link>, or{" "}
          <Link to="/import">import</Link> from Numista, OpenNumismat, or a spreadsheet.
        </>
      ),
    });
  }
  return list;
}

/** The checks as a list, with the way to hide them for good. The card around
 * it is the dashboard widget's. */
export function SetupList({
  checks,
  onDismiss,
}: {
  checks: SetupCheck[];
  onDismiss: () => void;
}) {
  return (
    <>
      <ul>
        {checks.map((c) => (
          <li key={c.key}>{c.text}</li>
        ))}
      </ul>
      <button type="button" className="link-button" onClick={onDismiss}>
        Don't show this again
      </button>
    </>
  );
}
