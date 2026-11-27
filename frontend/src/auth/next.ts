/** Only a same-app relative path is honoured for `next`: never an absolute
 * URL (a sign-in page is exactly where an open redirect would matter). */
export function safeNext(raw: string | null): string {
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
