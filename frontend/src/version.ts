/** The release the web interface was built from. The backend reports its
 * own in /api/health; the two differ when the proxy image and the backend
 * image are on different tags, or when this tab was opened before an
 * upgrade and is still running the old page. */
export const BUILD_VERSION: string = __CABINET_VERSION__;

/** Whether the server is a different release than this page. An empty or
 * missing server version (health answered without one) is not a mismatch. */
export function versionsDiffer(server: string | null | undefined): boolean {
  return Boolean(server) && server !== BUILD_VERSION;
}
