import { FormEvent, ReactElement, useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { api, ApiError } from "../api";
import { useAuth } from "../auth/AuthContext";
import { AuthBrand } from "../auth/Brand";
import { storeFailedNotice } from "../auth/failedNotice";
import { ssoErrorMessage } from "../auth/ssoErrors";
import { safeNext } from "../auth/next";
import { GitHubIcon, GoogleIcon, KeyIcon, MicrosoftIcon } from "../components/icons";
import { useTitle } from "../components/title";

const PRESET_ICON: Record<string, () => ReactElement> = {
  google: GoogleIcon,
  microsoft: MicrosoftIcon,
  github: GitHubIcon,
  custom: KeyIcon,
};

/** The server accepted the sign-in and the very next request arrived signed
 * out: the browser didn't keep the cookie. Over plain http that is a cookie
 * marked for https only (AUTH_INSECURE_HTTP isn't true), which a browser
 * drops without a word; the page used to show the empty form again. */
function cookieNotKept(): string {
  const start = "Cabinet accepted that, but your browser didn't keep the sign-in cookie, so you are still signed out. ";
  return window.isSecureContext
    ? start + "Check that the browser accepts cookies from this address."
    : start +
        "This address is plain http, and Cabinet is sending cookies meant for https only: set " +
        "AUTH_INSECURE_HTTP=true and start Cabinet again, or open it over https.";
}

export default function Login() {
  useTitle("Sign in");
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
      if ((await refresh()) === "anon") {
        setError(cookieNotKept());
        return;
      }
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
      if ((await refresh()) === "anon") {
        setError(cookieNotKept());
        return;
      }
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
              {/* The countdown stays outside the alert, or every second
                  would be read out. */}
              <span role="alert">
                {busyStatus
                  ? "Cabinet is busy right now (a restore may be running). Try again shortly."
                  : error}
              </span>
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
