import { useState } from "react";

import { SourceStatus } from "../../api";
import { LockIcon } from "../../components/icons";
import { Section, useSettings } from "./shared";

// Sources with nothing to configure beyond on/off.
const KEYLESS = new Set(["melt", "comps"]);

/** Settings → Pricing: the price-source keys (Price sources) and the
 * cached market data they and the stack view feed from (Cached market
 * data). One card, keys first. */
export default function PricingSection() {
  const { settings, error, note, saving, apply } = useSettings();
  const [keys, setKeys] = useState<Record<string, string>>({});

  if (error && !settings) return <p className="error">{error}</p>;
  if (!settings) return <p className="muted">Loading…</p>;

  const sourceCard = (source: SourceStatus) => {
    const keyless = KEYLESS.has(source.key);
    const keyField = source.key === "numista" ? "numista_api_key" : "pcgs_api_token";
    const enabledField = `${source.key}_enabled` as
      | "melt_enabled"
      | "numista_enabled"
      | "pcgs_enabled"
      | "comps_enabled";
    return (
      <div className="source-row" key={source.key}>
        <div className="source-head">
          <label className="slot">
            <input
              type="checkbox"
              checked={source.enabled}
              disabled={saving || (!keyless && !source.configured)}
              onChange={(e) =>
                apply(
                  { [enabledField]: e.target.checked },
                  `${source.name} ${e.target.checked ? "enabled" : "disabled"}.`,
                )
              }
            />
            <b>{source.name}</b>
          </label>
          {!source.available && <span className="badge status-wishlist">adapter pending</span>}
        </div>
        {source.note && <p className="muted" style={{ margin: "0.2rem 0 0.4rem" }}>{source.note}</p>}
        {!keyless && (
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
        {source.key === "numista" && (
          <div className="estimate-form" style={{ marginTop: "0.4rem" }}>
            <label className="field">
              Scheduled refresh
              <select
                value={settings.numista_refresh_days ?? ""}
                disabled={saving}
                onChange={(e) => {
                  const days = e.target.value ? Number(e.target.value) : null;
                  apply(
                    { numista_refresh_days: days },
                    days
                      ? `Numista scheduled refresh set to every ${days} days.`
                      : "Numista scheduled refresh turned off.",
                  );
                }}
              >
                <option value="">Off</option>
                <option value="7">Every 7 days</option>
                <option value="14">Every 14 days</option>
                <option value="30">Every 30 days</option>
              </select>
            </label>
            {settings.numista_refresh_days &&
              (() => {
                const monthlyCalls = Math.ceil(
                  settings.numista_priceable_items * 2 * (30 / settings.numista_refresh_days!),
                );
                const overBudget = monthlyCalls > 2000;
                return (
                  <p className={overBudget ? "error" : "muted"} style={{ margin: 0 }}>
                    ~{monthlyCalls} Numista calls/month at this cadence across{" "}
                    {settings.numista_priceable_items} priceable item(s): 2 calls per estimate,
                    free-tier cap is 2,000/month.
                    {overBudget && " This exceeds the free tier; expect 429s before the month is out."}
                  </p>
                );
              })()}
          </div>
        )}
        {source.key === "numista" && (
          <div className="paid-option">
            <label className="slot">
              <input
                type="checkbox"
                checked={settings.numista_sales_enabled}
                disabled={saving || !source.configured}
                onChange={(e) =>
                  apply(
                    { numista_sales_enabled: e.target.checked },
                    `Numista auction sales ${e.target.checked ? "enabled" : "disabled"}.`,
                  )
                }
              />
              <b>Numista auction sales</b>
              <span className="badge status-wishlist">paid Numista API plan</span>
            </label>
            <p className="muted" style={{ margin: "0.3rem 0 0" }}>
              Adds a <i>Fetch Numista auction sales</i> button to each item's sales log, which
              copies the auction results Numista has recorded for that year and mint (house,
              date, lot link, grade, price) into the log for the comps estimate.{" "}
              <b>This needs Numista's paid API plan</b>: at the time of writing a one-time
              €100 activation fee, then at least €100 a month (€0.01 a request, before VAT). A
              free key gets <code>Permission denied</code>, and the button says so. Leave this
              off unless you have that plan.
            </p>
            <p className="muted" style={{ margin: "0.3rem 0 0" }}>
              Each fetch is one request, made only when you click, never on the refresh
              schedule, and repeating it the same day is free (cached for a day).
            </p>
          </div>
        )}
        {source.key === "pcgs" && (
          <div className="estimate-form" style={{ marginTop: "0.4rem" }}>
            <label className="slot">
              <input
                type="checkbox"
                checked={settings.pcgs_auto_refresh}
                disabled={saving}
                onChange={(e) =>
                  apply(
                    { pcgs_auto_refresh: e.target.checked },
                    `PCGS auto-refresh ${e.target.checked ? "enabled" : "disabled"} (weekly).`,
                  )
                }
              />
              Auto-refresh weekly
            </label>
            <p className={settings.pcgs_priceable_items > 100 ? "error" : "muted"} style={{ margin: 0 }}>
              {settings.pcgs_priceable_items} priceable item(s), one call each. PCGS allows 100
              calls a day by default
              {settings.pcgs_priceable_items > 100
                ? ", so a refresh stops at the limit and raises the quota alert. PCGS raises " +
                  "the limit on request (apis@pcgs.com)."
                : "."}
            </p>
          </div>
        )}
      </div>
    );
  };

  return (
    <Section title="Pricing">
      {error && <p className="error">{error}</p>}
      {note && <p className="muted">{note}</p>}

      <h3>Price sources</h3>
      <p className="muted" style={{ marginTop: 0 }}>
        <LockIcon /> Keys are encrypted before they are stored and can never be read back, only
        replaced or removed.
      </p>
      {settings.sources.map(sourceCard)}

      <h3>Cached market data</h3>
      {settings.cached.length === 0 && (
        <p className="muted">
          Nothing cached yet. Spot prices and exchange rates appear here after the first
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
    </Section>
  );
}
