import { MouseEvent, ReactNode } from "react";

import { api } from "../api";
import { requestConfirm } from "./ConfirmDialog";

// A plain download link to a "fresh" route (both exports, backup.zip with
// and without photos, a stored backup): SPEC_0300 section 5 wants the
// password confirmed within the last 5 minutes before these, and asking only
// once the answer is genuinely needed reads better than confirming on every
// click. client.ts's req() already retries a JSON call that meets a 403
// reauth_required; a plain <a href> download can't be retried the same way
// (the browser, not fetch, does the navigation), so this checks
// GET /api/auth/me's confirmed_until first and opens the same dialog only
// when it's not comfortably in the future.

const FRESH_MARGIN_MS = 30_000;

/** Confirms the password first when the recent-password window has lapsed;
 * a no-op otherwise. Exported for anything that navigates to a "fresh"
 * route by a plain link rather than a JSON call: FreshLink itself, and
 * Settings -> Sign-in's "Link {provider}" links, which need a fresh session
 * before GET /api/auth/oidc/start?intent=link will accept them. */
export async function ensureFresh(): Promise<void> {
  const me = await api.me();
  const until = me.confirmed_until ? new Date(me.confirmed_until).getTime() : 0;
  if (until - Date.now() > FRESH_MARGIN_MS) return;
  await requestConfirm();
}

/** Looks and behaves like a plain download link (real href, real download
 * attribute, so "Save link as…" and Playwright's download handling both
 * work), but confirms the password first when the window has lapsed. */
export function FreshLink({
  href,
  download,
  className,
  title,
  role,
  children,
}: {
  href: string;
  download?: boolean | string;
  className?: string;
  title?: string;
  role?: string;
  children: ReactNode;
}) {
  async function onClick(e: MouseEvent<HTMLAnchorElement>) {
    // A modified click (open in new tab, etc.) is left to the browser.
    if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    e.preventDefault();
    try {
      await ensureFresh();
    } catch {
      return; // cancelled, or confirmation itself failed: nothing to download
    }
    const a = document.createElement("a");
    a.href = href;
    if (download !== undefined) a.download = typeof download === "string" ? download : "";
    document.body.appendChild(a);
    a.click();
    a.remove();
  }

  return (
    <a className={className} href={href} download={download} title={title} role={role} onClick={onClick}>
      {children}
    </a>
  );
}
