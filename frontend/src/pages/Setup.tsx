import { FormEvent, useEffect, useState } from "react";

import { api, ApiError } from "../api";
import { useAuth } from "../auth/AuthContext";
import { AuthBrand } from "../auth/Brand";

/** The setup page: the first person to present the setup code becomes the
 * admin (docs/specs/SPEC_0300.md section 6). Shown instead of the app for as
 * long as the instance is unclaimed. */
export default function Setup() {
  const { refresh } = useAuth();
  const [code, setCode] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [retryAfter, setRetryAfter] = useState<number | null>(null);

  useEffect(() => {
    if (retryAfter == null || retryAfter <= 0) return;
    const timer = window.setTimeout(() => setRetryAfter((s) => (s == null ? null : s - 1)), 1000);
    return () => window.clearTimeout(timer);
  }, [retryAfter]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (password !== confirm) {
      setError("Password and confirmation don't match.");
      return;
    }
    setBusy(true);
    try {
      await api.setup({ code: code.trim(), username: username.trim(), password });
      await refresh();
    } catch (err) {
      const e = err as ApiError;
      setError(e.message);
      setRetryAfter(e.retryAfter ?? null);
    } finally {
      setBusy(false);
    }
  }

  const waiting = retryAfter != null && retryAfter > 0;

  return (
    <div className="auth-page">
      <AuthBrand />
      <div className="card auth-card">
        <h1>Set up Cabinet</h1>
        <p className="muted">
          Nobody has claimed this Cabinet yet. Enter the setup code to become the admin; it
          works once, then the setup page closes for good. The code is in the backend's log
          (<code>docker compose logs backend</code>), or whatever <code>SETUP_CODE</code> or{" "}
          <code>SETUP_CODE_FILE</code> was set to.
        </p>
        {!window.isSecureContext && (
          <p className="error">
            This page isn't a secure connection (plain http). Your password would travel
            unencrypted. Use https, or connect over localhost.
          </p>
        )}
        <form
          onSubmit={submit}
          className="estimate-form"
          style={{ flexDirection: "column", alignItems: "stretch" }}
        >
          <label className="field">
            Setup code
            <input
              value={code}
              onChange={(e) => setCode(e.target.value)}
              autoComplete="off"
              spellCheck={false}
              required
            />
          </label>
          <label className="field">
            Username
            <input
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
              required
            />
          </label>
          <label className="field">
            Password
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="new-password"
              minLength={12}
              maxLength={256}
              required
            />
          </label>
          <label className="field">
            Confirm password
            <input
              type="password"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              autoComplete="new-password"
              required
            />
          </label>
          <p className="muted" style={{ margin: 0 }}>
            12 to 256 characters, no other rules.
          </p>
          {error && (
            <p className="error">
              {error}
              {waiting && ` Try again in ${retryAfter}s.`}
            </p>
          )}
          <button className="primary" type="submit" disabled={busy || waiting}>
            {busy ? "Setting up…" : "Create the admin account"}
          </button>
        </form>
      </div>
    </div>
  );
}
