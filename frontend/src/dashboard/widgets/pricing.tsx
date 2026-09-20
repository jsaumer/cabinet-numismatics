import { Link } from "react-router-dom";

import { api, money } from "../../api";
import { sourceName } from "../../components/provenance";
import { optionNumber } from "../options";
import { useWidgetData, useWidgetEmpty, WidgetProps } from "../WidgetFrame";

const pct = (v: number) => `${v > 0 ? "+" : ""}${v.toFixed(1)}%`;

/** How much of the collection has a sourced estimate. */
export function PricingCoverageWidget() {
  const { data, pending } = useWidgetData("pricing-coverage", () => api.pricingCoverage());
  if (!data) return pending;
  return (
    <>
      <p className="muted" style={{ marginTop: 0 }}>
        {data.estimated_items} of {data.owned_items} owned items have an estimate
        {data.manual_only_items > 0 && ` (${data.manual_only_items} manual only)`}.{" "}
        <Link to="/pricing">The pricing report</Link> says why.
      </p>
      <table className="estimates">
        <thead>
          <tr>
            <th>Source</th>
            <th className="num">Priced</th>
            <th className="num">Failed</th>
          </tr>
        </thead>
        <tbody>
          {data.sources.map((s) => (
            <tr key={s.source}>
              <td>
                {sourceName(s.source)}
                {!s.enabled && <span className="muted"> (off)</span>}
              </td>
              <td className="num">{s.priced}</td>
              <td className={s.failed ? "num error" : "num"}>{s.failed}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

/** Values that have gone out of date. */
export function StaleEstimatesWidget({ options }: WidgetProps) {
  const days = optionNumber(options, "days", 30);
  const count = optionNumber(options, "count", 6);
  const { data, pending } = useWidgetData(`pricing-stale:${days}`, () => api.pricingStale(days));
  useWidgetEmpty(data !== null && data.stale.length === 0);
  if (!data) return pending;
  if (data.stale.length === 0) return null;

  return (
    <>
      <p className="muted" style={{ marginTop: 0 }}>
        {data.stale.length} of {data.checked} latest estimates are {data.days} days old or built
        from expired source data.
      </p>
      <table className="estimates">
        <thead>
          <tr>
            <th>Item</th>
            <th>Source</th>
            <th className="num">Value</th>
            <th className="num">Age</th>
          </tr>
        </thead>
        <tbody>
          {data.stale.slice(0, count).map((e) => (
            <tr key={`${e.item_id}-${e.source}`}>
              <td>
                <Link to={`/items/${e.item_id}`}>{e.label}</Link>
              </td>
              <td title={e.source_label}>{sourceName(e.source)}</td>
              <td className="num">{money(e.estimated_value, e.currency)}</td>
              <td className="num">{e.age_days} d</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

/** Where the sources are furthest apart on the same item. */
export function SourceDisagreementsWidget({ options }: WidgetProps) {
  const count = optionNumber(options, "count", 5);
  const { data, pending } = useWidgetData("pricing-sources", () => api.pricingSources());
  useWidgetEmpty(data !== null && data.disagreements.length === 0);
  if (!data) return pending;
  if (data.disagreements.length === 0) return null;

  return (
    <table className="estimates">
      <thead>
        <tr>
          <th>Item</th>
          <th>Values</th>
          <th className="num">Spread</th>
        </tr>
      </thead>
      <tbody>
        {data.disagreements.slice(0, count).map((d) => (
          <tr key={d.item_id}>
            <td>
              <Link to={`/items/${d.item_id}`}>{d.label}</Link>
            </td>
            <td>
              <div className="chip-row">
                {Object.entries(d.values).map(([key, value]) => (
                  <span key={key} className="chip">
                    {sourceName(key)} {money(value, data.currency)}
                  </span>
                ))}
              </div>
            </td>
            <td className="num">{d.spread_pct.toFixed(1)}%</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** How the estimates held up against what items sold for. */
export function EstimateAccuracyWidget() {
  const { data, pending } = useWidgetData("pricing-accuracy", () => api.pricingAccuracy());
  useWidgetEmpty(data !== null && data.compared_items === 0);
  if (!data) return pending;
  if (data.compared_items === 0) return null;

  return (
    <>
      <p className="muted" style={{ marginTop: 0 }}>
        {data.compared_items} of {data.sold_items} sold items had an estimate on or before the sale
        date. Positive means the estimate was high.
      </p>
      <table className="estimates">
        <thead>
          <tr>
            <th>Source</th>
            <th className="num">Sales</th>
            <th className="num">Median error</th>
            <th className="num">Bias</th>
          </tr>
        </thead>
        <tbody>
          {data.summary.map((s) => (
            <tr key={s.source}>
              <td>{s.source === "blended" ? <b>Shown value</b> : sourceName(s.source)}</td>
              <td className="num">{s.sales}</td>
              <td className="num">±{s.median_abs_error_pct.toFixed(1)}%</td>
              <td className="num">{pct(s.mean_error_pct)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}
