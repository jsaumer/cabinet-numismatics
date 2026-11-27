import { useEffect, useState } from "react";

import { api, Health } from "../../api";
import { BUILD_VERSION, versionsDiffer } from "../../version";
import { Section } from "./shared";

function schemaLabel({ current, expected, status }: Health["schema"]): string {
  if (status === "ok") return `${current} (up to date)`;
  if (status === "pending") return `${current ?? "empty"} (migration pending, expects ${expected})`;
  if (status === "ahead") return `${current} (newer than this build, which expects ${expected})`;
  return "unknown (database unreachable)";
}

const DOCUMENT_STORAGE: Record<string, string> = {
  ok: "ready",
  not_mounted:
    "not a mounted volume, so uploads are refused and documents can't be lost with the container " +
    "(see docs/deployment.md)",
  unwritable: "not writable, so uploads are refused",
  inside_photos: "inside the public photo folder, so uploads are refused",
};

/** Settings → About: the server's version and the web interface's own, the
 * two migration chains, and document storage. */
export default function AboutSection() {
  const [health, setHealth] = useState<Health | null>(null);

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth(null));
  }, []);

  return (
    <Section title="About">
      {health === null ? (
        <p className="muted">Version information unavailable.</p>
      ) : (
        <dl className="facts">
          <div>
            <dt>Version</dt>
            <dd>
              <a
                href={`https://github.com/jsaumer/cabinet-numismatics/releases/tag/v${health.version}`}
                target="_blank"
                rel="noreferrer"
              >
                {health.version}
              </a>
            </dd>
          </div>
          <div>
            <dt>Web interface</dt>
            <dd className={versionsDiffer(health.version) ? "error" : undefined}>
              {BUILD_VERSION}
              {versionsDiffer(health.version) && ` (the server is ${health.version})`}
            </dd>
          </div>
          <div>
            <dt>Database schema</dt>
            <dd
              className={
                health.schema.status === "ok"
                  ? undefined
                  : health.schema.status === "unknown"
                    ? "muted"
                    : "error"
              }
            >
              {schemaLabel(health.schema)}
            </dd>
          </div>
          {health.auth_schema && (
            <div>
              <dt>Sign-in schema</dt>
              <dd
                className={
                  health.auth_schema.status === "ok"
                    ? undefined
                    : health.auth_schema.status === "unknown"
                      ? "muted"
                      : "error"
                }
              >
                {schemaLabel(health.auth_schema)}
              </dd>
            </div>
          )}
          <div>
            <dt>Document storage</dt>
            <dd className={health.documents === "ok" ? undefined : "error"}>
              {DOCUMENT_STORAGE[health.documents] ?? health.documents}
            </dd>
          </div>
        </dl>
      )}
      {health !== null && versionsDiffer(health.version) && (
        <p className="error">
          The web interface and the server are different releases. Reload this page first: a tab
          opened before an upgrade keeps running the old one. If the two still differ, the proxy
          image and the backend image are on different tags; set both to the same version and
          start the stack again.
        </p>
      )}
      <p className="muted">
        Cabinet is free software under the MIT license. It is not affiliated with or endorsed by
        Numista, PCGS, NGC, or PMG; their names say only where a value or a lookup comes from.
      </p>
    </Section>
  );
}
