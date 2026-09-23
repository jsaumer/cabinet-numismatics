import { Link } from "react-router-dom";

import { api, GainEntry, money } from "../../api";
import { LineChart } from "../../components/charts";
import { SetupList, setupChecks, useSetupDismissed } from "../../components/setup";
import { optionNumber } from "../options";
import { useWidgetData, useWidgetEmpty, WidgetProps } from "../WidgetFrame";

/** A gain or loss, coloured and signed. */
export function delta(value: number, currency: string) {
  return (
    <span className={value >= 0 ? "gain" : "loss"}>
      {value >= 0 ? "+" : ""}
      {money(value, currency)}
    </span>
  );
}

function gainsTable(entries: GainEntry[], valueHead: string, currency: string) {
  return (
    <div className="table-scroll">
      <table className="estimates">
        <thead>
          <tr>
            <th>Item</th>
            <th className="num">Paid</th>
            <th className="num">{valueHead}</th>
            <th className="num">Gain</th>
          </tr>
        </thead>
        <tbody>
          {entries.map((e) => (
            <tr key={e.item_id}>
              <td>
                <Link to={`/items/${e.item_id}`}>{e.label}</Link>
              </td>
              <td className="num">{money(e.cost_basis, currency)}</td>
              <td className="num">{money(e.value, currency)}</td>
              <td className="num">{delta(e.gain, currency)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** What's still switched off on a fresh install. */
export function SetupWidget() {
  const stats = useWidgetData("stats", () => api.collectionStats());
  const settings = useWidgetData("settings", () => api.getSettings());
  const backups = useWidgetData("backups", () => api.listBackups());
  const health = useWidgetData("health", () => api.health());
  const { dismissed, dismiss } = useSetupDismissed();

  // The backup list and health are extras: a failure there leaves their checks
  // out rather than the whole card.
  const ready = stats.settled && settings.settled && backups.settled && health.settled;
  const checks =
    stats.data && settings.data
      ? setupChecks(stats.data.counts.total, settings.data, backups.data, health.data)
      : null;
  useWidgetEmpty(dismissed || (ready && (checks === null || checks.length === 0)));

  if (!ready) return stats.pending;
  if (dismissed || !checks || checks.length === 0) return null;
  return <SetupList checks={checks} onDismiss={dismiss} />;
}

/** The value hero: the collection's estimated value and the headline figures. */
export function ValueSummaryWidget() {
  const { data: stats, pending } = useWidgetData("stats", () => api.collectionStats());
  if (!stats) return pending;
  const cur = stats.currency;

  return (
    <>
      <div className="hero">
        <span className="hero-label">Estimated collection value</span>
        <span className="hero-value">{money(stats.estimated_value, cur)}</span>
        {stats.estimated_items < stats.counts.owned && (
          <span className="muted">
            based on {stats.estimated_items} of {stats.counts.owned} owned items;{" "}
            <Link to="/pricing">see pricing coverage</Link>
          </span>
        )}
      </div>
      <div className="tiles">
        <div className="tile">
          <span className="tile-label">Owned</span>
          <span className="tile-value">{stats.counts.owned}</span>
          <span className="muted">
            {stats.counts.coins} coins · {stats.counts.notes} notes
            {stats.counts.bullion > 0 && ` · ${stats.counts.bullion} bars and rounds`}
          </span>
        </div>
        <div className="tile">
          <span className="tile-label">Cost basis</span>
          <span className="tile-value">{money(stats.cost_basis, cur)}</span>
        </div>
        <div className="tile">
          <span className="tile-label">Unrealized</span>
          <span className="tile-value">{delta(stats.unrealized_gain, cur)}</span>
        </div>
        {stats.counts.sold > 0 && (
          <div className="tile">
            <span className="tile-label">Realized ({stats.counts.sold} sold)</span>
            <span className="tile-value">{delta(stats.realized_gain, cur)}</span>
          </div>
        )}
        {stats.counts.wishlist > 0 && (
          <div className="tile">
            <span className="tile-label">Wishlist</span>
            <span className="tile-value">{stats.counts.wishlist}</span>
          </div>
        )}
      </div>
      {(stats.converted_other_currency > 0 || stats.excluded_other_currency > 0) && (
        <p className="muted" style={{ marginBottom: 0 }}>
          {stats.converted_other_currency > 0 &&
            `${stats.converted_other_currency} amount(s) converted to ${cur} at daily rates. `}
          {stats.excluded_other_currency > 0 &&
            `${stats.excluded_other_currency} amount(s) excluded (no exchange rate).`}
        </p>
      )}
    </>
  );
}

/** The collection's value month by month. */
export function ValueHistoryWidget({ options }: WidgetProps) {
  const months = optionNumber(options, "months", 24);
  const { data, pending } = useWidgetData(`value-history:${months}`, () =>
    api.valueHistory(months),
  );
  useWidgetEmpty(data !== null && data.points.length === 0);
  if (!data) return pending;
  if (data.points.length === 0) return null;
  return (
    <LineChart
      data={data.points.map((p) => ({ key: p.date.slice(0, 7), value: p.value }))}
      format={(v) => money(v, data.currency)}
    />
  );
}

/** The best and worst unrealized gains among owned items. */
export function UnrealizedMoversWidget({ options }: WidgetProps) {
  const topN = optionNumber(options, "top_n", 5);
  const { data, pending } = useWidgetData("gains", () => api.gains());
  useWidgetEmpty(data !== null && data.unrealized.length === 0);
  if (!data) return pending;
  if (data.unrealized.length === 0) return null;
  const trimmed = data.unrealized.length > topN * 2;
  const rows = trimmed
    ? [...data.unrealized.slice(0, topN), ...data.unrealized.slice(-topN)]
    : data.unrealized;
  return (
    <>
      {trimmed && (
        <p className="muted" style={{ marginTop: 0 }}>
          The best and worst {topN} of {data.unrealized.length} owned items with both a price and
          an estimate.
        </p>
      )}
      {gainsTable(rows, "Est. value", data.currency)}
    </>
  );
}

/** What sold items actually made. */
export function RealizedGainsWidget({ options }: WidgetProps) {
  const topN = optionNumber(options, "top_n", 20);
  const { data, pending } = useWidgetData("gains", () => api.gains());
  useWidgetEmpty(data !== null && data.realized.length === 0);
  if (!data) return pending;
  if (data.realized.length === 0) return null;
  return gainsTable(data.realized.slice(0, topN), "Sold for", data.currency);
}
