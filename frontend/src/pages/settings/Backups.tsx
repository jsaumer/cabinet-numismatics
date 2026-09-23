import { useEffect, useState } from "react";

import { api, BackupList, formatBytes, Health } from "../../api";
import { FreshLink } from "../../auth/FreshLink";
import { EyeIcon, EyeOffIcon } from "../../components/icons";
import { RestoreBlock, useRestore } from "../../components/restore";
import { Section, SettingRow, useSettings } from "./shared";

const DAILY_LABELS: Record<number, string> = {
  7: "7 days",
  14: "14 days",
  30: "30 days",
  90: "90 days",
  365: "1 year",
};
const WEEKLY_LABELS: Record<number, string> = {
  28: "4 weeks",
  56: "8 weeks",
  91: "13 weeks (a quarter)",
  182: "26 weeks (half a year)",
  365: "52 weeks (a year)",
};

function retentionChoices(settings: { backup_retention_choices: { daily: number[]; weekly: number[] } }, schedule: string) {
  return schedule === "weekly" ? settings.backup_retention_choices.weekly : settings.backup_retention_choices.daily;
}

function retentionLabel(days: number, schedule: string): string {
  if (days === 0) return "Forever";
  const labels = schedule === "weekly" ? WEEKLY_LABELS : DAILY_LABELS;
  return labels[days] ?? `${days} days`;
}

function nearest(choices: number[], value: number): number {
  return choices.reduce((best, d) => (Math.abs(d - value) < Math.abs(best - value) ? d : best), choices[0]);
}

/** Settings → Backups: the backup key, the schedule and retention, the
 * archives themselves, and restoring one. */
export default function BackupsSection() {
  const { settings, error, note, saving, apply, reload: reloadSettings } = useSettings();
  const [health, setHealth] = useState<Health | null>(null);
  const [backups, setBackups] = useState<BackupList | null>(null);
  const [backupError, setBackupError] = useState<string | null>(null);
  const [backupNote, setBackupNote] = useState<string | null>(null);
  const [backingUp, setBackingUp] = useState(false);
  const [keyBusy, setKeyBusy] = useState(false);
  const [keyVisible, setKeyVisible] = useState(false);
  const [keyCopied, setKeyCopied] = useState(false);

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

  // A restore replaced the database: everything on this page is stale.
  const restore = useRestore(() => {
    setBackupError(null);
    setBackupNote(null);
    reloadSettings();
    loadAbout();
  });

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

  async function markKeySaved() {
    setKeyBusy(true);
    setBackupError(null);
    try {
      await api.markBackupKeySaved();
      loadBackups();
    } catch (e) {
      setBackupError((e as Error).message);
    } finally {
      setKeyBusy(false);
    }
  }

  async function copyKey(fingerprint: string) {
    try {
      await navigator.clipboard.writeText(fingerprint);
      setKeyCopied(true);
      window.setTimeout(() => setKeyCopied(false), 2000);
    } catch {
      setKeyCopied(false);
    }
  }

  async function deleteBackup(name: string) {
    if (!window.confirm(`Delete ${name}? This can't be undone.`)) return;
    setKeyBusy(true);
    setBackupError(null);
    try {
      await api.deleteBackup(name); // a fresh route: the password dialog opens if needed
      setBackupNote(`Deleted ${name}.`);
      loadBackups();
    } catch (e) {
      setBackupError((e as Error).message);
    } finally {
      setKeyBusy(false);
    }
  }

  function changeSchedule(schedule: "daily" | "weekly" | null) {
    if (!settings) return;
    const choices = retentionChoices(settings, schedule ?? "daily");
    const current = settings.backup_retention_days;
    if (current !== 0 && !choices.includes(current)) {
      const snapped = nearest(choices, current);
      const scheduleText = schedule ? `Backups scheduled ${schedule}` : "Scheduled backups turned off";
      apply(
        { backup_schedule: schedule, backup_retention_days: snapped },
        `${scheduleText}; keeping archives for ${retentionLabel(snapped, schedule ?? "daily")}.`,
      );
    } else {
      apply(
        { backup_schedule: schedule },
        schedule ? `Backups scheduled ${schedule}.` : "Scheduled backups turned off.",
      );
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

  const schedule = settings.backup_schedule ?? "daily"; // which choice set is in effect
  const choices = retentionChoices(settings, schedule);

  return (
    <Section
      title="Backups"
      description={
        <>
          Every archive is encrypted with the backup key below and signed, so it can be neither
          read nor altered without it. It holds the collection's database, the photos, and the
          documents, never your sign-in or API tokens. Restore it below, or with{" "}
          <code>scripts/restore.sh</code> (see docs/backup-restore.md).
        </>
      }
    >
      {error && <p className="error">{error}</p>}
      {note && <p className="muted">{note}</p>}

      {backups && (
        <>
          <h3>Backup key</h3>
          <div className="estimate-form" style={{ marginTop: 0 }}>
            <div className="key-field">
              <input
                type={keyVisible ? "text" : "password"}
                readOnly
                value={backups.key.fingerprint}
              />
              <button
                type="button"
                className="link-button"
                aria-label={keyVisible ? "Hide public key" : "Show public key"}
                onClick={() => setKeyVisible((v) => !v)}
              >
                {keyVisible ? <EyeOffIcon /> : <EyeIcon />}
              </button>
              <button type="button" onClick={() => copyKey(backups.key.fingerprint)}>
                {keyCopied ? "Copied" : "Copy"}
              </button>
            </div>
          </div>
          <p className="muted" style={{ marginTop: "0.3rem" }}>
            This is the public half of your backup key, shown so you can confirm which key is in
            use. The secret half never leaves the container:{" "}
            <code>python -m app.cli backup-key show</code> prints it.
          </p>
          {!backups.key.saved && !backups.key.supplied && (
            <div className="estimate-form" style={{ marginTop: 0 }}>
              <p className="error" style={{ margin: 0, flexBasis: "100%" }}>
                Save your backup key. From the host:{" "}
                <code>docker compose exec backend python -m app.cli backup-key show</code>, then
                keep it in a password manager. The secret half is never shown in the browser.
              </p>
              <button disabled={keyBusy} onClick={markKeySaved}>
                I have saved it
              </button>
            </div>
          )}
          {backups.key.supplied && (
            <p className="muted" style={{ margin: 0 }}>
              Supplied by{" "}
              <code>{backups.key.location === "environment" ? "BACKUP_KEY" : "BACKUP_KEY_FILE"}</code>
              ; keep your own copy of that secret safe.
            </p>
          )}
          {backups.key.location_message && (
            <p className="error">{backups.key.location_message}</p>
          )}
        </>
      )}

      <h3>Schedule and retention</h3>
      <SettingRow label="Schedule">
        <select
          value={settings.backup_schedule ?? ""}
          disabled={saving}
          onChange={(e) => changeSchedule(e.target.value ? (e.target.value as "daily" | "weekly") : null)}
        >
          <option value="">Off</option>
          <option value="daily">Daily</option>
          <option value="weekly">Weekly</option>
        </select>
      </SettingRow>
      <SettingRow label="Keep archives for">
        <select
          value={String(settings.backup_retention_days)}
          disabled={saving}
          onChange={(e) => {
            const days = Number(e.target.value);
            apply(
              { backup_retention_days: days },
              days ? `Keeping archives for ${retentionLabel(days, schedule)}.` : "Keeping every archive forever.",
            );
          }}
        >
          {choices.map((days) => (
            <option key={days} value={days}>
              {retentionLabel(days, schedule)}
            </option>
          ))}
          <option value={0}>Forever</option>
        </select>
      </SettingRow>
      {settings.backup_retention_days === 0 && (
        <p className="error">
          Retention is off: nothing is ever deleted, and this directory will grow without
          limit. Delete archives below by hand, or choose a retention.
        </p>
      )}
      <SettingRow label="Include photos">
        <input
          type="checkbox"
          aria-label="Include photos"
          checked={settings.backup_include_photos}
          disabled={saving}
          onChange={(e) =>
            apply(
              { backup_include_photos: e.target.checked },
              e.target.checked ? "Stored backups include photos." : "Stored backups are data only.",
            )
          }
        />
      </SettingRow>

      <h3>Archives</h3>
      <div className="estimate-form" style={{ marginTop: 0 }}>
        <FreshLink className="button primary" href="/api/backup.zip" download>
          Download backup
        </FreshLink>
        <FreshLink className="button" href="/api/backup.zip?photos=false" download>
          Data only (no photos)
        </FreshLink>
        <button disabled={backingUp} onClick={backUpNow}>
          {backingUp ? "Backing up…" : "Back up now"}
        </button>
      </div>
      <p className="muted">
        The download starts once the archive is built; allow a minute for a large photo
        collection. Confirms your password first if it's been more than a few minutes.
      </p>
      {backupError && <p className="error">{backupError}</p>}
      {backupNote && <p className="muted">{backupNote}</p>}
      {backups && (
        <>
          <p className="muted">
            Stored in <code>{backups.directory}</code>
            {backups.free_bytes != null && ` (${formatBytes(backups.free_bytes)} free)`}.
            Mount a volume or NAS path there to keep archives off this host. A schedule
            counts from the last run; after each run, archives older than the retention
            are removed, but the newest full and the newest data-only archive always stay.
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
                  <th>Archive</th><th>Size</th><th>Created</th><th></th>
                </tr>
              </thead>
              <tbody>
                {backups.backups.map((b) => (
                  <tr key={b.name}>
                    <td>
                      <FreshLink href={`/api/backups/${b.name}`} download>{b.name}</FreshLink>
                      {b.prerestore && (
                        <span className="badge status-wishlist">before restore</span>
                      )}
                    </td>
                    <td>{formatBytes(b.size)}</td>
                    <td className="muted">{new Date(b.created_at).toLocaleString()}</td>
                    <td className="provenance-toggle">
                      {restore.enabled && (
                        <button
                          disabled={restore.busy || backingUp || keyBusy}
                          onClick={() => restore.inspectArchive(b.name)}
                        >
                          Restore…
                        </button>
                      )}{" "}
                      <button
                        className="danger"
                        disabled={restore.busy || backingUp || keyBusy}
                        onClick={() => deleteBackup(b.name)}
                      >
                        Delete
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}

      <RestoreBlock restore={restore} appVersion={health?.version} />
    </Section>
  );
}
