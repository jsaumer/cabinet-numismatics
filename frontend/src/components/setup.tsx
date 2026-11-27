import { ReactNode, useState } from "react";
import { Link } from "react-router-dom";

import { AppSettings, BackupList, Health } from "../api";
import { EXPOSURE_GUIDANCE_URL } from "../auth/exposureWarning";

export interface SetupCheck {
  key: string;
  text: ReactNode;
  /** Something is broken, not merely still switched off: shown in red. */
  failure?: boolean;
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

/** What's broken, then what's still switched off on a fresh install. The
 * caller supplies the three requests it reads, so the dashboard fetches each
 * of them once. An empty collection isn't on the list: the welcome state
 * (components/welcome.tsx) says that. */
export function setupChecks(
  settings: AppSettings,
  backups: BackupList | null,
  health: Health | null,
): SetupCheck[] {
  const list: SetupCheck[] = [];
  if (health && health.schema.status !== "ok") {
    list.push({
      key: "schema",
      failure: true,
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
      failure: true,
      text: (
        <>
          Document storage isn't a mounted volume, so uploads are refused. Bind{" "}
          <code>/data/documents</code> (docs/deployment.md §2).
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
      failure: true,
      text: (
        <>
          The last backup failed: {backups.last_run.error} (<Link to="/settings/backups">Settings</Link>).
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
          catalog (<Link to="/settings/pricing">Settings → Price sources</Link>).
        </>
      ),
    });
  }
  list.push({
    key: "exposure",
    text: (
      <>
        <a href={EXPOSURE_GUIDANCE_URL} target="_blank" rel="noreferrer">
          Read the exposure guidance
        </a>
        : Cabinet is for private networks.
      </>
    ),
  });
  // What's broken first; the rest keeps its order.
  return [...list.filter((c) => c.failure), ...list.filter((c) => !c.failure)];
}

/** The checks as a list under their heading, with the way to hide the ones
 * that are only switched off. The card around it is the dashboard widget's. */
export function SetupList({
  checks,
  onDismiss,
}: {
  checks: SetupCheck[];
  onDismiss?: () => void;
}) {
  return (
    <>
      <h2>Before you rely on it</h2>
      <ul>
        {checks.map((c) => (
          <li key={c.key} className={c.failure ? "setup-failure" : undefined}>
            {c.text}
          </li>
        ))}
      </ul>
      {onDismiss && (
        <button type="button" className="link-button" onClick={onDismiss}>
          Don't show this again
        </button>
      )}
    </>
  );
}
