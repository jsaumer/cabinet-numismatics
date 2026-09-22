import { useEffect, useRef, useState } from "react";

import { api, RestoreInspection, RestoreOutcome, RestoreStatus } from "../api";
import { FileButton } from "./controls";

// Settings → Backups → Restore: pick an archive, read the summary, type the
// phrase, then watch the steps. The backend answers 503 to everything but the
// status call while it restores, so the poll shrugs off errors.

const STEPS: Record<string, string> = {
  safety_backup: "Taking a safety backup",
  database: "Restoring the database",
  migrations: "Running migrations",
  photos: "Restoring photos",
  documents: "Restoring documents",
  finishing: "Finishing",
};

const POLL_MS = 2000;
const GIVE_UP_MS = 10 * 60 * 1000; // without one answer from the status call

type Phase = "idle" | "inspecting" | "review" | "running" | "done" | "failed";

export interface RestoreControl {
  enabled: boolean;
  /** Something is in flight: archive rows shouldn't start another. */
  busy: boolean;
  running: boolean;
  phase: Phase;
  status: RestoreStatus | null;
  inspection: RestoreInspection | null;
  outcome: RestoreOutcome | null;
  error: string | null;
  step: string | null;
  phrase: string;
  inspectArchive: (name: string) => void;
  inspectFile: (file: File) => void;
  cancel: () => void;
  run: (confirm: string) => void;
}

/** `onFinished` runs once a restore ends, either way: maintenance is over, so
 * the page can fetch its data again. */
export function useRestore(onFinished: () => void): RestoreControl {
  const [status, setStatus] = useState<RestoreStatus | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [inspection, setInspection] = useState<RestoreInspection | null>(null);
  const [uploaded, setUploaded] = useState(false);
  const [outcome, setOutcome] = useState<RestoreOutcome | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [step, setStep] = useState<string | null>(null);
  const finished = useRef(onFinished);
  finished.current = onFinished;

  useEffect(() => {
    api
      .restoreStatus()
      .then((s) => {
        setStatus(s);
        if (s.enabled && s.state === "running") {
          setStep(s.step);
          setPhase("running");
        }
      })
      .catch(() => setStatus(null));
  }, []);

  useEffect(() => {
    if (phase !== "running") return;
    let stopped = false;
    let timer: number | undefined;
    let lastAnswer = Date.now();

    const finish = (s: RestoreStatus | null, ok: boolean, message: string | null) => {
      if (s) setStatus(s);
      setOutcome(s?.last ?? null);
      setError(ok ? null : message);
      setPhase(ok ? "done" : "failed");
      finished.current();
    };

    const poll = async () => {
      try {
        const s = await api.restoreStatus();
        if (stopped) return;
        lastAnswer = Date.now();
        if (s.state === "running") {
          setStep(s.step);
        } else if (s.state === "done" || (s.state !== "failed" && s.last?.ok)) {
          return finish(s, true, null);
        } else {
          return finish(
            s,
            false,
            s.last?.error ?? "The restore stopped without a result; check the backend's log.",
          );
        }
      } catch {
        // Maintenance, a dropped connection, a restarting proxy: keep asking.
        if (stopped) return;
        if (Date.now() - lastAnswer > GIVE_UP_MS) {
          return finish(
            null,
            false,
            "Cabinet hasn't answered for ten minutes. The restore may still be running; " +
              "reload this page to check.",
          );
        }
      }
      timer = window.setTimeout(poll, POLL_MS);
    };

    timer = window.setTimeout(poll, POLL_MS);
    return () => {
      stopped = true;
      window.clearTimeout(timer);
    };
  }, [phase]);

  // Only an upload is staged; an archive picked from the list stays where it is.
  const discard = () => {
    if (inspection && uploaded) api.discardRestore(inspection.restore_id).catch(() => undefined);
  };

  const inspect = (request: Promise<RestoreInspection>, fromUpload: boolean) => {
    discard();
    setInspection(null);
    setOutcome(null);
    setError(null);
    setPhase("inspecting");
    request
      .then((found) => {
        setInspection(found);
        setUploaded(fromUpload);
        setPhase("review");
      })
      .catch((e: Error) => {
        setError(e.message);
        setPhase("idle");
      });
  };

  return {
    enabled: status?.enabled === true,
    busy: phase === "inspecting" || phase === "running",
    running: phase === "running",
    phase,
    status,
    inspection,
    outcome,
    error,
    step,
    phrase: status?.confirm_phrase || "RESTORE",
    inspectArchive: (name) => inspect(api.inspectRestoreArchive(name), false),
    inspectFile: (file) => inspect(api.inspectRestoreFile(file), true),
    cancel: () => {
      discard();
      setInspection(null);
      setError(null);
      setPhase("idle");
    },
    run: (confirm) => {
      if (!inspection) return;
      setError(null);
      api
        .runRestore(inspection.restore_id, confirm)
        .then(() => {
          setStep("safety_backup");
          setPhase("running");
        })
        .catch((e: Error) => setError(e.message));
    },
  };
}

const count = (value: number | null | undefined) =>
  value == null ? "–" : value.toLocaleString();

const when = (iso: string | null | undefined) => (iso ? new Date(iso).toLocaleString() : "–");

function Summary({ found, appVersion }: { found: RestoreInspection; appVersion?: string }) {
  const { archive, current } = found;
  const rows: [string, string, string][] = [
    ["Items", count(archive.items), count(current.items)],
    ["Photos", count(archive.photos), count(current.photos)],
    ["Documents", count(archive.documents), count(current.documents)],
    ["In the trash", count(archive.trashed), count(current.trashed)],
    ["Schema revision", archive.revision ?? "–", current.revision ?? "–"],
    ["App version", archive.app_version ?? "–", appVersion ?? "–"],
    ["Archive date", when(archive.created_at), "–"],
  ];
  return (
    <table className="estimates restore-summary">
      <thead>
        <tr><th></th><th>This archive</th><th>Here now</th></tr>
      </thead>
      <tbody>
        {rows.map(([label, theirs, ours]) => (
          <tr key={label}>
            <td className="muted">{label}</td>
            <td>{theirs}</td>
            <td>{ours}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function RestoreBlock({
  restore,
  appVersion,
}: {
  restore: RestoreControl;
  appVersion?: string;
}) {
  const [typed, setTyped] = useState("");
  const { phase, inspection, outcome, status, phrase } = restore;

  useEffect(() => {
    if (phase !== "review") setTyped("");
  }, [phase]);

  if (!restore.enabled) return null;
  const last = status?.last ?? null;

  return (
    <div className="restore-block">
      <h3>Restore</h3>
      <p className="muted" style={{ marginTop: 0 }}>
        Restoring replaces everything here (the items, their values and history, the settings,
        and the photos and documents when the archive carries them) with what is in the
        archive. A safety backup of the collection as it is now is taken first.
      </p>

      {phase !== "running" && (
        <div className="estimate-form" style={{ marginTop: 0 }}>
          <FileButton
            accept=".zip,application/zip"
            disabled={restore.busy}
            onFiles={(files) => restore.inspectFile(files[0])}
          >
            Restore from a file
          </FileButton>
          {phase === "inspecting" && <span className="muted">Checking the archive…</span>}
        </div>
      )}

      {restore.error && phase !== "failed" && <p className="error">{restore.error}</p>}

      {phase === "review" && inspection && (
        <>
          <p>
            <b>{inspection.archive.name}</b>
          </p>
          <Summary found={inspection} appVersion={appVersion} />
          {inspection.will_migrate && (
            <p className="muted">
              This archive is from an older Cabinet; it will be migrated to the current schema.
            </p>
          )}
          {!inspection.replaces_files && (
            <p className="muted">
              Photos and documents are not in this archive and will be left as they are.
            </p>
          )}
          <p className="muted">{inspection.credentials_note}</p>
          {inspection.secrets.length > 0 && (
            <p className="muted">Saved in the archive and kept: {inspection.secrets.join(", ")}.</p>
          )}
          {inspection.secrets_cleared.length > 0 && (
            <p className="muted">
              In the archive but not usable here, so cleared after the restore:{" "}
              {inspection.secrets_cleared.join(", ")}. Enter them again in Settings.
            </p>
          )}
          {inspection.secrets_note && <p className="muted">{inspection.secrets_note}</p>}
          <div className="estimate-form">
            <label className="field">
              Type {phrase} to confirm
              <input
                value={typed}
                autoComplete="off"
                spellCheck={false}
                style={{ width: "10rem" }}
                onChange={(e) => setTyped(e.target.value)}
              />
            </label>
            <button
              className="danger"
              disabled={typed.trim() !== phrase}
              onClick={() => restore.run(typed.trim())}
            >
              Restore this archive
            </button>
            <button onClick={restore.cancel}>Cancel</button>
          </div>
        </>
      )}

      {phase === "running" && (
        <p role="status">
          <b>{STEPS[restore.step ?? ""] ?? "Restoring"}…</b>{" "}
          <span className="muted">
            Cabinet is unavailable until this finishes. Keep this page open.
          </span>
        </p>
      )}

      {phase === "done" && (
        <p className="gain" role="status">
          Restore complete: {count(outcome?.items)} items, {count(outcome?.photos)} photos,{" "}
          {count(outcome?.documents)} documents
          {outcome?.archive ? ` from ${outcome.archive}` : ""}.
          {outcome?.safety_backup &&
            ` The collection as it was is in ${outcome.safety_backup}.`}
          {outcome?.secrets_cleared?.length
            ? ` Cleared: ${outcome.secrets_cleared.join(", ")}. Enter them again in Settings.`
            : ""}
        </p>
      )}

      {phase === "failed" && (
        <p className="error" role="status">
          Restore failed: {restore.error}
          {outcome?.safety_backup && ` The safety backup is ${outcome.safety_backup}.`}
        </p>
      )}

      {last && phase !== "done" && phase !== "failed" && phase !== "running" && (
        <p className="muted">
          Last restore {when(last.at)}:{" "}
          {last.ok
            ? `${last.archive ?? "an archive"} (${count(last.items)} items)`
            : `failed: ${last.error ?? "no reason recorded"}`}
        </p>
      )}
    </div>
  );
}
