import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import {
  AccuracyReport,
  api,
  CoverageStatus,
  money,
  PricingCoverage,
  SourcesReport,
  StaleReport,
} from "../api";
import { sourceName } from "../components/provenance";

const STATUS_LABELS: Record<CoverageStatus, string> = {
  priced: "priced",
  not_applicable: "can't price",
  failed: "failed",
  not_tried: "not tried",
  disabled: "off",
};

const STRATEGY_LABELS: Record<string, string> = {
  latest: "the latest estimate",
  preferred_source: "the preferred source",
  average: "the average of sources",
};

const STALE_DAYS = [7, 30, 90, 365];

const pct = (v: number) => `${v > 0 ? "+" : ""}${v.toFixed(1)}%`;

export default function Pricing() {
  const [coverage, setCoverage] = useState<PricingCoverage | null>(null);
  const [sources, setSources] = useState<SourcesReport | null>(null);
  const [accuracy, setAccuracy] = useState<AccuracyReport | null>(null);
  const [days, setDays] = useState(30);
  const [stale, setStale] = useState<StaleReport | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api.pricingCoverage(), api.pricingSources(), api.pricingAccuracy()])
      .then(([c, s, a]) => {
        setCoverage(c);
        setSources(s);
        setAccuracy(a);
      })
      .catch((e: Error) => setError(e.message));
  }, []);

  useEffect(() => {
    api
      .pricingStale(days)
      .then(setStale)
      .catch((e: Error) => setError(e.message));
  }, [days]);

  if (error) return <p className="error">{error}</p>;
  if (!coverage || !sources || !accuracy) return <p className="muted">Loading…</p>;

  const cur = sources.currency;

  return (
    <>
      <div className="detail-header">
        <h1>Pricing</h1>
      </div>
      <p className="muted">
        How well the collection is priced: what's missing and why, what's out of date, how the
        sources compare, and how estimates held up against what items actually sold for.
      </p>

      <div className="card">
        <h2>Coverage</h2>
        <p className="muted" style={{ marginTop: 0 }}>
          {coverage.estimated_items} of {coverage.owned_items} owned items have an estimate
          {coverage.manual_only_items > 0 && ` (${coverage.manual_only_items} manual only)`}.
        </p>
        <div className="table-scroll">
          <table className="estimates">
            <thead>
              <tr>
                <th>Source</th>
                <th className="num">Priced</th>
                <th className="num">Can't price</th>
                <th className="num">Failed</th>
                <th className="num">Not tried</th>
              </tr>
            </thead>
            <tbody>
              {coverage.sources.map((s) => (
                <tr key={s.source}>
                  <td>
                    {sourceName(s.source)}
                    {!s.enabled && <span className="muted"> (off)</span>}
                  </td>
                  <td className="num">{s.priced}</td>
                  <td className="num">{s.not_applicable}</td>
                  <td className={s.failed ? "num error" : "num"}>{s.failed}</td>
                  <td className="num">{s.not_tried}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {coverage.items.length === 0 ? (
          <p className="muted">Nothing needs attention: every owned item is priced where it can be.</p>
        ) : (
          <>
            <h3>Needs attention</h3>
            <p className="muted" style={{ marginTop: 0 }}>
              Items with no estimate, a source that failed or hasn't been tried, or a source
              whose last attempt didn't produce a new value.
            </p>
            <div className="table-scroll">
              <table className="estimates">
                <thead>
                  <tr>
                    <th>Item</th>
                    {coverage.sources.map((s) => (
                      <th key={s.source}>{sourceName(s.source)}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {coverage.items.map((item) => (
                    <tr key={item.item_id}>
                      <td>
                        <Link to={`/items/${item.item_id}`}>{item.label}</Link>
                        {!item.has_estimate && <div className="muted coverage-reason">no estimate</div>}
                      </td>
                      {item.sources.map((sc) => (
                        <td key={sc.source}>
                          <span className={`chip coverage-${sc.status}`}>
                            {STATUS_LABELS[sc.status]}
                          </span>
                          {sc.status !== "priced" && sc.status !== "disabled" && sc.reason && (
                            <div className="muted coverage-reason">{sc.reason}</div>
                          )}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>

      <div className="card">
        <h2>Stale estimates</h2>
        <div className="estimate-form" style={{ marginTop: 0 }}>
          <label className="field">
            Older than
            <select value={days} onChange={(e) => setDays(Number(e.target.value))}>
              {STALE_DAYS.map((d) => (
                <option key={d} value={d}>
                  {d} days
                </option>
              ))}
            </select>
          </label>
        </div>
        {stale === null ? (
          <p className="muted">Loading…</p>
        ) : stale.stale.length === 0 ? (
          <p className="muted">
            None of the {stale.checked} latest estimates are {stale.days} days old or built from
            expired source data.
          </p>
        ) : (
          <>
            <p className="muted">
              {stale.stale.length} of {stale.checked} latest estimates (one per item and source).
              Rows marked <b>in totals</b> are the value shown for that item.
            </p>
            <div className="table-scroll">
              <table className="estimates">
                <thead>
                  <tr>
                    <th>Item</th>
                    <th>Source</th>
                    <th className="num">Value</th>
                    <th className="num">Age</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {stale.stale.map((e) => (
                    <tr key={`${e.item_id}-${e.source}`}>
                      <td><Link to={`/items/${e.item_id}`}>{e.label}</Link></td>
                      <td title={e.source_label}>{sourceName(e.source)}</td>
                      <td className="num">{money(e.estimated_value, e.currency)}</td>
                      <td className="num">{e.age_days} d</td>
                      <td>
                        {e.in_totals && <span className="chip">in totals</span>}
                        {e.upstream_stale && (
                          <span className="chip coverage-failed" title="The source's data was past its cache window when this was estimated">
                            expired source data
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>

      <div className="card">
        <h2>By source</h2>
        <p className="muted" style={{ marginTop: 0 }}>
          Each source's latest estimate per owned item, in {cur}. The shown value uses{" "}
          {STRATEGY_LABELS[sources.strategy] ?? sources.strategy}
          {sources.strategy === "preferred_source" &&
            sources.preferred_source &&
            ` (${sourceName(sources.preferred_source)})`}
          {sources.averaged_items > 0 && ` (${sources.averaged_items} item(s) averaged)`}.{" "}
          <Link to="/settings/general">Change in Settings</Link>.
        </p>
        <div className="table-scroll">
          <table className="estimates">
            <thead>
              <tr>
                <th>Source</th>
                <th className="num">Items</th>
                <th className="num">Total</th>
                <th className="num">Avg confidence</th>
                <th className="num">Median age</th>
                <th className="num">Shown value for</th>
              </tr>
            </thead>
            <tbody>
              {sources.sources.map((s) => (
                <tr key={s.source}>
                  <td>{sourceName(s.source)}</td>
                  <td className="num">{s.items}</td>
                  <td className="num">{s.items ? money(s.total_value, cur) : "–"}</td>
                  <td className="num">
                    {s.avg_confidence != null ? `${Math.round(s.avg_confidence * 100)}%` : "–"}
                  </td>
                  <td className="num">
                    {s.median_age_days != null ? `${s.median_age_days} d` : "–"}
                  </td>
                  <td className="num">{s.in_totals}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {sources.excluded_other_currency > 0 && (
          <p className="muted">
            {sources.excluded_other_currency} amount(s) left out of totals (no exchange rate).
          </p>
        )}
        {sources.disagreements.length > 0 && (
          <>
            <h3>Where sources disagree most</h3>
            <div className="table-scroll">
              <table className="estimates">
                <thead>
                  <tr>
                    <th>Item</th>
                    <th>Values</th>
                    <th className="num">Spread</th>
                  </tr>
                </thead>
                <tbody>
                  {sources.disagreements.map((d) => (
                    <tr key={d.item_id}>
                      <td><Link to={`/items/${d.item_id}`}>{d.label}</Link></td>
                      <td>
                        <div className="chip-row">
                          {Object.entries(d.values).map(([key, value]) => (
                            <span key={key} className="chip">
                              {sourceName(key)} {money(value, cur)}
                            </span>
                          ))}
                        </div>
                      </td>
                      <td className="num">{d.spread_pct.toFixed(1)}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>

      <div className="card">
        <h2>Accuracy against sales</h2>
        {accuracy.compared_items === 0 ? (
          <p className="muted" style={{ marginBottom: 0 }}>
            {accuracy.sold_items === 0
              ? "No sold items yet. Mark an item sold with its price to see how its estimates held up."
              : `None of the ${accuracy.sold_items} sold item(s) had an estimate on or before the sale date.`}
          </p>
        ) : (
          <>
            <p className="muted" style={{ marginTop: 0 }}>
              {accuracy.compared_items} of {accuracy.sold_items} sold items had an estimate on or
              before the sale date. Error is estimate against sold price: positive means the
              estimate was high.
            </p>
            <div className="table-scroll">
              <table className="estimates">
                <thead>
                  <tr>
                    <th>Source</th>
                    <th className="num">Sales</th>
                    <th className="num">Median error</th>
                    <th className="num">Bias</th>
                    <th className="num">Within 20%</th>
                  </tr>
                </thead>
                <tbody>
                  {accuracy.summary.map((s) => (
                    <tr key={s.source}>
                      <td>{s.source === "blended" ? <b>Shown value</b> : sourceName(s.source)}</td>
                      <td className="num">{s.sales}</td>
                      <td className="num">±{s.median_abs_error_pct.toFixed(1)}%</td>
                      <td className="num">{pct(s.mean_error_pct)}</td>
                      <td className="num">
                        {s.within_20_pct} of {s.sales}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="table-scroll">
              <table className="estimates">
                <thead>
                  <tr>
                    <th>Item</th>
                    <th className="num">Sold for</th>
                    <th className="num">Shown estimate</th>
                    <th className="num">Error</th>
                    <th>By source</th>
                  </tr>
                </thead>
                <tbody>
                  {accuracy.items.map((item) => (
                    <tr key={item.item_id}>
                      <td>
                        <Link to={`/items/${item.item_id}`}>{item.label}</Link>
                        {item.sold_date && <div className="muted coverage-reason">sold {item.sold_date}</div>}
                      </td>
                      <td className="num">{money(item.sold_price, accuracy.currency)}</td>
                      <td className="num">
                        {item.blended ? money(item.blended.value, accuracy.currency) : "–"}
                      </td>
                      <td className="num">{item.blended ? pct(item.blended.error_pct) : "–"}</td>
                      <td>
                        <div className="chip-row">
                          {item.by_source.map((e) => (
                            <span key={e.source} className="chip" title={money(e.value, accuracy.currency)}>
                              {sourceName(e.source)} {pct(e.error_pct)}
                            </span>
                          ))}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>
    </>
  );
}
