import { useEffect, useRef, useState } from "react";

import { api, DemoStatus } from "../api";

const DISMISS_KEY = "cabinet.demo.dismissed";
const POLL_MS = 3000;

function readDismissed(): boolean {
  try {
    return window.localStorage.getItem(DISMISS_KEY) === "1";
  } catch {
    return false;
  }
}

/** A freshly loaded demo shows its notice again, whatever was dismissed. */
export function forgetDemoDismissal() {
  try {
    window.localStorage.removeItem(DISMISS_KEY);
  } catch {
    /* storage refused: nothing was remembered either */
  }
}

/** The demo collection's state, polled while its photos are being fetched.
 * `onChange` runs when the photos finish and when the demo is removed, so
 * the page around it can fetch again. */
export function useDemo(onChange?: () => void) {
  const [status, setStatus] = useState<DemoStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const changed = useRef(onChange);
  changed.current = onChange;

  useEffect(() => {
    let gone = false;
    let timer: number | undefined;
    let wasRunning = false;
    const check = () => {
      api
        .demo()
        .then((found) => {
          if (gone) return;
          setStatus(found);
          const running = found.photos.state === "running";
          if (wasRunning && !running) changed.current?.();
          wasRunning = running;
          if (running) timer = window.setTimeout(check, POLL_MS);
        })
        .catch(() => {
          /* the notice is an extra: no demo state, no notice */
        });
    };
    check();
    return () => {
      gone = true;
      window.clearTimeout(timer);
    };
  }, []);

  async function remove() {
    if (!status) return;
    const pieces = `${status.items} demo piece${status.items === 1 ? "" : "s"}`;
    if (!window.confirm(`Remove the ${pieces} for good? Pieces you entered yourself stay.`)) return;
    setBusy(true);
    setError(null);
    try {
      await api.removeDemo();
      setStatus({ items: 0, photos: { state: "idle", total: 0, fetched: 0, failed: 0 } });
      changed.current?.();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return { status, busy, error, remove };
}

/** Says the pieces on screen are the demo's, and offers to remove them. On
 * the dashboard and the collection page; "Keep it" hides it in this browser
 * (Settings, General still offers the removal). */
export function DemoNotice({ onChange }: { onChange?: () => void }) {
  const { status, busy, error, remove } = useDemo(onChange);
  const [dismissed, setDismissed] = useState<boolean>(readDismissed);

  if (!status || status.items === 0 || dismissed) return null;
  const { photos } = status;
  return (
    <div className="demo-notice no-print" role="status">
      <span>
        <b>This is the demo collection.</b> Look around, then remove it before entering your own
        pieces.
        {photos.state === "running" && ` Fetching photos: ${photos.fetched} of ${photos.total}.`}
        {photos.state === "done" && photos.failed > 0 &&
          ` ${photos.failed} of its ${photos.total} photos could not be fetched.`}
      </span>
      <span className="demo-notice-actions">
        <button type="button" onClick={remove} disabled={busy}>
          {busy ? "Removing…" : "Remove the demo collection"}
        </button>
        <button
          type="button"
          className="link-button"
          onClick={() => {
            try {
              window.localStorage.setItem(DISMISS_KEY, "1");
            } catch {
              /* private mode: hides for this page view only */
            }
            setDismissed(true);
          }}
        >
          Keep it for now
        </button>
      </span>
      {error && (
        <span className="error" role="alert">
          {error}
        </span>
      )}
    </div>
  );
}
