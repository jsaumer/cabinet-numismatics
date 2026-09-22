import { FormEvent, useEffect, useRef, useState } from "react";

import { api, setReauthHandler } from "../api";

// The "confirm your password to continue" dialog (SPEC_0300 section 5): one
// instance, mounted once by <ConfirmDialogHost/> in App.tsx. Two callers open
// it through the same promise-based service:
//   - client.ts's req(), automatically, when a "fresh" route answers 403
//     {reauth_required: true}; it retries the original request once the
//     promise resolves.
//   - auth/freshLink.tsx, before navigating a plain download link, when
//     GET /api/auth/me's confirmed_until isn't comfortably in the future.
// Cancelling rejects the promise with a clear error; a wrong password shows
// inline and leaves the dialog open, per SPEC_0300.

type Opener = () => Promise<void>;

let opener: Opener | null = null;

/** Registered once by <ConfirmDialogHost/>; unset if it ever unmounts. */
function setOpener(fn: Opener | null) {
  opener = fn;
  setReauthHandler(fn);
}

/** Opens the dialog and resolves once the password is confirmed. Rejects if
 * the visitor cancels, or if no dialog is mounted to answer. */
export function requestConfirm(): Promise<void> {
  if (!opener) return Promise.reject(new Error("Confirmation isn't available right now."));
  return opener();
}

interface PendingConfirm {
  resolve: () => void;
  reject: (e: Error) => void;
}

/** Mount once, inside the signed-in app. Renders nothing until something
 * asks for confirmation. */
export function ConfirmDialogHost() {
  const [open, setOpen] = useState(false);
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const pending = useRef<PendingConfirm | null>(null);

  useEffect(() => {
    setOpener(
      () =>
        new Promise<void>((resolve, reject) => {
          pending.current = { resolve, reject };
          setPassword("");
          setError(null);
          setOpen(true);
        }),
    );
    return () => setOpener(null);
  }, []);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") cancel();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  function cancel() {
    setOpen(false);
    pending.current?.reject(new Error("Confirmation cancelled."));
    pending.current = null;
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.confirmPassword(password);
      setOpen(false);
      pending.current?.resolve();
      pending.current = null;
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (!open) return null;

  return (
    <div className="modal" role="presentation" onClick={cancel}>
      <div
        className="card modal-body confirm-dialog"
        role="dialog"
        aria-modal="true"
        aria-label="Confirm your password"
        onClick={(e) => e.stopPropagation()}
      >
        <h2>Confirm your password to continue.</h2>
        <form onSubmit={submit} className="estimate-form" style={{ flexDirection: "column", alignItems: "stretch" }}>
          <label className="field">
            Password
            <input
              type="password"
              autoFocus
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </label>
          {error && <p className="error">{error}</p>}
          <div className="estimate-form" style={{ marginTop: 0 }}>
            <button type="submit" className="primary" disabled={busy || !password}>
              {busy ? "Confirming…" : "Confirm"}
            </button>
            <button type="button" onClick={cancel} disabled={busy}>
              Cancel
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
