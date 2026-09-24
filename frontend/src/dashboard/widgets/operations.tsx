import { Link } from "react-router-dom";

import { api, formatBytes } from "../../api";
import { optionNumber } from "../options";
import { useWidgetData, useWidgetEmpty, WidgetProps } from "../WidgetFrame";

const when = (iso: string) => new Date(iso).toLocaleString();

const SOURCE_LABELS: Record<string, string> = { melt: "Melt", numista: "Numista", pcgs: "PCGS" };

/** Whether the collection is being backed up, and when it last was. */
export function BackupStatusWidget() {
  const backups = useWidgetData("backups", () => api.listBackups());
  const settings = useWidgetData("settings", () => api.getSettings());
  if (!backups.data) return backups.pending;
  const list = backups.data;
  const schedule = settings.data?.backup_schedule;

  return (
    <>
      <dl className="facts">
        <div>
          <dt>Schedule</dt>
          <dd className={settings.data && !schedule ? "error" : undefined}>
            {schedule ? schedule : settings.data ? "off" : "–"}
          </dd>
        </div>
        <div>
          <dt>Archives kept</dt>
          <dd>{list.backups.length}</dd>
        </div>
        {list.free_bytes != null && (
          <div>
            <dt>Free space</dt>
            <dd>{formatBytes(list.free_bytes)}</dd>
          </div>
        )}
      </dl>
      {list.last_run ? (
        <p className={list.last_run.ok ? "muted" : "error"} style={{ marginBottom: 0 }}>
          Last run {when(list.last_run.at)}:{" "}
          {list.last_run.ok
            ? `${list.last_run.file} (${formatBytes(list.last_run.size ?? 0)})`
            : `failed: ${list.last_run.error}`}
        </p>
      ) : (
        <p className="muted" style={{ marginBottom: 0 }}>
          No backup has run yet. <Link to="/settings/backups">Back up now</Link>.
        </p>
      )}
    </>
  );
}

/** The account's doors, at a glance: how this session signed in, live
 * sessions and tokens, which sign-in methods are on, and whether sharing is.
 * Every request is one the Settings pages already make; nothing new is
 * exposed. */
export function SigninStatusWidget() {
  const me = useWidgetData("me", () => api.me());
  const sessions = useWidgetData("sessions", () => api.listSessions());
  const tokens = useWidgetData("tokens", () => api.listTokens());
  const config = useWidgetData("signin-config", () => api.signinConfig());
  const settings = useWidgetData("settings", () => api.getSettings());
  const links = useWidgetData("share-links", () => api.listShareLinks(), settings.data?.share_enabled === true);
  if (!me.data || !config.data) return me.data ? config.pending : me.pending;

  const who = me.data;
  const cfg = config.data;
  const enabledProviders = cfg.providers.filter((p) => p.enabled);
  const provider = cfg.providers.find((p) => p.id === who.provider_id);
  const method =
    who.auth_method === "oidc"
      ? (provider?.display_name ?? "a provider")
      : who.auth_method === "trusted_header"
        ? "the proxy's sign-in"
        : who.auth_method === "password"
          ? "the password"
          : "an API token";
  const headerMode = cfg.trusted_header.configured
    ? cfg.trusted_header.enabled
      ? "on"
      : "off"
    : null;
  const anyProvider = enabledProviders.length > 0 || cfg.trusted_header.enabled;
  const failing = cfg.providers.filter((p) => p.credentials_failing);
  const sharing = settings.data?.share_enabled;

  return (
    <>
      <dl className="facts">
        <div>
          <dt>Signed in with</dt>
          <dd>{method}</dd>
        </div>
        <div>
          <dt>Sessions</dt>
          <dd>{sessions.data ? sessions.data.length : "–"}</dd>
        </div>
        <div>
          <dt>API tokens</dt>
          <dd>{tokens.data ? tokens.data.length : "–"}</dd>
        </div>
        <div>
          <dt>Sign-in providers</dt>
          <dd className={failing.length ? "error" : undefined}>
            {enabledProviders.length
              ? enabledProviders.map((p) => p.display_name).join(", ")
              : cfg.providers.length
                ? "none on"
                : "none"}
            {failing.length ? ` (${failing.length} rejected)` : ""}
          </dd>
        </div>
        {headerMode && (
          <div>
            <dt>Proxy sign-in</dt>
            <dd>{headerMode}</dd>
          </div>
        )}
        <div>
          <dt>Linked identities</dt>
          <dd>{cfg.identities.length}</dd>
        </div>
        <div>
          <dt>Password sign-in alerts</dt>
          <dd className={anyProvider && !cfg.password_sign_in_alerts ? "error" : undefined}>
            {cfg.password_sign_in_alerts ? "on" : "off"}
          </dd>
        </div>
        <div>
          <dt>Sharing</dt>
          <dd>
            {sharing == null
              ? "–"
              : sharing
                ? `on${links.data ? `, ${links.data.length} link${links.data.length === 1 ? "" : "s"}` : ""}`
                : "off"}
          </dd>
        </div>
      </dl>
      <p className="muted" style={{ marginBottom: 0 }}>
        <Link to="/settings/signin">Sign-in settings</Link> · <Link to="/settings/account">Account</Link>
      </p>
    </>
  );
}

/** What is failing, and when the scheduled refreshes last ran. */
export function AlertsStatusWidget() {
  const { data, pending } = useWidgetData("settings", () => api.getSettings());
  if (!data) return pending;
  const failing = data.alerts.filter((a) => a.failing);
  const refreshes = Object.entries(data.refresh_last_run);

  return (
    <>
      {failing.length === 0 ? (
        <p className="muted" style={{ marginTop: 0 }}>
          Nothing is failing.
        </p>
      ) : (
        <ul className="dash-notes">
          {failing.map((a) => (
            <li key={a.key} className="error">
              {a.label}
              {a.message && `: ${a.message}`}
            </li>
          ))}
        </ul>
      )}
      {!data.alert_webhook_hint && !data.heartbeat_hint && (
        <p className="muted">
          Failures only reach the log. <Link to="/settings/alerts">Add a webhook</Link>.
        </p>
      )}
      {refreshes.length > 0 && (
        <table className="estimates">
          <thead>
            <tr>
              <th>Refresh</th>
              <th>Last run</th>
              <th className="num">Failed</th>
            </tr>
          </thead>
          <tbody>
            {refreshes.map(([source, run]) => (
              <tr key={source}>
                <td>{SOURCE_LABELS[source] ?? source}</td>
                <td className="muted">{when(run.at)}</td>
                <td className={run.failed ? "num loss" : "num"}>{run.failed}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}

/** The cached spot prices and exchange rates behind every conversion. */
export function MarketDataWidget() {
  const { data, pending } = useWidgetData("settings", () => api.getSettings());
  if (!data) return pending;
  if (data.cached.length === 0) {
    return (
      <p className="muted" style={{ marginBottom: 0 }}>
        Nothing cached yet. Spot prices and exchange rates appear after the first estimate or
        conversion.
      </p>
    );
  }
  return (
    <table className="estimates">
      <thead>
        <tr>
          <th>Value</th>
          <th>Price</th>
          <th>Fetched</th>
        </tr>
      </thead>
      <tbody>
        {data.cached.map((c) => (
          <tr key={c.label}>
            <td>{c.label}</td>
            <td>{c.value}</td>
            <td className="muted">{when(c.fetched_at)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** Owned pieces missing something worth filling in. */
export function DataHealthWidget() {
  const { data, pending } = useWidgetData("data-health", () => api.dataHealth());
  useWidgetEmpty(data !== null && data.checks.every((c) => c.count === 0));
  if (!data) return pending;
  const gaps = data.checks.filter((c) => c.count > 0);
  if (gaps.length === 0) return null;

  return (
    <>
      <p className="muted" style={{ marginTop: 0 }}>
        Of {data.owned} owned items:
      </p>
      <ul className="dash-list">
        {gaps.map((check) => (
          <li key={check.key}>
            <span className="dash-list-main">
              {check.label}
              {check.items.length > 0 && (
                <span className="muted">
                  {" · "}
                  {check.items.map((i, index) => (
                    <span key={i.id}>
                      {index > 0 && ", "}
                      <Link to={`/items/${i.id}`}>{i.label}</Link>
                    </span>
                  ))}
                  {check.count > check.items.length && ` +${check.count - check.items.length}`}
                </span>
              )}
            </span>
            <span className="num">{check.count}</span>
          </li>
        ))}
      </ul>
    </>
  );
}

/** What is waiting in the trash. */
export function TrashWidget({ options }: WidgetProps) {
  const count = optionNumber(options, "count", 5);
  const { data, pending } = useWidgetData("trash", () => api.listTrash());
  useWidgetEmpty(data !== null && data.items.length === 0);
  if (!data) return pending;
  if (data.items.length === 0) return null;

  return (
    <>
      <p className="muted" style={{ marginTop: 0 }}>
        {data.items.length} item(s) in the <Link to="/trash">trash</Link>
        {data.retention_days
          ? `, deleted for good after ${data.retention_days} days`
          : "; automatic emptying is off"}
        .
      </p>
      <ul className="dash-list">
        {data.items.slice(0, count).map((item) => (
          <li key={item.id}>
            <span className="dash-list-main">
              <Link to={`/items/${item.id}`}>{item.label}</Link>
            </span>
            <span className="muted">{new Date(item.deleted_at).toLocaleDateString()}</span>
          </li>
        ))}
      </ul>
    </>
  );
}
