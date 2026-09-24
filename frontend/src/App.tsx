import { useEffect, useState } from "react";
import { Link, Navigate, NavLink, Route, Routes, useLocation, useNavigate } from "react-router-dom";

import { MoonIcon, SettingsIcon, SunIcon, TrashIcon } from "./components/icons";
import { applyTheme, initialTheme } from "./components/theme";
import { AuthProvider, useAuth } from "./auth/AuthContext";
import { AuthBrand } from "./auth/Brand";
import { CONFIRM_MARKER, ConfirmDialogHost } from "./auth/ConfirmDialog";
import { FailedNotice, takeFailedNotice } from "./auth/failedNotice";
import { ssoErrorMessage } from "./auth/ssoErrors";
import Checklists from "./pages/Checklists";
import Dashboard from "./pages/Dashboard";
import Settings from "./pages/Settings";
import ItemDetail from "./pages/ItemDetail";
import ItemForm from "./pages/ItemForm";
import Import from "./pages/Import";
import ItemList from "./pages/ItemList";
import Login from "./pages/Login";
import Pricing from "./pages/Pricing";
import Report from "./pages/Report";
import AddRun from "./pages/AddRun";
import SharePage from "./pages/share/SharePage";
import Setup from "./pages/Setup";
import Stack from "./pages/Stack";
import Trash from "./pages/Trash";

/** The dashboard is the home page. Before v0.16.0 the collection list lived at
 * "/", so a "/" link carrying list filters or paging still opens the list. */
function Home() {
  const { search } = useLocation();
  return search ? <Navigate to={`/collection${search}`} replace /> : <Dashboard />;
}

/** Shown while the boot check (GET /api/auth/state, then GET /api/auth/me)
 * is still running, and while a restore is in progress: no nav chrome, just
 * the brand, since there is nothing from the collection to show yet. */
function BootScreen({ text }: { text: string }) {
  return (
    <div className="auth-page">
      <AuthBrand />
      <div className="card auth-card">
        <p className="muted" role="status">
          {text}
        </p>
      </div>
    </div>
  );
}

function FailedSignInsNotice() {
  const [notice, setNotice] = useState<FailedNotice | null>(null);

  useEffect(() => {
    setNotice(takeFailedNotice());
  }, []);

  if (!notice) return null;
  const since = new Date(notice.since).toLocaleString(undefined, {
    month: "long",
    day: "numeric",
  });
  return (
    <p className="error notice-bar no-print">
      {notice.count} failed sign-in{notice.count === 1 ? "" : "s"} since your last visit on{" "}
      {since}. <Link to="/settings/account">See the audit log.</Link>{" "}
      <button type="button" className="link-button" onClick={() => setNotice(null)}>
        Dismiss
      </button>
    </p>
  );
}

/** A return from the confirm dialog's "Confirm at your sign-in provider"
 * path (auth/ConfirmDialog.tsx): the pending action is never replayed
 * automatically (CR-20, R2-20), so this only tells the owner what happened
 * and lets them repeat what they started. confirm_error carries a code on
 * failure; success carries only the marker ConfirmDialog.tsx appended to
 * `next` before navigating away, since the backend's own redirect on
 * success has no marker of its own. Both are stripped from the address bar
 * so a reload doesn't repeat the note. */
function ConfirmReturnNotice() {
  const location = useLocation();
  const navigate = useNavigate();
  const [note, setNote] = useState<{ text: string; failed: boolean } | null>(null);

  useEffect(() => {
    const params = new URLSearchParams(location.search);
    const confirmError = params.get("confirm_error");
    const confirmed = params.get(CONFIRM_MARKER);
    if (!confirmError && !confirmed) return;
    setNote(
      confirmError
        ? { text: ssoErrorMessage(confirmError), failed: true }
        : { text: "Confirmed. Repeat the action you started.", failed: false },
    );
    params.delete("confirm_error");
    params.delete(CONFIRM_MARKER);
    navigate(
      { pathname: location.pathname, search: params.toString() },
      { replace: true },
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (!note) return null;
  return (
    <p className={`${note.failed ? "error" : "muted"} notice-bar no-print`}>
      {note.text}{" "}
      <button type="button" className="link-button" onClick={() => setNote(null)}>
        Dismiss
      </button>
    </p>
  );
}

function AuthedApp({
  theme,
  setTheme,
}: {
  theme: "light" | "dark";
  setTheme: (fn: (t: "light" | "dark") => "light" | "dark") => void;
}) {
  const { me, signOut } = useAuth();

  return (
    <>
      <ConfirmDialogHost />
      <header className="site-header no-print">
        <Link className="brand" to="/">
          <img src="/logo.svg" alt="" width="26" height="26" />
          Cabinet
        </Link>
        <span className="subtitle">Numismatics: Coin &amp; Paper Money Collection Manager</span>
        <nav>
          <NavLink to="/" end>Dashboard</NavLink>
          <NavLink to="/collection">Collection</NavLink>
          <NavLink to="/pricing">Pricing</NavLink>
          <NavLink to="/stack">Stack</NavLink>
          <NavLink to="/checklists">Checklists</NavLink>
          <NavLink to="/import">Import</NavLink>
          <NavLink className="nav-icon" to="/settings" title="Settings" aria-label="Settings">
            <SettingsIcon />
          </NavLink>
          <NavLink className="nav-icon" to="/trash" title="Trash" aria-label="Trash">
            <TrashIcon />
          </NavLink>
          <button
            className="theme-toggle nav-icon"
            title={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
            aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
            onClick={() => setTheme((t) => (t === "dark" ? "light" : "dark"))}
          >
            {theme === "dark" ? <SunIcon /> : <MoonIcon />}
          </button>
          {me && (
            <span className="account-menu">
              <span className="muted account-name">{me.username}</span>
              <button type="button" onClick={() => void signOut()}>
                Sign out
              </button>
            </span>
          )}
        </nav>
      </header>
      <main>
        <FailedSignInsNotice />
        <ConfirmReturnNotice />
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/collection" element={<ItemList />} />
          <Route path="/dashboard" element={<Navigate to="/" replace />} />
          <Route path="/pricing" element={<Pricing />} />
          <Route path="/stack" element={<Stack />} />
          <Route path="/report" element={<Report />} />
          <Route path="/checklists" element={<Checklists />} />
          <Route path="/import" element={<Import />} />
          <Route path="/trash" element={<Trash />} />
          <Route path="/settings" element={<Navigate to="/settings/general" replace />} />
          <Route path="/settings/:section" element={<Settings />} />
          <Route path="/items/new" element={<ItemForm />} />
          <Route path="/items/run" element={<AddRun />} />
          <Route path="/items/:id" element={<ItemDetail />} />
          <Route path="/items/:id/edit" element={<ItemForm />} />
          <Route path="/setup" element={<Navigate to="/" replace />} />
          <Route path="/login" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </>
  );
}

function Gate() {
  const { status } = useAuth();
  // Applied here, above every route (setup and sign-in included), not just
  // the signed-in app: a remembered light mode should hold on those pages
  // too, even though only the signed-in header carries the toggle itself.
  const [theme, setTheme] = useState<"light" | "dark">(initialTheme);
  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  if (status === "loading") return <BootScreen text="Loading…" />;
  if (status === "restoring") {
    return <BootScreen text="A restore is running. This page checks again every few seconds." />;
  }
  if (status === "setup") {
    return (
      <Routes>
        <Route path="/setup" element={<Setup />} />
        <Route path="*" element={<Navigate to="/setup" replace />} />
      </Routes>
    );
  }
  if (status === "anon") {
    return (
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="*" element={<RedirectToLogin />} />
      </Routes>
    );
  }
  return <AuthedApp theme={theme} setTheme={setTheme} />;
}

function RedirectToLogin() {
  const location = useLocation();
  const path = location.pathname + location.search;
  const next = path && path !== "/" ? `?next=${encodeURIComponent(path)}` : "";
  return <Navigate to={`/login${next}`} replace />;
}

/** A share link (v0.32.0): read-only, no sign-in, rendered before anything
 * about auth runs. It never calls GET /api/auth/state or /api/auth/me (the
 * page's own calls are all `raw`, see api/calls.ts), and AuthProvider isn't
 * mounted at all here, so its 401 handler can never fire on this branch. */
function ShareRoutes() {
  return (
    <Routes>
      <Route path="/s/:token" element={<SharePage />} />
      <Route path="/s/:token/items/:itemId" element={<SharePage />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export default function App() {
  const location = useLocation();
  if (location.pathname === "/s" || location.pathname.startsWith("/s/")) {
    return <ShareRoutes />;
  }
  return (
    <AuthProvider>
      <Gate />
    </AuthProvider>
  );
}
