import { api, BreakdownEntry, Breakdowns, money, WidgetOptions } from "../../api";
import { ChartDatum, Columns, HBars } from "../../components/charts";
import { optionIdOrNull, optionNumber, optionOrNull, optionText } from "../options";
import { useWidgetData, WidgetProps } from "../WidgetFrame";

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
  acquisition_year: {
    label: "year acquired",
    field: "acquisitions_by_year",
    chart: "columns",
    trim: false,
  },
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
