import { useEffect, useState } from "react";

import {
  api,
  AppSettings,
  AppSettingsUpdate,
  BackupList,
  Health,
  SourceStatus,
  ValueStrategy,
} from "../api";
import { AlertsCard } from "../components/alerts";
import { LockIcon } from "../components/icons";
import { RestoreBlock, useRestore } from "../components/restore";

function formatBytes(bytes: number): string {
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit++;
  }
  return `${value.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`;
}

function schemaLabel({ current, expected, status }: Health["schema"]): string {
  if (status === "ok") return `${current} (up to date)`;
  if (status === "pending") return `${current ?? "empty"} (migration pending, expects ${expected})`;
  if (status === "ahead") return `${current} (newer than this build, which expects ${expected})`;
  return "unknown (database unreachable)";
}

// Sources with nothing to configure beyond on/off.
const KEYLESS = new Set(["melt", "comps"]);

const DOCUMENT_STORAGE: Record<string, string> = {
  ok: "ready",
  not_mounted:
    "not a mounted volume, so uploads are refused and documents can't be lost with the container " +
    "(see docs/deployment.md)",
  unwritable: "not writable, so uploads are refused",
  inside_photos: "inside the public photo folder, so uploads are refused",
};

export default function Settings() {
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [currency, setCurrency] = useState("");
  const [cadence, setCadence] = useState("");
  const [valueStrategy, setValueStrategy] = useState<ValueStrategy>("latest");
  const [preferredSource, setPreferredSource] = useState("");
  const [keys, setKeys] = useState<Record<string, string>>({});
  const [health, setHealth] = useState<Health | null>(null);
  const [keep, setKeep] = useState("");
  const [backups, setBackups] = useState<BackupList | null>(null);
  const [backupError, setBackupError] = useState<string | null>(null);
  const [backupNote, setBackupNote] = useState<string | null>(null);
  const [backingUp, setBackingUp] = useState(false);

  function loadBackups() {
    api
      .listBackups()
      .then(setBackups)
      .catch((e: Error) => setBackupError(e.message));
  }

  function loadAbout() {
    api.health().then(setHealth).catch(() => setHealth(null));
    loadBackups();
  }

  useEffect(loadAbout, []);

  async function backUpNow() {
    setBackingUp(true);
    setBackupError(null);
    setBackupNote(null);
    try {
      const run = await api.runBackup();
      const pruned = run.pruned?.length ? ` Removed ${run.pruned.length} older.` : "";
      setBackupNote(`Backup written: ${run.file} (${formatBytes(run.size ?? 0)}).${pruned}`);
    } catch (e) {
      setBackupError((e as Error).message);
    } finally {
      setBackingUp(false);
      loadBackups();
    }
  }

  function loadSettings() {
    api
      .getSettings()
      .then((s) => {
        setError(null);
        setSettings(s);
        setCurrency(s.display_currency);
        setCadence(String(s.reestimate_days));
        setValueStrategy(s.value_strategy);
        setPreferredSource(s.preferred_source ?? "");
        setKeep(String(s.backup_keep));
      })
      .catch((e: Error) => setError(e.message));
  }

  useEffect(loadSettings, []);

  // A restore replaced the database: everything on this page is stale.
  const restore = useRestore(() => {
    setBackupError(null);
    setBackupNote(null);
    loadSettings();
    loadAbout();
  });

  async function apply(payload: AppSettingsUpdate, message: string): Promise<boolean> {
    setSaving(true);
    setError(null);
    setNote(null);
    try {
      const updated = await api.updateSettings(payload);
      setSettings(updated);
      setCurrency(updated.display_currency);
      setCadence(String(updated.reestimate_days));
      setValueStrategy(updated.value_strategy);
      setPreferredSource(updated.preferred_source ?? "");
      setKeep(String(updated.backup_keep));
      setNote(message);
      return true;
    } catch (e) {
      setError((e as Error).message);
      return false;
    } finally {
      setSaving(false);
    }
  }

  // Opened mid-restore: the settings call got a 503, the status call didn't.
  if (!settings && restore.running) {
    return (
      <div className="card">
        <h2>Backups</h2>
        <RestoreBlock restore={restore} />
      </div>
    );
  }
  if (error && !settings) return <p className="error">{error}</p>;
  if (!settings) return <p className="muted">Loading…</p>;

  const sourceCard = (source: SourceStatus) => {
    const keyless = KEYLESS.has(source.key);
    const keyField = source.key === "numista" ? "numista_api_key" : "pcgs_api_token";
    const enabledField = `${source.key}_enabled` as
      | "melt_enabled"
      | "numista_enabled"
      | "pcgs_enabled"
      | "comps_enabled";
    return (
      <div className="source-row" key={source.key}>
        <div className="source-head">
          <label className="slot">
            <input
              type="checkbox"
              checked={source.enabled}
              disabled={saving || (!keyless && !source.configured)}
              onChange={(e) =>
                apply(
                  { [enabledField]: e.target.checked },
                  `${source.name} ${e.target.checked ? "enabled" : "disabled"}.`,
                )
              }
            />
            <b>{source.name}</b>
          </label>
          {!source.available && <span className="badge status-wishlist">adapter pending</span>}
        </div>
        {source.note && <p className="muted" style={{ margin: "0.2rem 0 0.4rem" }}>{source.note}</p>}
        {!keyless && (
          <div className="estimate-form" style={{ marginTop: 0 }}>
            <label className="field">
              {source.key === "numista" ? "API key" : "API token"}
              {source.configured
                ? ` (saved ${source.secret_hint ?? ""})`
                : " (not configured)"}
              <input
                type="password"
                autoComplete="off"
                placeholder={source.configured ? "replace…" : "paste key…"}
                value={keys[keyField] ?? ""}
                onChange={(e) => setKeys((k) => ({ ...k, [keyField]: e.target.value }))}
              />
            </label>
            <button
              disabled={saving || !(keys[keyField] ?? "").trim()}
              onClick={() => {
                apply({ [keyField]: keys[keyField].trim() }, "Key saved.");
                setKeys((k) => ({ ...k, [keyField]: "" }));
              }}
            >
              Save key
            </button>
            {source.configured && (
              <button
                disabled={saving}
                onClick={() => apply({ [keyField]: "" }, "Key removed.")}
              >
                Remove key
              </button>
            )}
          </div>
        )}
        {source.key === "numista" && (
          <div className="estimate-form" style={{ marginTop: "0.4rem" }}>
            <label className="field">
              Scheduled refresh
              <select
                value={settings.numista_refresh_days ?? ""}
                disabled={saving}
                onChange={(e) => {
                  const days = e.target.value ? Number(e.target.value) : null;
                  apply(
                    { numista_refresh_days: days },
                    days
                      ? `Numista scheduled refresh set to every ${days} days.`
                      : "Numista scheduled refresh turned off.",
                  );
                }}
              >
                <option value="">Off</option>
                <option value="7">Every 7 days</option>
                <option value="14">Every 14 days</option>
                <option value="30">Every 30 days</option>
              </select>
            </label>
            {settings.numista_refresh_days &&
              (() => {
                const monthlyCalls = Math.ceil(
                  settings.numista_priceable_items * 2 * (30 / settings.numista_refresh_days!),
                );
                const overBudget = monthlyCalls > 2000;
                return (
                  <p className={overBudget ? "error" : "muted"} style={{ margin: 0 }}>
                    ~{monthlyCalls} Numista calls/month at this cadence across{" "}
                    {settings.numista_priceable_items} priceable item(s): 2 calls per estimate,
                    free-tier cap is 2,000/month.
                    {overBudget && " This exceeds the free tier; expect 429s before the month is out."}
                  </p>
                );
              })()}
          </div>
        )}
        {source.key === "numista" && (
          <div className="paid-option">
            <label className="slot">
              <input
                type="checkbox"
                checked={settings.numista_sales_enabled}
                disabled={saving || !source.configured}
                onChange={(e) =>
                  apply(
                    { numista_sales_enabled: e.target.checked },
                    `Numista auction sales ${e.target.checked ? "enabled" : "disabled"}.`,
                  )
                }
              />
              <b>Numista auction sales</b>
              <span className="badge status-wishlist">paid Numista API plan</span>
            </label>
            <p className="muted" style={{ margin: "0.3rem 0 0" }}>
              Adds a <i>Fetch Numista auction sales</i> button to each item's sales log, which
              copies the auction results Numista has recorded for that year and mint (house,
              date, lot link, grade, price) into the log for the comps estimate.{" "}
              <b>This needs Numista's paid API plan</b>: at the time of writing a one-time
              €100 activation fee, then at least €100 a month (€0.01 a request, before VAT). A
              free key gets <code>Permission denied</code>, and the button says so. Leave this
              off unless you have that plan.
            </p>
            <p className="muted" style={{ margin: "0.3rem 0 0" }}>
              Each fetch is one request, made only when you click, never on the refresh
              schedule, and repeating it the same day is free (cached for a day).
            </p>
          </div>
        )}
        {source.key === "pcgs" && (
          <div className="estimate-form" style={{ marginTop: "0.4rem" }}>
            <label className="slot">
              <input
                type="checkbox"
                checked={settings.pcgs_auto_refresh}
                disabled={saving}
                onChange={(e) =>
                  apply(
                    { pcgs_auto_refresh: e.target.checked },
                    `PCGS auto-refresh ${e.target.checked ? "enabled" : "disabled"} (weekly).`,
                  )
                }
              />
              Auto-refresh weekly
            </label>
                        <p className={settings.pcgs_priceable_items > 100 ? "error" : "muted"}
              style={{ margin: 0 }}>
              {settings.pcgs_priceable_items} priceable item(s), one call each. PCGS allows 100
              calls a day by default
              {settings.pcgs_priceable_items > 100
                ? ", so a refresh stops at the limit and raises the quota alert. PCGS raises " +
                  "the limit on request (apis@pcgs.com)."
                : "."}
            </p>
          </div>
        )}
      </div>
    );
  };

  return (
    <>
      <div className="detail-header">
        <h1>Settings</h1>
      </div>
      {error && <p className="error">{error}</p>}
      {note && <p className="muted">{note}</p>}

      <div className="card">
        <h2>General</h2>
        <div className="estimate-form" style={{ marginTop: 0 }}>
          <label className="field">
            Display currency (totals, dashboard, report)
            <input value={currency} maxLength={3} style={{ width: "5rem" }}
              onChange={(e) => setCurrency(e.target.value)} />
          </label>
          <label className="field">
            Melt refresh cadence (days; 0 disables)
            <input type="number" min={0} max={365} value={cadence} style={{ width: "6rem" }}
              onChange={(e) => setCadence(e.target.value)} />
          </label>
          <label className="field">
            Value shown in list / dashboard / export
            <select
              value={valueStrategy}
              onChange={(e) => setValueStrategy(e.target.value as ValueStrategy)}
            >
              <option value="latest">Latest estimate (any source)</option>
              <option value="preferred_source">Preferred source (falls back to latest)</option>
              <option value="average">Average of sources</option>
            </select>
          </label>
          {valueStrategy === "preferred_source" && (
            <label className="field">
              Preferred source
              <select
                value={preferredSource}
                onChange={(e) => setPreferredSource(e.target.value)}
              >
                <option value="" disabled>choose…</option>
                {settings.sources.map((s: SourceStatus) => (
                  <option key={s.key} value={s.key}>{s.name}</option>
                ))}
              </select>
            </label>
          )}
          <button
            className="primary"
            disabled={saving}
            onClick={() =>
              apply(
                {
                  display_currency: currency.trim().toUpperCase(),
                  reestimate_days: Number(cadence),
                  value_strategy: valueStrategy,
                  preferred_source: valueStrategy === "preferred_source" ? (preferredSource || null) : null,
                },
                "General settings saved.",
              )
            }
          >
            Save
          </button>
        </div>
        <div className="estimate-form">
          <label className="field">
            Empty the trash automatically
            <select
              value={settings.trash_retention_days}
              disabled={saving}
              onChange={(e) => {
                const days = Number(e.target.value);
                apply(
                  { trash_retention_days: days },
                  days
                    ? `Items in the trash are now deleted for good after ${days} days.`
                    : "The trash is no longer emptied automatically.",
                );
              }}
            >
              <option value={0}>Never</option>
              <option value={7}>After 7 days</option>
              <option value={30}>After 30 days</option>
              <option value={90}>After 90 days</option>
              <option value={365}>After a year</option>
            </select>
          </label>
        </div>
        <p className="muted" style={{ marginBottom: 0 }}>
          Amounts in other currencies convert at cached daily ECB rates; anything
          unconvertible is excluded from totals and counted, never guessed. The value
          strategy controls this single blended number; the item page always shows
          every source's own latest value.
        </p>
      </div>

      <div className="card">
        <h2>Price sources</h2>
        <p className="muted" style={{ marginTop: 0 }}>
          <LockIcon /> Keys are encrypted before they are stored and can never be read back, only
          replaced or removed.
        </p>
        {settings.sources.map(sourceCard)}
      </div>

      <div className="card">
        <h2>Cached market data</h2>
        {settings.cached.length === 0 && (
          <p className="muted">
            Nothing cached yet. Spot prices and exchange rates appear here after the first
            estimate or conversion.
          </p>
        )}
        {settings.cached.length > 0 && (
          <table className="estimates">
            <thead>
              <tr><th>Value</th><th>Price</th><th>Source</th><th>Fetched</th></tr>
            </thead>
            <tbody>
              {settings.cached.map((c) => (
                <tr key={c.label}>
                  <td>{c.label}</td>
                  <td>{c.value}</td>
                  <td className="muted">{c.source}</td>
                  <td className="muted">{new Date(c.fetched_at).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="card">
        <h2>Backups</h2>
        <p className="muted" style={{ marginTop: 0 }}>
          An archive holds the database, the photos, and a manifest with checksums. Restore
          it below, or with <code>scripts/restore.sh</code> (see docs/backup-restore.md). Stored API
          keys stay encrypted, and the encryption key is not in the archive.
        </p>
        <div className="estimate-form" style={{ marginTop: 0 }}>
          <a className="button primary" href="/api/backup.zip" download>
            Download backup
          </a>
          <a className="button" href="/api/backup.zip?photos=false" download>
            Data only (no photos)
          </a>
        </div>
        <p className="muted">
          The download starts once the archive is built; allow a minute for a large photo
          collection.
        </p>

        <h3>Scheduled backups</h3>
        <div className="estimate-form" style={{ marginTop: 0 }}>
          <label className="field">
            Schedule
            <select
              value={settings.backup_schedule ?? ""}
              disabled={saving}
              onChange={(e) => {
                const schedule = e.target.value ? (e.target.value as "daily" | "weekly") : null;
                apply(
                  { backup_schedule: schedule },
                  schedule ? `Backups scheduled ${schedule}.` : "Scheduled backups turned off.",
                );
              }}
            >
              <option value="">Off</option>
              <option value="daily">Daily</option>
              <option value="weekly">Weekly</option>
            </select>
          </label>
          <label className="field">
            Keep newest
            <input type="number" min={1} max={365} value={keep} style={{ width: "5rem" }}
              onChange={(e) => setKeep(e.target.value)} />
          </label>
          <button
            disabled={saving || !keep || Number(keep) === settings.backup_keep}
            onClick={() =>
              apply({ backup_keep: Number(keep) }, `Keeping the newest ${keep} backups.`)
            }
          >
            Save
          </button>
          <label className="slot">
            <input
              type="checkbox"
              checked={settings.backup_include_photos}
              disabled={saving}
              onChange={(e) =>
                apply(
                  { backup_include_photos: e.target.checked },
                  e.target.checked
                    ? "Stored backups include photos."
                    : "Stored backups are data only.",
                )
              }
            />
            Include photos
          </label>
          <button disabled={backingUp} onClick={backUpNow}>
            {backingUp ? "Backing up…" : "Back up now"}
          </button>
        </div>
        {backupError && <p className="error">{backupError}</p>}
        {backupNote && <p className="muted">{backupNote}</p>}
        {backups && (
          <>
            <p className="muted">
              Stored in <code>{backups.directory}</code>
              {backups.free_bytes != null && ` (${formatBytes(backups.free_bytes)} free)`}.
              Mount a volume or NAS path there to keep archives off this host. A schedule
              counts from the last run; older archives beyond the keep count are removed.
            </p>
            {backups.last_run && (
              <p className={backups.last_run.ok ? "muted" : "error"}>
                Last run {new Date(backups.last_run.at).toLocaleString()}:{" "}
                {backups.last_run.ok
                  ? `${backups.last_run.file} (${formatBytes(backups.last_run.size ?? 0)})`
                  : `failed: ${backups.last_run.error}`}
              </p>
            )}
            {backups.backups.length > 0 && (
              <table className="estimates">
                <thead>
                  <tr>
                    <th>Archive</th><th>Size</th><th>Created</th>
                    {restore.enabled && <th></th>}
                  </tr>
                </thead>
                <tbody>
                  {backups.backups.map((b) => (
                    <tr key={b.name}>
                      <td>
                        <a href={`/api/backups/${b.name}`} download>{b.name}</a>
                        {b.prerestore && (
                          <span className="badge status-wishlist">before restore</span>
                        )}
                      </td>
                      <td>{formatBytes(b.size)}</td>
                      <td className="muted">{new Date(b.created_at).toLocaleString()}</td>
                      {restore.enabled && (
                        <td className="provenance-toggle">
                          <button
                            disabled={restore.busy || backingUp}
                            onClick={() => restore.inspectArchive(b.name)}
                          >
                            Restore…
                          </button>
                        </td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </>
        )}
        <RestoreBlock restore={restore} appVersion={health?.version} />
      </div>

      <AlertsCard settings={settings} saving={saving} apply={apply} />

      <div className="card">
        <h2>About</h2>
        {health === null ? (
          <p className="muted">Version information unavailable.</p>
        ) : (
          <dl className="facts">
            <div>
              <dt>Version</dt>
              <dd>
                <a
                  href={`https://github.com/jsaumer/cabinet-numismatics/releases/tag/v${health.version}`}
                  target="_blank"
                  rel="noreferrer"
                >
                  {health.version}
                </a>
              </dd>
            </div>
            <div>
              <dt>Database schema</dt>
              <dd
                className={
                  health.schema.status === "ok"
                    ? undefined
                    : health.schema.status === "unknown"
                      ? "muted"
                      : "error"
                }
              >
                {schemaLabel(health.schema)}
              </dd>
            </div>
            <div>
              <dt>Document storage</dt>
              <dd className={health.documents === "ok" ? undefined : "error"}>
                {DOCUMENT_STORAGE[health.documents] ?? health.documents}
              </dd>
            </div>
          </dl>
        )}
      </div>
    </>
  );
}
