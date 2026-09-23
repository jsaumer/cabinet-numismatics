import { ReactNode, useEffect, useRef, useState } from "react";

import { api, AppSettings, AppSettingsUpdate } from "../../api";

// Shared pieces for the routed Settings sections: the section list the shell
// and the nav both read, a Section/SettingRow pair for a consistent layout,
// a quiet "Saved" tick for a control that applies on change, and the hook
// that loads settings and applies a change against PUT /api/settings.

export interface SettingsSection {
  key: string;
  path: string;
  label: string;
}

// The six routed sections, in nav order. A path under /settings/ that isn't
// one of these falls back to "general" (see pages/Settings.tsx).
export const SETTINGS_SECTIONS: SettingsSection[] = [
  { key: "general", path: "/settings/general", label: "General" },
  { key: "pricing", path: "/settings/pricing", label: "Pricing" },
  { key: "backups", path: "/settings/backups", label: "Backups" },
  { key: "alerts", path: "/settings/alerts", label: "Alerts & metrics" },
  { key: "account", path: "/settings/account", label: "Account" },
  { key: "about", path: "/settings/about", label: "About" },
];

/** One settings section: an h2 title, an optional one-line description, and
 * its content, all inside the usual .card. */
export function Section({
  title,
  description,
  children,
}: {
  title: string;
  description?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="card">
      <h2>{title}</h2>
      {description && (
        <p className="muted" style={{ marginTop: 0 }}>
          {description}
        </p>
      )}
      {children}
    </div>
  );
}

/** A single setting: label and help text on the left, the control on the
 * right. Stacks vertically under 700px (see .setting-row in styles.css). */
export function SettingRow({
  label,
  help,
  htmlFor,
  children,
}: {
  label: ReactNode;
  help?: ReactNode;
  htmlFor?: string; // the control's id, so the label focuses it
  children: ReactNode;
}) {
  return (
    <div className="setting-row">
      <div className="setting-row-text">
        {htmlFor ? (
          <label className="setting-row-label" htmlFor={htmlFor}>
            {label}
          </label>
        ) : (
          <div className="setting-row-label">{label}</div>
        )}
        {help && <p className="muted setting-row-help">{help}</p>}
      </div>
      <div className="setting-row-control">{children}</div>
    </div>
  );
}

/** A quiet confirmation next to a control that applies as soon as it
 * changes, shown for a couple of seconds instead of a page-level note. */
export function SavedTick({ shown }: { shown: boolean }) {
  if (!shown) return null;
  return (
    <span className="saved-tick" role="status">
      Saved
    </span>
  );
}

/** Triggers a SavedTick for about two seconds. */
export function useSavedTick(): [boolean, () => void] {
  const [shown, setShown] = useState(false);
  const timer = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(timer.current), []);
  function trigger() {
    setShown(true);
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setShown(false), 2000);
  }
  return [shown, trigger];
}

/** Loads the settings once and applies a change through PUT /api/settings,
 * used by every section that reads or writes them. Each section mounts its
 * own copy (they're separate routes now), so each fetches independently. */
export function useSettings() {
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  function reload() {
    api
      .getSettings()
      .then((s) => {
        setError(null);
        setSettings(s);
      })
      .catch((e: Error) => setError(e.message));
  }

  useEffect(reload, []);

  async function apply(payload: AppSettingsUpdate, message: string | null): Promise<boolean> {
    setSaving(true);
    setError(null);
    if (message !== null) setNote(null);
    try {
      const updated = await api.updateSettings(payload);
      setSettings(updated);
      if (message !== null) setNote(message);
      return true;
    } catch (e) {
      setError((e as Error).message);
      return false;
    } finally {
      setSaving(false);
    }
  }

  return { settings, setSettings, error, note, saving, apply, reload };
}
