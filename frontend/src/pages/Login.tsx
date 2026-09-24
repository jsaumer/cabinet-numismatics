import { FormEvent, ReactElement, useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { api, ApiError } from "../api";
import { useAuth } from "../auth/AuthContext";
import { AuthBrand } from "../auth/Brand";
import { storeFailedNotice } from "../auth/failedNotice";
import { ssoErrorMessage } from "../auth/ssoErrors";
import { GitHubIcon, GoogleIcon, KeyIcon, MicrosoftIcon } from "../components/icons";

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

const PRESET_ICON: Record<string, () => ReactElement> = {
  google: GoogleIcon,
  microsoft: MicrosoftIcon,
  github: GitHubIcon,
  custom: KeyIcon,
};

export default function Login() {
  const { refresh, methods } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const next = safeNext(params.get("next"));
  const flowError = params.get("error");

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(flowError ? ssoErrorMessage(flowError) : null);
  const [busy, setBusy] = useState(false);
  const [retryAfter, setRetryAfter] = useState<number | null>(null);
  const [busyStatus, setBusyStatus] = useState(false);
  const [trustedBusy, setTrustedBusy] = useState(false);

  useEffect(() => {
    if (retryAfter == null || retryAfter <= 0) return;
    const timer = window.setTimeout(() => setRetryAfter((s) => (s == null ? null : s - 1)), 1000);
    return () => window.clearTimeout(timer);
  }, [retryAfter]);

  // Shown once: strip ?error= from the address bar so a reload doesn't
  // repeat a stale failure.
  useEffect(() => {
    if (!flowError) return;
    const stripped = new URLSearchParams(params);
    stripped.delete("error");
    navigate({ search: stripped.toString() }, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function trustedSignIn() {
    setError(null);
    setBusyStatus(false);
    setTrustedBusy(true);
    try {
      await api.trustedSignIn();
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
      setTrustedBusy(false);
    }
  }

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
  const providers = methods?.providers ?? [];
  const trustedHeader = methods?.trusted_header;

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
        {(providers.length > 0 || trustedHeader) && (
          <div
            className="estimate-form"
            style={{ flexDirection: "column", alignItems: "stretch", marginTop: 0 }}
          >
            {providers.map((p) => {
              const ProviderIcon = PRESET_ICON[p.preset] ?? KeyIcon;
              return (
                <a
                  key={p.id}
                  className="button provider-button"
                  href={api.oidcStartUrl(p.id, next)}
                >
                  <ProviderIcon />
                  {`Sign in with ${p.name}`}
                </a>
              );
            })}
            {trustedHeader && (
              <button type="button" onClick={trustedSignIn} disabled={trustedBusy || waiting}>
                {trustedBusy ? "Signing in…" : "Continue with the proxy's sign-in"}
              </button>
            )}
            <p className="muted" style={{ margin: "0.4rem 0 0" }}>
              Or sign in with the password:
            </p>
          </div>
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
