// Carries "N failed sign-ins since your last visit" from the sign-in page to
// the app shell across the navigation that follows a successful sign-in.
// sessionStorage is fine here: it's a per-viewer reading convenience, not
// collection data, and it doesn't need to survive past this tab.

const KEY = "cabinet.auth.failedNotice";

export interface FailedNotice {
  count: number;
  since: string; // previous_sign_in_at
}

export function storeFailedNotice(notice: FailedNotice) {
  try {
    sessionStorage.setItem(KEY, JSON.stringify(notice));
  } catch {
    /* private mode: the notice just won't show */
  }
}

/** Reads the notice, if any, and clears it: it shows once, right after the
 * sign-in that produced it, not again on a later reload. */
export function takeFailedNotice(): FailedNotice | null {
  try {
    const raw = sessionStorage.getItem(KEY);
    if (!raw) return null;
    sessionStorage.removeItem(KEY);
    return JSON.parse(raw) as FailedNotice;
  } catch {
    return null;
  }
}
