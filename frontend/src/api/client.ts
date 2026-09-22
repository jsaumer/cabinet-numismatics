// fetch wrapper: JSON in and out, FastAPI error details as Error messages.
//
// This is also the one place that reacts to a session dying or needing a
// fresh password (docs/specs/SPEC_0300.md section 5): a 401 sends the
// browser to /login, and a 403 with reauth_required opens the confirm-
// password dialog and retries the request once it's answered. Both hooks
// are set once, at runtime, by ../auth/AuthContext.tsx and
// ../auth/ConfirmDialog.tsx; client.ts never imports from ../auth so the
// two sides can't import each other in a circle. See frontend/README.md.

export class ApiError extends Error {
  status: number;
  retryAfter: number | null;

  constructor(message: string, status: number, retryAfter: number | null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.retryAfter = retryAfter;
  }
}

type UnauthorizedHandler = (path: string) => void;
type ReauthHandler = () => Promise<void>;

let onUnauthorized: UnauthorizedHandler | null = null;
let onReauthRequired: ReauthHandler | null = null;

/** Set once by AuthProvider: where a 401 outside the auth pages sends the
 * browser (a full page load, so every in-memory cache is gone with it). */
export function setUnauthorizedHandler(fn: UnauthorizedHandler | null) {
  onUnauthorized = fn;
}

/** Set once by the confirm-password dialog: opens it, resolves once the
 * password is confirmed, rejects if the visitor cancels. */
export function setReauthHandler(fn: ReauthHandler | null) {
  onReauthRequired = fn;
}

async function readError(resp: Response): Promise<{ message: string; reauth: boolean }> {
  let detail: string | undefined;
  let reauth = false;
  try {
    const body = await resp.json();
    if (typeof body.detail === "string") {
      detail = body.detail;
      reauth = body.reauth_required === true;
    } else if (Array.isArray(body.detail)) {
      // FastAPI validation errors: [{loc: ["body", "field", ...], msg}, …]
      detail = body.detail
        .map((e: { loc?: (string | number)[]; msg?: string }) => {
          const field = (e.loc ?? []).filter((p) => p !== "body").join(".");
          return field ? `${field}: ${e.msg}` : e.msg;
        })
        .join("; ");
    }
  } catch {
    /* non-JSON error body */
  }
  return { message: detail || `HTTP ${resp.status}`, reauth };
}

export interface ReqOptions {
  /** Skip the global 401 redirect and the 403 reauth retry: for the setup
   * and sign-in forms and the auth boot check, which answer those statuses
   * themselves (a wrong password is not "signed out"). */
  raw?: boolean;
  /** Set on the one retry after a confirmation, so a second reauth_required
   * is an error rather than another dialog. */
  retried?: boolean;
}

export async function req<T>(url: string, init?: RequestInit, opts?: ReqOptions): Promise<T> {
  const resp = await fetch(url, init);
  if (resp.ok) {
    if (resp.status === 204) return undefined as T;
    return resp.json() as Promise<T>;
  }

  const retryAfterHeader = resp.headers.get("Retry-After");
  const retryAfter = retryAfterHeader ? Number(retryAfterHeader) : null;

  if (resp.status === 401 && !opts?.raw && onUnauthorized) {
    onUnauthorized(location.pathname + location.search);
    // The browser is on its way to /login; don't surface an error a page
    // has no time left to show.
    return new Promise<T>(() => {});
  }

  const { message, reauth } = await readError(resp);

  if (resp.status === 403 && reauth && !opts?.raw && !opts?.retried && onReauthRequired) {
    await onReauthRequired(); // throws "Confirmation cancelled." if the visitor cancels
    // Retried once, now inside the confirmed window; never a second dialog.
    return req<T>(url, init, { ...opts, retried: true });
  }

  throw new ApiError(message, resp.status, retryAfter);
}

export const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});
