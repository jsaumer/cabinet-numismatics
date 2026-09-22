import { FormEvent, useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { api, ApiError } from "../api";
import { useAuth } from "../auth/AuthContext";
import { AuthBrand } from "../auth/Brand";
import { storeFailedNotice } from "../auth/failedNotice";

/** Only a same-app relative path is honoured for `next`: never an absolute
 * URL (a sign-in page is exactly where an open redirect would matter). */
function safeNext(raw: string | null): string {
  if (!raw) return "/";
  if (!raw.startsWith("/") || raw.startsWith("//")) return "/";
  try {
    // A relative path parses against any base; reject one that resolves to
    // a different origin (e.g. "/\\evil.example" some browsers treat as //).
    const url = new URL(raw, window.location.origin);
    if (url.origin !== window.location.origin) return "/";
    return url.pathname + url.search + url.hash;
  } catch {
    return "/";
  }
}

export default function Login() {
  const { refresh } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const next = safeNext(params.get("next"));

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [retryAfter, setRetryAfter] = useState<number | null>(null);
  const [busyStatus, setBusyStatus] = useState(false);

  useEffect(() => {
    if (retryAfter == null || retryAfter <= 0) return;
    const timer = window.setTimeout(() => setRetryAfter((s) => (s == null ? null : s - 1)), 1000);
    return () => window.clearTimeout(timer);
  }, [retryAfter]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusyStatus(false);
    setBusy(true);
    try {
      const result = await api.login({ username: username.trim(), password });
      if (result.failed_since_previous > 0 && result.previous_sign_in_at) {
        storeFailedNotice({
          count: result.failed_since_previous,
          since: result.previous_sign_in_at,
        });
      }
      await refresh();
      navigate(next, { replace: true });
    } catch (err) {
      const e = err as ApiError;
      if (e.status === 429) {
        setRetryAfter(e.retryAfter ?? null);
      } else if (e.status === 503) {
        setBusyStatus(true);
        setRetryAfter(e.retryAfter ?? null);
      }
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  const waiting = retryAfter != null && retryAfter > 0;

  return (
    <div className="auth-page">
      <AuthBrand />
      <div className="card auth-card">
        <h1>Sign in</h1>
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
            Username
            <input
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
              required
              autoFocus
            />
          </label>
          <label className="field">
            Password
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              required
            />
          </label>
          {error && (
            <p className="error">
              {busyStatus
                ? "Cabinet is busy right now (a restore may be running). Try again shortly."
                : error}
              {waiting && !busyStatus && ` Try again in ${retryAfter} second${retryAfter === 1 ? "" : "s"}.`}
            </p>
          )}
          <button className="primary" type="submit" disabled={busy || waiting}>
            {busy ? "Signing in…" : "Sign in"}
          </button>
        </form>
      </div>
    </div>
  );
}
