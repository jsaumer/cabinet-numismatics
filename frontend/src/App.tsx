import { useEffect, useRef, useState } from "react";
import {
  Link,
  Navigate,
  Route,
  Routes,
  useLocation,
  useNavigate,
  useSearchParams,
} from "react-router-dom";

import { MoonIcon, SunIcon } from "./components/icons";
import { PageErrorBoundary } from "./components/error-boundary";
import { Logo } from "./components/logo";
import { DataCredits } from "./components/data-credits";
import { VersionNotice } from "./components/version-notice";
import { Sidebar } from "./components/sidebar";
import { applyPalette, applyTheme, initialTheme } from "./components/theme";
import { isThemeKey } from "./themes";
import { api } from "./api";
import { AuthProvider, useAuth } from "./auth/AuthContext";
import { AuthBrand } from "./auth/Brand";
import { CONFIRM_MARKER, ConfirmDialogHost } from "./auth/ConfirmDialog";
import { FailedNotice, takeFailedNotice } from "./auth/failedNotice";
import { safeNext } from "./auth/next";
import { ssoErrorMessage } from "./auth/ssoErrors";
import Checklists from "./pages/Checklists";
import Dashboard from "./pages/Dashboard";
import Settings from "./pages/Settings";
import ItemDetail from "./pages/ItemDetail";
import ItemForm from "./pages/ItemForm";
import Import from "./pages/Import";
import ItemList from "./pages/ItemList";
import QuickAdd from "./pages/QuickAdd";
import Login from "./pages/Login";
import Pricing from "./pages/Pricing";
import Report from "./pages/Report";
import AddRun from "./pages/AddRun";
import SharePage from "./pages/share/SharePage";
import Setup from "./pages/Setup";
import Stack from "./pages/Stack";
import Trash from "./pages/Trash";
import { useTitle } from "./components/title";
import { shortcutsEnabled, useShortcutsEnabled } from "./components/shortcuts";

/** The dashboard is the home page. Before v0.16.0 the collection list lived at
 * "/", so a "/" link carrying list filters or paging still opens the list. */
function Home() {
  const { search } = useLocation();
  return search ? <Navigate to={`/collection${search}`} replace /> : <Dashboard />;
}

/** Shown while the boot check (GET /api/auth/state, then GET /api/auth/me)
 * is still running, and while a restore is in progress: no nav chrome, just
 * the brand, since there is nothing from the collection to show yet. */
/** An address that names no page. */
function NotFound() {
  useTitle("Page not found");
  return (
    <div className="card">
      <h1>There is no page here</h1>
      <p className="muted">The address may be mistyped, or the page has moved.</p>
      <p>
        <Link to="/collection">Go to the collection</Link> · <Link to="/">Dashboard</Link>
      </p>
    </div>
  );
}

/** The server answered, and refused: this page's address isn't one of
 * PUBLIC_ORIGINS. The usual cause is a port or a scheme left out, which
 * still loads the page (nginx matches the name alone) and then fails every
 * request a signed-in browser makes. Shown with the exact value to set,
 * since retrying changes nothing. */
function RefusedScreen() {
  useTitle("Wrong address");
  return (
    <div className="auth-page">
      <AuthBrand />
      <div className="card auth-card">
        <h1>Cabinet refused this address</h1>
        <p>
          Cabinet is running, but it only accepts requests from the addresses in{" "}
          <code>PUBLIC_ORIGINS</code>, and this page's isn't one of them. The whole address has to
          match: <code>http</code> or <code>https</code>, the name, and the port.
        </p>
        <p>
          Add this to <code>PUBLIC_ORIGINS</code>, start Cabinet again (
          <code>docker compose up -d</code>), and reload:
        </p>
        <p>
          <code className="refused-origin">{window.location.origin}</code>
        </p>
      </div>
    </div>
  );
}

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
    <p className="error notice-bar no-print" role="status">
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

/** The sign-in page's address, once signed in. The moment a sign-in
 * succeeds the signed-in app renders at /login?next=..., before the sign-in
 * page's own navigation has run, so this route decides where the owner
 * lands: back where they were sent from, not always the dashboard. */
/** Put focus on the page's heading, or on the content area while the page
 * is still loading and has none yet. */
function focusContent(main: HTMLElement) {
  const heading = main.querySelector<HTMLElement>("h1");
  const target = heading ?? main;
  if (heading && !heading.hasAttribute("tabindex")) heading.setAttribute("tabindex", "-1");
  target.focus();
}

function AfterSignIn() {
  const [params] = useSearchParams();
  return <Navigate to={safeNext(params.get("next"))} replace />;
}

function AuthedApp({
  theme,
  setTheme,
}: {
  theme: "light" | "dark";
  setTheme: (fn: (t: "light" | "dark") => "light" | "dark") => void;
}) {
  const { me, signOut } = useAuth();
  const location = useLocation();
  const mainRef = useRef<HTMLElement>(null);
  const lastPath = useRef(location.pathname);

  // After a move to another page, focus goes to its heading, so a screen
  // reader says where it landed and Tab starts from the content. Not while
  // moving through the collection list (each piece is a new address there,
  // and the keys have to stay with the list), and not when the page put
  // focus somewhere itself (the quick add's lookup box).
  useEffect(() => {
    const from = lastPath.current;
    lastPath.current = location.pathname;
    if (from === location.pathname) return;
    if (from.startsWith("/collection") && location.pathname.startsWith("/collection")) return;
    const main = mainRef.current;
    if (!main) return;
    const active = document.activeElement;
    if (active && active !== main && main.contains(active)) return;
    focusContent(main);
    // A page that is still loading has no heading yet: when it arrives, and
    // focus is still where this put it, move on to the heading.
    if (main.querySelector("h1")) return;
    const waiting = new MutationObserver(() => {
      if (!main.querySelector("h1")) return;
      waiting.disconnect();
      if (document.activeElement === main) focusContent(main);
    });
    waiting.observe(main, { childList: true, subtree: true });
    const giveUp = window.setTimeout(() => waiting.disconnect(), 5000);
    return () => {
      waiting.disconnect();
      window.clearTimeout(giveUp);
    };
  }, [location.pathname]);

  // The server holds the theme; the copy in this browser only covers the
  // moments before sign-in. A failed read keeps whatever is showing.
  useEffect(() => {
    api
      .appearance()
      .then((a) => {
        if (isThemeKey(a.theme)) applyPalette(a.theme);
      })
      .catch(() => {});
  }, []);

  return (
    <>
      <a
        className="skip-link"
        href="#main"
        onClick={(e) => {
          // Focus, not a hash in the address: the router owns the address.
          e.preventDefault();
          if (mainRef.current) focusContent(mainRef.current);
        }}
      >
        Skip to content
      </a>
      <ConfirmDialogHost />
      <header className="site-header no-print">
        <Link className="brand" to="/">
          <Logo size={26} />
          Cabinet
        </Link>
        <HeaderSearch />
        <nav>
          <Link className="button primary header-add" to="/items/add" title="Add a piece (N)">
            Add piece
          </Link>
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
      <div className="shell">
      <Sidebar />
      <main id="main" ref={mainRef} tabIndex={-1}>
        <VersionNotice />
        <FailedSignInsNotice />
        <ConfirmReturnNotice />
        <PageErrorBoundary resetKey={location.pathname}>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/collection" element={<ItemList />} />
          <Route path="/collection/:id" element={<ItemList />} />
          <Route path="/dashboard" element={<Navigate to="/" replace />} />
          <Route path="/pricing" element={<Pricing />} />
          <Route path="/stack" element={<Stack />} />
          <Route path="/report" element={<Report />} />
          <Route path="/checklists" element={<Checklists />} />
          <Route path="/import" element={<Import />} />
          <Route path="/trash" element={<Trash />} />
          <Route path="/settings" element={<Navigate to="/settings/general" replace />} />
          <Route path="/settings/:section" element={<Settings />} />
          <Route path="/items/add" element={<QuickAdd />} />
          <Route path="/items/new" element={<ItemForm />} />
          <Route path="/items/run" element={<AddRun />} />
          <Route path="/items/:id" element={<ItemDetail />} />
          <Route path="/items/:id/edit" element={<ItemForm />} />
          <Route path="/setup" element={<Navigate to="/" replace />} />
          <Route path="/login" element={<AfterSignIn />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
        </PageErrorBoundary>
        <DataCredits />
      </main>
      </div>
    </>
  );
}

/** Search from anywhere: Enter opens the collection filtered by the text,
 * and "/" focuses the box from any page that isn't already typing. */
function HeaderSearch() {
  const navigate = useNavigate();
  const location = useLocation();
  const [text, setText] = useState("");
  const ref = useRef<HTMLInputElement>(null);
  const slash = useShortcutsEnabled();

  useEffect(() => {
    if (location.pathname.startsWith("/collection")) {
      setText(new URLSearchParams(location.search).get("q") ?? "");
    }
  }, [location.pathname, location.search]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key !== "/" || e.ctrlKey || e.metaKey || e.altKey) return;
      if (!shortcutsEnabled()) return; // switched off in Settings, General
      const t = e.target as HTMLElement | null;
      if (t && (t.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName))) return;
      e.preventDefault();
      ref.current?.focus();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <form
      className="header-search"
      role="search"
      onSubmit={(e) => {
        e.preventDefault();
        const q = text.trim();
        navigate(q ? `/collection?q=${encodeURIComponent(q)}` : "/collection");
      }}
    >
      <input
        ref={ref}
        type="search"
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="Search the collection"
        aria-label="Search the collection"
      />
      {slash && <kbd aria-hidden="true">/</kbd>}
    </form>
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
  if (status === "unreachable") {
    return (
      <BootScreen text="Cabinet isn't answering yet. It may still be starting; this page checks again every few seconds." />
    );
  }
  if (status === "refused") return <RefusedScreen />;
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
