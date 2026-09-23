import { api, BreakdownEntry, Breakdowns, money, WidgetOptions } from "../../api";
import { ChartDatum, Columns, HBars } from "../../components/charts";
import { optionIdOrNull, optionNumber, optionOrNull, optionText } from "../options";
import { useWidgetData, useWidgetEmpty, WidgetProps } from "../WidgetFrame";

type Measure = "value" | "count" | "cost";

interface Dimension {
  /** In a title: "Items by decade". */
  label: string;
  field: Exclude<keyof Breakdowns, "currency">;
  chart: "bars" | "columns";
  /** Ordered by size, so a long tail can become "Other". A dimension that
   * runs in time keeps every bucket: an "Other" year means nothing. */
  trim: boolean;
}

export const DIMENSIONS: Record<string, Dimension> = {
  country: { label: "country", field: "by_country", chart: "bars", trim: true },
  type: { label: "type", field: "by_type", chart: "bars", trim: true },
  decade: { label: "decade", field: "by_decade", chart: "columns", trim: false },
  grade: { label: "grade", field: "by_grade", chart: "bars", trim: true },
  tag: { label: "tag", field: "by_tag", chart: "bars", trim: true },
  metal: { label: "metal", field: "by_metal", chart: "bars", trim: true },
  acquisition_year: {
    label: "year acquired",
    field: "acquisitions_by_year",
    chart: "columns",
    trim: false,
  },
};

// The type dimension's keys are the raw item type ("coin", "note",
// "bullion"); this is the only dimension whose bars need a friendlier label
// than the key itself.
const TYPE_LABELS: Record<string, string> = {
  coin: "Coin",
  note: "Note",
  bullion: "Bars and rounds",
};

const MEASURE_TITLES: Record<Measure, string> = {
  value: "Estimated value by",
  count: "Items by",
  cost: "Cost basis by",
};

const measureOf = (options: WidgetOptions): Measure => {
  const measure = optionText(options, "measure", "value");
  return measure === "count" || measure === "cost" ? measure : "value";
};

/** The card's own title, e.g. "Estimated value by country". */
export function breakdownTitle(options: WidgetOptions): string {
  const key = optionText(options, "dimension", "country");
  const dimension = DIMENSIONS[key] ?? DIMENSIONS.country;
  const measure = measureOf(options);
  // The one that doesn't read well from the pattern.
  if (key === "acquisition_year" && measure === "count") return "Acquisitions by year";
  return `${MEASURE_TITLES[measure]} ${dimension.label}`;
}

const amount = (entry: BreakdownEntry, measure: Measure): number =>
  measure === "count" ? entry.count : measure === "cost" ? entry.cost_basis : entry.estimated_value;

/** Owned items grouped one way, optionally scoped to a tag or a set. */
export function BreakdownWidget({ options }: WidgetProps) {
  const key = optionText(options, "dimension", "country");
  const dimension = DIMENSIONS[key] ?? DIMENSIONS.country;
  const measure = measureOf(options);
  const topN = optionNumber(options, "top_n", 8);
  const tag = optionOrNull(options, "tag");
  const setId = optionIdOrNull(options, "set_id");

  const { data, pending } = useWidgetData(`breakdowns:${tag ?? ""}:${setId ?? ""}`, () =>
    api.breakdowns({ tag, set_id: setId }),
  );
  // Only to name the set the card is scoped to.
  const sets = useWidgetData("sets", () => api.listSets(), setId !== null);
  if (!data) return pending;

  const entries = data[dimension.field];
  const format =
    measure === "count" ? (v: number) => String(v) : (v: number) => money(v, data.currency);

  let points: ChartDatum[] = entries.map((e) => ({
    key: e.key,
    label: key === "type" ? (TYPE_LABELS[e.key] ?? e.key) : undefined,
    value: amount(e, measure),
    title:
      key === "acquisition_year"
        ? `${e.key}: ${e.count} item(s), ${money(e.cost_basis, data.currency)} spent`
        : undefined,
  }));
  if (dimension.trim && points.length > topN) {
    const rest = points.slice(topN - 1);
    points = [
      ...points.slice(0, topN - 1),
      { key: "Other", value: rest.reduce((sum, p) => sum + p.value, 0) },
    ];
  }

  const setName = sets.data?.find((s) => s.id === setId)?.name;
  const scope =
    tag || setId !== null ? (
      <p className="muted" style={{ marginTop: 0 }}>
        {tag ? `Tagged "${tag}"` : `In the set "${setName ?? setId}"`} only.
      </p>
    ) : null;

  return (
    <>
      {scope}
      {dimension.chart === "columns" ? (
        <Columns data={points} format={format} />
      ) : (
        <HBars data={points} format={format} />
      )}
    </>
  );
}

/** How much of the collection is in a slab, and from which service. */
export function CertifiedShareWidget() {
  const { data, pending } = useWidgetData("quality", () => api.quality());
  useWidgetEmpty(data !== null && data.owned === 0);
  if (!data) return pending;
  if (data.owned === 0) return null;
  const share = (data.certified.items / data.owned) * 100;

  return (
    <>
      <div className="tiles">
        <div className="tile">
          <span className="tile-label">Certified</span>
          <span className="tile-value">{share.toFixed(0)}%</span>
          <span className="muted">
            {data.certified.items} of {data.owned} owned
          </span>
        </div>
        <div className="tile">
          <span className="tile-label">Value in slabs</span>
          <span className="tile-value">{money(data.certified.value, data.currency)}</span>
          <span className="muted">raw {money(data.raw.value, data.currency)}</span>
        </div>
        <div className="tile">
          <span className="tile-label">Graded</span>
          <span className="tile-value">{data.graded}</span>
          <span className="muted">{data.ungraded} ungraded</span>
        </div>
      </div>
      {data.by_service.length > 0 && (
        <table className="estimates" style={{ marginTop: "0.8rem" }}>
          <thead>
            <tr>
              <th>Service</th>
              <th className="num">Items</th>
              <th className="num">Value</th>
            </tr>
          </thead>
          <tbody>
            {data.by_service.map((s) => (
              <tr key={s.key}>
                <td>{s.key}</td>
                <td className="num">{s.count}</td>
                <td className="num">{money(s.estimated_value, data.currency)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}

/** How the value is spread: a few big pieces, or many even ones. */
export function ValueSpreadWidget() {
  const { data, pending } = useWidgetData("value-spread", () => api.valueSpread());
  useWidgetEmpty(data !== null && data.median == null);
  if (!data) return pending;
  if (data.median == null) return null;

  const rows: [string, string][] = [
    ["Median", money(data.median, data.currency)],
    ["Mean", money(data.mean, data.currency)],
    ["Lowest", money(data.min, data.currency)],
    ["Highest", money(data.max, data.currency)],
  ];
  return (
    <>
      <dl className="facts">
        {rows.map(([label, value]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
      {data.top_share_pct != null && (
        <p className="muted" style={{ marginBottom: 0 }}>
          The top tenth of {data.items} valued pieces holds{" "}
          <b>{data.top_share_pct.toFixed(0)}%</b> of the value.
        </p>
      )}
    </>
  );
}

/** How many of each kind the collection holds. */
export function CountsWidget() {
  const { data, pending } = useWidgetData("stats", () => api.collectionStats());
  if (!data) return pending;
  const counts = data.counts;
  const rows: [string, number][] = [
    ["Owned", counts.owned],
    ["Coins", counts.coins],
    ["Notes", counts.notes],
    ["Sold", counts.sold],
    ["Wishlist", counts.wishlist],
    ["In all", counts.total],
  ];
  return (
    <dl className="facts">
      {rows.map(([label, value]) => (
        <div key={label}>
          <dt>{label}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}
