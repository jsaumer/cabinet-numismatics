import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api, Breakdowns, CollectionStats, GainEntry, Gains, money, ValueHistory } from "../api";
import { ChartDatum, Columns, HBars, LineChart } from "../components/charts";

const TOP_N = 8;

function topN(entries: { key: string; estimated_value: number }[]): ChartDatum[] {
  const data = entries.map((e) => ({ key: e.key, value: e.estimated_value }));
  if (data.length <= TOP_N) return data;
  const head = data.slice(0, TOP_N - 1);
  const rest = data.slice(TOP_N - 1);
  return [...head, { key: "Other", value: rest.reduce((s, d) => s + d.value, 0) }];
}

export default function Dashboard() {
  const [stats, setStats] = useState<CollectionStats | null>(null);
  const [breakdowns, setBreakdowns] = useState<Breakdowns | null>(null);
  const [gains, setGains] = useState<Gains | null>(null);
  const [history, setHistory] = useState<ValueHistory | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshNote, setRefreshNote] = useState<string | null>(null);

  const load = () =>
    Promise.all([api.collectionStats(), api.breakdowns(), api.gains(), api.valueHistory()])
      .then(([s, b, g, h]) => {
        setStats(s);
        setBreakdowns(b);
        setGains(g);
        setHistory(h);
      })
      .catch((e: Error) => setError(e.message));

  useEffect(() => {
    load();
  }, []);

  async function refreshMelt() {
    setRefreshing(true);
    setRefreshNote(null);
    try {
      const r = await api.refreshMelt();
      setRefreshNote(
        `Melt refresh: ${r.updated} updated, ${r.skipped} skipped${r.failed ? `, ${r.failed} failed` : ""}.`,
      );
      await load();
    } catch (e) {
      setRefreshNote((e as Error).message);
    } finally {
      setRefreshing(false);
    }
  }

  if (error) return <p className="error">{error}</p>;
  if (!stats || !breakdowns || !gains) return <p className="muted">Loading…</p>;

  if (stats.counts.total === 0) {
    return (
      <div className="empty">
        Nothing to report yet — <Link to="/items/new">add your first item</Link>.
      </div>
    );
  }

  const cur = stats.currency;
  const fmt = (v: number) => money(v, cur);
  const count = (v: number) => String(v);
  const delta = (v: number) => (
    <span className={v >= 0 ? "gain" : "loss"}>
      {v >= 0 ? "+" : ""}{money(v, cur)}
    </span>
  );

  const gainsTable = (entries: GainEntry[], valueHead: string) => (
    <table className="estimates">
      <thead>
        <tr><th>Item</th><th className="num">Paid</th>
          <th className="num">{valueHead}</th><th className="num">Gain</th></tr>
      </thead>
      <tbody>
        {entries.map((e) => (
          <tr key={e.item_id}>
            <td><Link to={`/items/${e.item_id}`}>{e.label}</Link></td>
            <td className="num">{money(e.cost_basis, cur)}</td>
            <td className="num">{money(e.value, cur)}</td>
            <td className="num">{delta(e.gain)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );

  const movers =
    gains.unrealized.length > 10
      ? [...gains.unrealized.slice(0, 5), ...gains.unrealized.slice(-5)]
      : gains.unrealized;

  return (
    <>
      <div className="detail-header">
        <h1>Dashboard</h1>
        <div className="spacer" />
        <button onClick={refreshMelt} disabled={refreshing}>
          {refreshing ? "Refreshing…" : "⚖ Refresh melt values"}
        </button>
        <Link className="button" to="/report">Insurance report</Link>
      </div>
      {refreshNote && <p className="muted">{refreshNote}</p>}

      <div className="card hero-card">
        <div className="hero">
          <span className="hero-label">Estimated collection value</span>
          <span className="hero-value">{money(stats.estimated_value, cur)}</span>
          {stats.estimated_items < stats.counts.owned && (
            <span className="muted">
              based on {stats.estimated_items} of {stats.counts.owned} owned items
            </span>
          )}
        </div>
        <div className="tiles">
          <div className="tile">
            <span className="tile-label">Owned</span>
            <span className="tile-value">{stats.counts.owned}</span>
            <span className="muted">
              {stats.counts.coins} coins · {stats.counts.notes} notes
            </span>
          </div>
          <div className="tile">
            <span className="tile-label">Cost basis</span>
            <span className="tile-value">{money(stats.cost_basis, cur)}</span>
          </div>
          <div className="tile">
            <span className="tile-label">Unrealized</span>
            <span className="tile-value">{delta(stats.unrealized_gain)}</span>
          </div>
          {stats.counts.sold > 0 && (
            <div className="tile">
              <span className="tile-label">Realized ({stats.counts.sold} sold)</span>
              <span className="tile-value">{delta(stats.realized_gain)}</span>
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
      </div>

      {history && history.points.length > 0 && (
        <div className="card">
          <h2>Collection value over time</h2>
          <LineChart
            data={history.points.map((p) => ({ key: p.date.slice(0, 7), value: p.value }))}
            format={(v) => money(v, cur)}
          />
        </div>
      )}

      <div className="chart-grid">
        <div className="card">
          <h2>Estimated value by country</h2>
          <HBars data={topN(breakdowns.by_country)} format={fmt} />
        </div>
        <div className="card">
          <h2>Estimated value by tag</h2>
          <HBars data={topN(breakdowns.by_tag)} format={fmt} />
        </div>
        <div className="card">
          <h2>Items by decade</h2>
          <Columns
            data={breakdowns.by_decade.map((e) => ({ key: e.key, value: e.count }))}
            format={count}
          />
        </div>
        <div className="card">
          <h2>Acquisitions by year</h2>
          <Columns
            data={breakdowns.acquisitions_by_year.map((e) => ({
              key: e.key,
              value: e.count,
              title: `${e.key}: ${e.count} item(s), ${money(e.cost_basis, cur)} spent`,
            }))}
            format={count}
          />
        </div>
        <div className="card">
          <h2>Items by grade</h2>
          <HBars
            data={breakdowns.by_grade.map((e) => ({ key: e.key, value: e.count }))}
            format={count}
          />
        </div>
      </div>

      {gains.unrealized.length > 0 && (
        <div className="card">
          <h2>Unrealized gain/loss{gains.unrealized.length > 10 ? " — top movers" : ""}</h2>
          {gainsTable(movers, "Est. value")}
        </div>
      )}
      {gains.realized.length > 0 && (
        <div className="card">
          <h2>Realized gain/loss (sold)</h2>
          {gainsTable(gains.realized, "Sold for")}
        </div>
      )}
    </>
  );
}
