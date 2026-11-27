import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../api";
import { BUILD_VERSION, versionsDiffer } from "../version";

/** Says so when this page and the server are different releases. Two things
 * cause it: a tab left open across an upgrade (a reload fixes it), and a
 * deployment that moved one image's tag and not the other's (a reload
 * doesn't). Checked when the app loads and again whenever the tab comes
 * back into view, which is when a tab left open overnight is next looked
 * at. A failed check says nothing. */
export function VersionNotice() {
  const [server, setServer] = useState<string | null>(null);

  useEffect(() => {
    let gone = false;
    const check = () => {
      api
        .health()
        .then((health) => {
          if (!gone) setServer(health.version ?? null);
        })
        .catch(() => {});
    };
    const onVisible = () => {
      if (document.visibilityState === "visible") check();
    };
    check();
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      gone = true;
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, []);

  if (!versionsDiffer(server)) return null;
  return (
    <p className="error notice-bar no-print" role="status">
      <span>
        This page is Cabinet {BUILD_VERSION} and the server is {server}.
      </span>
      <button type="button" className="link-button" onClick={() => window.location.reload()}>
        Reload the page
      </button>
      <span>
        If it still says so afterwards, the two images are on different versions; see{" "}
        <Link to="/settings/about">Settings, About</Link>.
      </span>
    </p>
  );
}
