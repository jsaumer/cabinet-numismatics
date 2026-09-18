import { useState } from "react";

import { AlertFormat, api, AppSettings, AppSettingsUpdate, MonitorOutcome } from "../api";

const FORMATS: { value: AlertFormat; label: string; hint: string }[] = [
  {
    value: "generic",
    label: "Generic JSON",
    hint:
      "POSTs JSON with app, alert, label, status (failing, recovered, or test), title, " +
      "message, and at — for n8n, Home Assistant, Node-RED, or anything that takes a webhook.",
  },
  {
    value: "ntfy",
    label: "ntfy",
    hint: "The topic URL, e.g. https://ntfy.sh/your-topic. A protected topic takes ?auth=… in the URL.",
  },
  {
    value: "discord",
    label: "Discord",
    hint: "A channel webhook URL (channel settings → Integrations → Webhooks).",
  },
  {
    value: "slack",
    label: "Slack / Mattermost",
    hint: "An incoming-webhook URL; Mattermost's incoming webhooks take the same message.",
  },
  {
    value: "gotify",
    label: "Gotify",
    hint: "https://gotify.example/message?token=<application token>.",
  },
];

const SOURCE_LABELS: Record<string, string> = { melt: "Melt", numista: "Numista", pcgs: "PCGS" };

const when = (iso: string) => new Date(iso).toLocaleString();

function Result({ outcome }: { outcome: MonitorOutcome | null }) {
  if (!outcome) return null;
  return (
    <p className={outcome.ok ? "gain" : "error"} style={{ margin: "0.3rem 0 0" }}>
      {outcome.ok ? "✓" : "✗"} {outcome.detail} ({when(outcome.at)})
    </p>
  );
}

/** Settings → Alerts & metrics: the webhook, the Uptime Kuma heartbeat,
 * what's failing now, the last scheduled refreshes, and /api/metrics. */
export function AlertsCard({
  settings,
  saving,
  apply,
}: {
  settings: AppSettings;
  saving: boolean;
  apply: (payload: AppSettingsUpdate, message: string) => Promise<boolean>;
}) {
  const [hookUrl, setHookUrl] = useState("");
  const [beatUrl, setBeatUrl] = useState("");
  const [testing, setTesting] = useState<string | null>(null);
  const [results, setResults] = useState<Record<string, MonitorOutcome | null>>({});

  async function test(target: "webhook" | "heartbeat") {
    setTesting(target);
    try {
      const outcome = await api.testAlert(target);
      setResults((r) => ({ ...r, [target]: outcome }));
    } catch (e) {
      setResults((r) => ({
        ...r,
        [target]: { at: new Date().toISOString(), ok: false, detail: (e as Error).message },
      }));
    } finally {
      setTesting(null);
    }
  }

  const format = FORMATS.find((f) => f.value === settings.alert_webhook_format) ?? FORMATS[0];
  const refreshes = Object.entries(settings.refresh_last_run);

  return (
    <div className="card">
      <h2>Alerts &amp; metrics</h2>
      <p className="muted" style={{ marginTop: 0 }}>
        Cabinet sends an alert when a backup fails, a price source rejects its key or runs out
        of quota, or a scheduled refresh has failures — once when it starts, and once when it's
        working again. Saved URLs often carry a token, so they're encrypted like the API keys
        and only their host is shown.
      </p>

      <h3>Webhook</h3>
      <div className="estimate-form" style={{ marginTop: 0 }}>
        <label className="field">
          Format
          <select
            value={settings.alert_webhook_format}
            disabled={saving}
            onChange={(e) => {
              const picked = FORMATS.find((f) => f.value === e.target.value)!;
              apply({ alert_webhook_format: picked.value }, `Alerts are sent as ${picked.label}.`);
            }}
          >
            {FORMATS.map((f) => (
              <option key={f.value} value={f.value}>{f.label}</option>
            ))}
          </select>
        </label>
        <label className="field" style={{ flex: "1 1 16rem" }}>
          URL
          {settings.alert_webhook_hint
            ? ` (saved ${settings.alert_webhook_hint})`
            : " (not configured)"}
          <input
            type="password"
            autoComplete="off"
            placeholder={settings.alert_webhook_hint ? "replace…" : "paste webhook URL…"}
            value={hookUrl}
            onChange={(e) => setHookUrl(e.target.value)}
          />
        </label>
        <button
          disabled={saving || !hookUrl.trim()}
          onClick={() => {
            apply({ alert_webhook_url: hookUrl.trim() }, "Webhook saved.").then(
              (ok) => ok && setHookUrl(""),
            );
          }}
        >
          Save
        </button>
        {settings.alert_webhook_hint && (
          <>
            <button disabled={testing !== null} onClick={() => test("webhook")}>
              {testing === "webhook" ? "Sending…" : "Send test"}
            </button>
            <button
              disabled={saving}
              onClick={() => apply({ alert_webhook_url: "" }, "Webhook removed.")}
            >
              Remove
            </button>
          </>
        )}
      </div>
      <p className="muted" style={{ margin: "0.3rem 0 0" }}>{format.hint}</p>
      <Result outcome={results.webhook ?? settings.alert_delivery} />

      <h3>Heartbeat</h3>
      <p className="muted" style={{ marginTop: 0 }}>
        An Uptime Kuma <b>Push</b> monitor catches what an alert can't: Cabinet not running at
        all. Every hour Cabinet pushes <code>up</code>, or <code>down</code> with what's failing.
        Give the monitor a heartbeat interval of at least 65 minutes.
      </p>
      <div className="estimate-form" style={{ marginTop: 0 }}>
        <label className="field" style={{ flex: "1 1 16rem" }}>
          Push URL
          {settings.heartbeat_hint ? ` (saved ${settings.heartbeat_hint})` : " (not configured)"}
          <input
            type="password"
            autoComplete="off"
            placeholder={settings.heartbeat_hint ? "replace…" : "paste push URL…"}
            value={beatUrl}
            onChange={(e) => setBeatUrl(e.target.value)}
          />
        </label>
        <button
          disabled={saving || !beatUrl.trim()}
          onClick={() => {
            apply({ heartbeat_url: beatUrl.trim() }, "Heartbeat URL saved.").then(
              (ok) => ok && setBeatUrl(""),
            );
          }}
        >
          Save
        </button>
        {settings.heartbeat_hint && (
          <>
            <button disabled={testing !== null} onClick={() => test("heartbeat")}>
              {testing === "heartbeat" ? "Pushing…" : "Push now"}
            </button>
            <button
              disabled={saving}
              onClick={() => apply({ heartbeat_url: "" }, "Heartbeat URL removed.")}
            >
              Remove
            </button>
          </>
        )}
      </div>
      <Result outcome={results.heartbeat ?? settings.heartbeat} />

      <h3>Status</h3>
      {settings.alerts.length === 0 ? (
        <p className="muted" style={{ marginTop: 0 }}>Nothing has failed.</p>
      ) : (
        <table className="estimates">
          <thead>
            <tr><th>Check</th><th>State</th><th>Since</th><th>Detail</th></tr>
          </thead>
          <tbody>
            {settings.alerts.map((a) => (
              <tr key={a.key}>
                <td>{a.label}</td>
                <td className={a.failing ? "loss" : "gain"}>{a.failing ? "failing" : "recovered"}</td>
                <td className="muted">{a.since ? when(a.since) : "—"}</td>
                <td className="muted">{a.failing ? a.message : a.message && `was: ${a.message}`}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {refreshes.length > 0 && (
        <table className="estimates" style={{ marginTop: "0.6rem" }}>
          <thead>
            <tr><th>Scheduled refresh</th><th>Last run</th><th>Updated</th><th>Skipped</th><th>Failed</th></tr>
          </thead>
          <tbody>
            {refreshes.map(([source, run]) => (
              <tr key={source}>
                <td>{SOURCE_LABELS[source] ?? source}</td>
                <td className="muted">{when(run.at)}</td>
                <td>{run.updated}</td>
                <td>{run.skipped}</td>
                <td className={run.failed ? "loss" : undefined}>
                  {run.failed}
                  {(run.stopped || run.error) && (
                    <div className="muted sale-title">
                      {run.stopped ? `stopped: ${run.stopped}` : run.error}
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <h3>Prometheus metrics</h3>
      <label className="slot">
        <input
          type="checkbox"
          checked={settings.metrics_enabled}
          disabled={saving}
          onChange={(e) =>
            apply(
              { metrics_enabled: e.target.checked },
              e.target.checked ? "Metrics are served at /api/metrics." : "Metrics turned off.",
            )
          }
        />
        Serve metrics at <code>/api/metrics</code>
      </label>
      <p className="muted" style={{ margin: "0.3rem 0 0" }}>
        Item counts, collection value and cost basis, backup and refresh outcomes, and which
        alerts are failing, refreshed at most once a minute. Like the rest of the API it has no
        login, and it includes the collection's value — see docs/monitoring.md for the scrape
        config.
        {settings.metrics_enabled && (
          <>
            {" "}
            <a href="/api/metrics" target="_blank" rel="noreferrer">View them</a>.
          </>
        )}
      </p>
    </div>
  );
}
