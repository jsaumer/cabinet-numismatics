import { createContext, ReactNode, useCallback, useContext, useEffect, useState } from "react";

import { api, ApiError, AuthState, Me, setUnauthorizedHandler } from "../api";
import { storeFailedNotice } from "./failedNotice";

export type AuthStatus = "loading" | "restoring" | "setup" | "anon" | "authed";

interface AuthContextValue {
  status: AuthStatus;
  me: Me | null;
  /** The sign-in page's buttons (password, providers, trusted header): set
   * once the boot check's GET /api/auth/state answers, null before that and
   * while signed in (the sign-in page is the only reader). */
  methods: AuthState["methods"] | null;
  /** Re-runs the boot check: after setup, after a successful sign-in, and
   * after anything that could change confirmed_until. */
  refresh: () => Promise<void>;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth() must be used inside <AuthProvider>.");
  return value;
}

const RESTORE_RETRY_MS = 5000;

/** The app's boot sequence (docs/specs/SPEC_0300.md, "Frontend boot"):
 * GET /api/auth/state, then GET /api/auth/me. setup_required shows /setup; a
 * 503 (a restore is running) retries every 5 seconds; a 401 from /me shows
 * /login. Everything else renders once signed in. */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>("loading");
  const [me, setMe] = useState<Me | null>(null);
  const [methods, setMethods] = useState<AuthState["methods"] | null>(null);

  const check = useCallback(async () => {
    let state: AuthState;
    try {
      state = await api.authState();
      if (state.setup_required) {
        setMe(null);
        setMethods(null);
        setStatus("setup");
        return;
      }
    } catch (e) {
      if (e instanceof ApiError && e.status === 503) {
        setStatus("restoring");
        return;
      }
      // A dropped connection or a restarting proxy: treat it the same as a
      // restore in progress and try again shortly.
      setStatus("restoring");
      return;
    }
    try {
      const who = await api.me({ raw: true });
      setMe(who);
      setMethods(null);
      setStatus("authed");
      // A single sign-on hands the failed-sign-ins notice over once here
      // (R2-10): a password sign-in already stores it from LoginResult in
      // pages/Login.tsx, so this only fires for oidc/trusted_header.
      if (who.failed_since_previous != null && who.failed_since_previous > 0 && who.previous_sign_in_at) {
        storeFailedNotice({ count: who.failed_since_previous, since: who.previous_sign_in_at });
      }
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        setMe(null);
        setMethods(state.methods);
        setStatus("anon");
        return;
      }
      throw e;
    }
  }, []);

  useEffect(() => {
    check();
  }, [check]);

  useEffect(() => {
    if (status !== "restoring") return;
    const timer = window.setTimeout(check, RESTORE_RETRY_MS);
    return () => window.clearTimeout(timer);
  }, [status, check]);

  // A 401 anywhere else in the app (the session died mid-visit): a full page
  // load to /login, so every in-memory cache goes with it.
  useEffect(() => {
    setUnauthorizedHandler((path) => {
      const next = path && path !== "/login" ? `?next=${encodeURIComponent(path)}` : "";
      window.location.href = `/login${next}`;
    });
    return () => setUnauthorizedHandler(null);
  }, []);

  const signOut = useCallback(async () => {
    let redirect = "/login";
    try {
      const result = await api.logout();
      if (result?.redirect) redirect = result.redirect;
    } catch {
      // Sign out locally regardless: the cookie may already be gone.
    }
    window.location.href = redirect;
  }, []);

  return (
    <AuthContext.Provider value={{ status, me, methods, refresh: check, signOut }}>
      {children}
    </AuthContext.Provider>
  );
}
