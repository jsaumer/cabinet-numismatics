import { useEffect, useState } from "react";

import { api, Health } from "../../api";
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

/** Settings → About: the version, the two migration chains, and document
 * storage. */
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
    </Section>
  );
}
