import { FormEvent, useEffect, useState } from "react";

import { api, ApiToken, AuditEntry, AuthSession, NewApiToken, TokenScope } from "../api";
import { CloseIcon } from "./icons";

const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString() : "–");

// A user agent string is long and mostly noise; keep the browser and OS,
// drop the rest.
function shortAgent(agent: string | null): string {
  if (!agent) return "–";
  const browser = agent.match(/(Chrome|Firefox|Safari|Edg)\/[\d.]+/)?.[0]?.replace("Edg/", "Edge/");
  // Not a browser (curl, a script): its own words say more than whatever
  // sits first in its parentheses.
  if (!browser) return agent.slice(0, 60);
  const os = agent.match(/\((.*?)\)/)?.[1]?.split(";")[0]?.trim();
  return [browser, os].filter(Boolean).join(", ");
}

const AUDIT_LABELS: Record<string, string> = {
  setup: "Account set up",
  sign_in: "Signed in",
  sign_in_failed: "Failed sign-in",
  sign_out: "Signed out",
  reauth: "Password confirmed",
  password_changed: "Password changed",
  username_changed: "Username changed",
  password_reset: "Password reset (container command)",
  sessions_revoked_all: "Signed out everywhere",
  tokens_revoked_all: "All tokens revoked",
  session_revoked: "Session ended",
  token_created: "API token created",
  token_revoked: "API token revoked",
  backup_downloaded: "Backup downloaded",
  export_downloaded: "Export downloaded",
  restore_started: "Restore started",
  restore_finished: "Restore finished",
  secrets_cleared: "Secrets cleared",
};

const SCOPE_WARNING: Record<TokenScope, string | null> = {
  read: "A read token can see every item, its value, and where it is kept. Anyone holding it can too.",
  write:
    "A write token can see and change every item, its value, and where it is kept, including " +
    "adding and editing pieces. Anyone holding it can too.",
  metrics: null,
};

function PasswordSection() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setNote(null);
    if (next !== confirm) {
      setError("New password and confirmation don't match.");
      return;
    }
    setBusy(true);
    try {
      const result = await api.changePassword({ current_password: current, new_password: next });
      const revoked = result.revoked_tokens;
      const list = revoked.length
        ? `Revoked: ${revoked.map((t) => `${t.name} (${t.scope})`).join(", ")}. Create new ` +
          "tokens for anything that still needs one."
        : "No API tokens were revoked.";
      setNote(`Password changed. Other sessions were signed out. ${list}`);
      setCurrent("");
      setNext("");
      setConfirm("");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <h3>Password</h3>
      <form
        onSubmit={submit}
        className="estimate-form"
        style={{ flexDirection: "column", alignItems: "stretch", maxWidth: "24rem" }}
      >
        <label className="field">
          Current password
          <input
            type="password"
            value={current}
            onChange={(e) => setCurrent(e.target.value)}
            autoComplete="current-password"
            required
          />
        </label>
        <label className="field">
          New password
          <input
            type="password"
            value={next}
            onChange={(e) => setNext(e.target.value)}
            autoComplete="new-password"
            minLength={12}
            maxLength={256}
            required
          />
        </label>
        <label className="field">
          Confirm new password
          <input
            type="password"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            autoComplete="new-password"
            required
          />
        </label>
        {error && <p className="error">{error}</p>}
        {note && <p className="muted">{note}</p>}
        <div className="estimate-form" style={{ marginTop: 0 }}>
          <button className="primary" type="submit" disabled={busy}>
            {busy ? "Changing…" : "Change password"}
          </button>
        </div>
      </form>
    </>
  );
}

function UsernameSection() {
  const [current, setCurrent] = useState("");
  const [username, setUsername] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setNote(null);
    setBusy(true);
    try {
      await api.changeUsername({ current_password: current, username: username.trim() });
      setNote("Username changed.");
      setCurrent("");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <h3>Username</h3>
      <form
        onSubmit={submit}
        className="estimate-form"
        style={{ flexDirection: "column", alignItems: "stretch", maxWidth: "24rem" }}
      >
        <label className="field">
          Current password
          <input
            type="password"
            value={current}
            onChange={(e) => setCurrent(e.target.value)}
            autoComplete="current-password"
            required
          />
        </label>
        <label className="field">
          New username
          <input
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="username"
            required
          />
        </label>
        {error && <p className="error">{error}</p>}
        {note && <p className="muted">{note}</p>}
        <div className="estimate-form" style={{ marginTop: 0 }}>
          <button className="primary" type="submit" disabled={busy || !username.trim()}>
            {busy ? "Changing…" : "Change username"}
          </button>
        </div>
      </form>
    </>
  );
}

function SessionsSection() {
  const [sessions, setSessions] = useState<AuthSession[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  function load() {
    api
      .listSessions()
      .then(setSessions)
      .catch((e: Error) => setError(e.message));
  }

  useEffect(load, []);

  async function end(id: string) {
    setBusy(true);
    setError(null);
    try {
      await api.endSession(id);
      load();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function endAll() {
    if (!window.confirm("Sign out everywhere? Every session and known device is forgotten.")) return;
    setBusy(true);
    setError(null);
    try {
      await api.endAllSessions();
      // This session is gone too: the next request would 401 and redirect
      // anyway, but a full page load leaves the app in no ambiguous state.
      window.location.href = "/login";
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }

  return (
    <>
      <h3>Sessions</h3>
      {error && <p className="error">{error}</p>}
      {!sessions ? (
        <p className="muted">Loading…</p>
      ) : (
        <table className="estimates">
          <thead>
            <tr>
              <th>Device</th>
              <th>Address</th>
              <th>Last used</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {sessions.map((s) => (
              <tr key={s.id}>
                <td>
                  {shortAgent(s.user_agent)}
                  {s.current && <span className="badge status-wishlist">this browser</span>}
                </td>
                <td className="muted">{s.address ?? "–"}</td>
                <td className="muted">{when(s.last_seen_at)}</td>
                <td className="provenance-toggle">
                  {!s.current && (
                    <button disabled={busy} onClick={() => end(s.id)}>
                      End
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <div className="estimate-form" style={{ marginTop: "0.5rem" }}>
        <button className="danger" disabled={busy} onClick={endAll}>
          Sign out everywhere
        </button>
      </div>
    </>
  );
}

function TokensSection() {
  const [tokens, setTokens] = useState<ApiToken[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [name, setName] = useState("");
  const [scope, setScope] = useState<TokenScope>("read");
  const [days, setDays] = useState<string>("1");
  const [created, setCreated] = useState<NewApiToken | null>(null);
  const [copied, setCopied] = useState(false);

  function load() {
    api
      .listTokens()
      .then(setTokens)
      .catch((e: Error) => setError(e.message));
  }

  useEffect(load, []);

  async function create(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const token = await api.createToken({
        name: name.trim(),
        scope,
        days: days === "never" ? null : Number(days),
      });
      setCreated(token);
      setCopied(false);
      setName("");
      load();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function revoke(id: string) {
    setBusy(true);
    setError(null);
    try {
      await api.revokeToken(id);
      if (created?.id === id) setCreated(null);
      load();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function copy() {
    if (!created) return;
    try {
      await navigator.clipboard.writeText(created.token);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }

  return (
    <>
      <h3>API tokens</h3>
      {error && <p className="error">{error}</p>}
      {created && (
        <div className="estimate-form" style={{ flexDirection: "column", alignItems: "stretch" }}>
          <p>
            <b>{created.name}</b> ({created.scope}): copy it now, it won't be shown again.
          </p>
          <div className="estimate-form" style={{ marginTop: 0 }}>
            <code style={{ wordBreak: "break-all" }}>{created.token}</code>
            <button type="button" onClick={copy}>
              {copied ? "Copied" : "Copy"}
            </button>
            <button type="button" className="link-button" onClick={() => setCreated(null)}>
              <CloseIcon />
            </button>
          </div>
        </div>
      )}
      {!tokens ? (
        <p className="muted">Loading…</p>
      ) : tokens.length === 0 ? (
        <p className="muted">No API tokens.</p>
      ) : (
        <table className="estimates">
          <thead>
            <tr>
              <th>Name</th>
              <th>Scope</th>
              <th>Created</th>
              <th>Last used</th>
              <th>Expires</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {tokens.map((t) => (
              <tr key={t.id}>
                <td>{t.name}</td>
                <td className="muted">{t.scope}</td>
                <td className="muted">{when(t.created_at)}</td>
                <td className="muted">{t.last_used_at ? when(t.last_used_at) : "never"}</td>
                <td className="muted">{t.expires_at ? when(t.expires_at) : "never"}</td>
                <td className="provenance-toggle">
                  <button disabled={busy} onClick={() => revoke(t.id)}>
                    Revoke
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <form
        onSubmit={create}
        className="estimate-form"
        style={{ marginTop: "0.6rem", flexDirection: "column", alignItems: "stretch", maxWidth: "24rem" }}
      >
        <label className="field">
          Name
          <input value={name} onChange={(e) => setName(e.target.value)} required />
        </label>
        <label className="field">
          Scope
          <select
            value={scope}
            onChange={(e) => {
              const next = e.target.value as TokenScope;
              setScope(next);
              if (next !== "metrics" && days === "never") setDays("1");
            }}
          >
            <option value="read">Read</option>
            <option value="write">Write</option>
            <option value="metrics">Metrics</option>
          </select>
        </label>
        {SCOPE_WARNING[scope] && <p className="error" style={{ margin: 0 }}>{SCOPE_WARNING[scope]}</p>}
        <label className="field">
          Lifetime
          <select value={days} onChange={(e) => setDays(e.target.value)}>
            <option value="1">1 day</option>
            <option value="7">7 days</option>
            {scope === "metrics" && <option value="never">Never expires</option>}
          </select>
        </label>
        <div className="estimate-form" style={{ marginTop: 0 }}>
          <button className="primary" type="submit" disabled={busy || !name.trim()}>
            Create token
          </button>
        </div>
      </form>
    </>
  );
}

function detailText(entry: AuditEntry): string | null {
  if (!entry.detail || Object.keys(entry.detail).length === 0) return null;
  try {
    return Object.entries(entry.detail)
      .map(([k, v]) => `${k}: ${typeof v === "string" ? v : JSON.stringify(v)}`)
      .join(", ");
  } catch {
    return null;
  }
}

function AuditSection() {
  const [rows, setRows] = useState<AuditEntry[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);

  function loadMore(before?: number) {
    setBusy(true);
    setError(null);
    api
      .auditLog({ before, limit: 50 })
      .then((page) => {
        setRows((r) => (before ? [...r, ...page] : page));
        if (page.length < 50) setDone(true);
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setBusy(false));
  }

  useEffect(() => loadMore(), []);

  return (
    <>
      <h3>Audit log</h3>
      {error && <p className="error">{error}</p>}
      {rows.length === 0 && !busy ? (
        <p className="muted">Nothing recorded yet.</p>
      ) : (
        <table className="estimates">
          <thead>
            <tr>
              <th>When</th>
              <th>Event</th>
              <th>Who</th>
              <th>Address</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <td className="muted">{when(r.at)}</td>
                <td>
                  {AUDIT_LABELS[r.action] ?? r.action}
                  {detailText(r) && <span className="muted"> ({detailText(r)})</span>}
                </td>
                <td className="muted">
                  {r.actor_label} ({r.actor_kind})
                </td>
                <td className="muted">{r.address ?? "–"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {!done && (
        <button
          disabled={busy}
          style={{ marginTop: "0.5rem" }}
          onClick={() => loadMore(rows[rows.length - 1]?.id)}
        >
          {busy ? "Loading…" : "Older"}
        </button>
      )}
    </>
  );
}

/** Settings → Account: password, username, sessions, API tokens, and the
 * audit log (SPEC_0300 section 6, "Looking after the one account"). Each
 * section fetches its own data; nothing here depends on the rest of the
 * Settings page. */
export default function AccountCard() {
  return (
    <div className="card" id="account">
      <h2>Account</h2>
      <PasswordSection />
      <UsernameSection />
      <SessionsSection />
      <TokensSection />
      <AuditSection />
    </div>
  );
}
