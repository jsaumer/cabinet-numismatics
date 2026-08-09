import { useEffect, useState } from "react";

import { api, AppSettings, AppSettingsUpdate, SourceStatus } from "../api";

export default function Settings() {
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [currency, setCurrency] = useState("");
  const [cadence, setCadence] = useState("");
  const [keys, setKeys] = useState<Record<string, string>>({});

  useEffect(() => {
    api
      .getSettings()
      .then((s) => {
        setSettings(s);
        setCurrency(s.display_currency);
        setCadence(String(s.reestimate_days));
      })
      .catch((e: Error) => setError(e.message));
  }, []);

  async function apply(payload: AppSettingsUpdate, message: string) {
    setSaving(true);
    setError(null);
    setNote(null);
    try {
      const updated = await api.updateSettings(payload);
      setSettings(updated);
      setCurrency(updated.display_currency);
      setCadence(String(updated.reestimate_days));
      setNote(message);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  if (error && !settings) return <p className="error">{error}</p>;
  if (!settings) return <p className="muted">Loading…</p>;

  const sourceCard = (source: SourceStatus) => {
    const keyField = source.key === "numista" ? "numista_api_key" : "pcgs_api_token";
    const enabledField = source.key === "numista" ? "numista_enabled" : "pcgs_enabled";
    return (
      <div className="source-row" key={source.key}>
        <div className="source-head">
          <label className="slot">
            <input
              type="checkbox"
              checked={source.enabled}
              disabled={saving || (source.key !== "melt" && !source.configured)}
              onChange={(e) =>
                apply(
                  source.key === "melt"
                    ? { melt_enabled: e.target.checked }
                    : { [enabledField]: e.target.checked },
                  `${source.name} ${e.target.checked ? "enabled" : "disabled"}.`,
                )
              }
            />
            <b>{source.name}</b>
          </label>
          {!source.available && <span className="badge status-wishlist">adapter pending</span>}
        </div>
        {source.note && <p className="muted" style={{ margin: "0.2rem 0 0.4rem" }}>{source.note}</p>}
        {source.key !== "melt" && (
          <div className="estimate-form" style={{ marginTop: 0 }}>
            <label className="field">
              {source.key === "numista" ? "API key" : "API token"}
              {source.configured
                ? ` (saved ${source.secret_hint ?? ""})`
                : " (not configured)"}
              <input
                type="password"
                autoComplete="off"
                placeholder={source.configured ? "replace…" : "paste key…"}
                value={keys[keyField] ?? ""}
                onChange={(e) => setKeys((k) => ({ ...k, [keyField]: e.target.value }))}
              />
            </label>
            <button
              disabled={saving || !(keys[keyField] ?? "").trim()}
              onClick={() => {
                apply({ [keyField]: keys[keyField].trim() }, "Key saved.");
                setKeys((k) => ({ ...k, [keyField]: "" }));
              }}
            >
              Save key
            </button>
            {source.configured && (
              <button
                disabled={saving}
                onClick={() => apply({ [keyField]: "" }, "Key removed.")}
              >
                Remove key
              </button>
            )}
          </div>
        )}
      </div>
    );
  };

  return (
    <>
      <div className="detail-header">
        <h1>Settings</h1>
      </div>
      {error && <p className="error">{error}</p>}
      {note && <p className="muted">{note}</p>}

      <div className="card">
        <h2>General</h2>
        <div className="estimate-form" style={{ marginTop: 0 }}>
          <label className="field">
            Display currency (totals, dashboard, report)
            <input value={currency} maxLength={3} style={{ width: "5rem" }}
              onChange={(e) => setCurrency(e.target.value)} />
          </label>
          <label className="field">
            Melt refresh cadence (days; 0 disables)
            <input type="number" min={0} max={365} value={cadence} style={{ width: "6rem" }}
              onChange={(e) => setCadence(e.target.value)} />
          </label>
          <button
            className="primary"
            disabled={saving}
            onClick={() =>
              apply(
                {
                  display_currency: currency.trim().toUpperCase(),
                  reestimate_days: Number(cadence),
                },
                "General settings saved.",
              )
            }
          >
            Save
          </button>
        </div>
        <p className="muted" style={{ marginBottom: 0 }}>
          Amounts in other currencies convert at cached daily ECB rates; anything
          unconvertible is excluded from totals and counted, never guessed.
        </p>
      </div>

      <div className="card">
        <h2>Price sources</h2>
        <p className="muted" style={{ marginTop: 0 }}>
          🔒 Keys are encrypted before they are stored and can never be read back — only
          replaced or removed.
        </p>
        {settings.sources.map(sourceCard)}
      </div>

      <div className="card">
        <h2>Cached market data</h2>
        {settings.cached.length === 0 && (
          <p className="muted">
            Nothing cached yet — spot prices and exchange rates appear here after the first
            estimate or conversion.
          </p>
        )}
        {settings.cached.length > 0 && (
          <table className="estimates">
            <thead>
              <tr><th>Value</th><th>Price</th><th>Source</th><th>Fetched</th></tr>
            </thead>
            <tbody>
              {settings.cached.map((c) => (
                <tr key={c.label}>
                  <td>{c.label}</td>
                  <td>{c.value}</td>
                  <td className="muted">{c.source}</td>
                  <td className="muted">{new Date(c.fetched_at).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}
