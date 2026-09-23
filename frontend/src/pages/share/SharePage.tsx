import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import { api, ShareManifest } from "../../api";
import { MoonIcon, SunIcon } from "../../components/icons";
import { applyTheme, initialTheme } from "../../components/theme";
import ShareChecklist from "./ShareChecklist";
import ShareGrid from "./ShareGrid";
import SharePiece from "./SharePiece";

/** <meta name="robots"> while a share page is mounted, on top of nginx's own
 * X-Robots-Tag header on /s/ (proxy/nginx.conf) and the API's on every
 * answer (routers/share.py). */
function useNoIndex() {
  useEffect(() => {
    const meta = document.createElement("meta");
    meta.name = "robots";
    meta.content = "noindex";
    document.head.appendChild(meta);
    return () => {
      document.head.removeChild(meta);
    };
  }, []);
}

function ThemeToggle() {
  const [theme, setTheme] = useState(initialTheme);
  useEffect(() => applyTheme(theme), [theme]);
  return (
    <button
      type="button"
      className="theme-toggle nav-icon"
      title={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
      aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
      onClick={() => setTheme((t) => (t === "dark" ? "light" : "dark"))}
    >
      {theme === "dark" ? <SunIcon /> : <MoonIcon />}
    </button>
  );
}

/** A share link, rendered outside the sign-in gate entirely: App.tsx routes
 * /s/* here before AuthProvider is even mounted, so this page never calls
 * GET /api/auth/state or /api/auth/me. The manifest decides the body: a
 * piece's own page when the URL names one, the filled slots for a
 * checklist link, otherwise the grid. Every failure the API can answer
 * (sharing off, an unknown or revoked token) is the same 404, so this page
 * shows the same one message for all of them; nothing here links back into
 * the signed-in app. */
export default function SharePage() {
  const { token, itemId } = useParams<{ token: string; itemId?: string }>();
  const [manifest, setManifest] = useState<ShareManifest | null>(null);
  const [notFound, setNotFound] = useState(false);

  useNoIndex();

  useEffect(() => {
    setManifest(null);
    setNotFound(false);
    if (!token) {
      setNotFound(true);
      return;
    }
    api
      .shareManifest(token)
      .then(setManifest)
      .catch(() => setNotFound(true));
  }, [token]);

  if (notFound) {
    return (
      <div className="auth-page">
        <div className="auth-brand">
          <img src="/logo.svg" alt="" width="56" height="56" />
          <div className="auth-brand-name">Cabinet</div>
        </div>
        <div className="card auth-card">
          <p className="muted" role="status">
            This link isn&apos;t active.
          </p>
        </div>
      </div>
    );
  }

  return (
    <>
      <header className="site-header no-print">
        <span className="brand">
          <img src="/logo.svg" alt="" width="26" height="26" />
          {manifest ? manifest.name : "Cabinet"}
        </span>
        <nav>
          <ThemeToggle />
        </nav>
      </header>
      <main>
        {!manifest ? (
          <p className="muted">Loading…</p>
        ) : itemId ? (
          <SharePiece token={token as string} shareName={manifest.name} />
        ) : manifest.kind === "checklist" ? (
          <ShareChecklist token={token as string} manifest={manifest} />
        ) : (
          <ShareGrid token={token as string} manifest={manifest} />
        )}
      </main>
      <footer className="share-footer no-print">
        <span className="muted">Shared from Cabinet</span>
      </footer>
    </>
  );
}
