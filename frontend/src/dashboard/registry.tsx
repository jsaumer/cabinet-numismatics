// Every widget the dashboard knows: what the catalogue calls it, how big it
// starts, what it can be told, and what draws it. The backend validates the
// same types and options; keep the two in step.

import { ReactNode } from "react";

import type { DashboardWidget, WidgetOptions, WidgetSize } from "../api";
import { OptionField } from "./options";
import { WidgetProps } from "./WidgetFrame";
import { breakdownTitle, BreakdownWidget, CountsWidget } from "./widgets/breakdowns";
import {
  ChecklistsWidget,
  FancySerialsWidget,
  NotesBySignatureWidget,
  RecentAdditionsWidget,
  WishlistWidget,
} from "./widgets/collection";
import {
  AlertsStatusWidget,
  BackupStatusWidget,
  MarketDataWidget,
  TrashWidget,
} from "./widgets/operations";
import {
  EstimateAccuracyWidget,
  PricingCoverageWidget,
  SourceDisagreementsWidget,
  StaleEstimatesWidget,
} from "./widgets/pricing";
import {
  RealizedGainsWidget,
  SetupWidget,
  UnrealizedMoversWidget,
  ValueHistoryWidget,
  ValueSummaryWidget,
} from "./widgets/value";

export type WidgetGroup = "Value" | "Breakdowns" | "Collection" | "Pricing" | "Operations";

export const GROUPS: WidgetGroup[] = [
  "Value",
  "Breakdowns",
  "Collection",
  "Pricing",
  "Operations",
];

export interface WidgetSpec {
  name: string;
  /** One line in the catalogue. */
  description: string;
  group: WidgetGroup;
  defaultSize: WidgetSize;
  defaultOptions: WidgetOptions;
  fields?: OptionField[];
  /** The card's heading, which the options may decide. */
  title: string | ((options: WidgetOptions) => string);
  /** The card carries its own heading, so the frame adds none in view mode. */
  untitled?: boolean;
  cardClass?: string;
  Component: (props: WidgetProps) => ReactNode;
}

const countField = (
  key: string,
  label: string,
  min: number,
  max: number,
  hint?: string,
): OptionField => ({ key, label, kind: "count", min, max, hint });

export const REGISTRY: Record<string, WidgetSpec> = {
  setup: {
    name: "Getting set up",
    description: "What is still switched off: backups, alerts, a price-source key.",
    group: "Operations",
    defaultSize: "full",
    defaultOptions: {},
    title: "Getting set up",
    untitled: true,
    cardClass: "setup-card",
    Component: SetupWidget,
  },
  value_summary: {
    name: "Value summary",
    description: "The estimated total, cost basis, and the gains beside it.",
    group: "Value",
    defaultSize: "full",
    defaultOptions: {},
    title: "Collection value",
    untitled: true,
    cardClass: "hero-card",
    Component: ValueSummaryWidget,
  },
  value_history: {
    name: "Value over time",
    description: "The collection's estimated value month by month.",
    group: "Value",
    defaultSize: "full",
    defaultOptions: { months: 24 },
    fields: [
      {
        key: "months",
        label: "Range",
        kind: "choice",
        choices: [
          { value: 12, label: "12 months" },
          { value: 24, label: "24 months" },
          { value: 60, label: "5 years" },
          { value: 120, label: "10 years" },
        ],
      },
    ],
    title: "Collection value over time",
    Component: ValueHistoryWidget,
  },
  breakdown: {
    name: "Breakdown chart",
    description: "Owned items grouped by country, type, decade, grade, tag, or year acquired.",
    group: "Breakdowns",
    defaultSize: "third",
    defaultOptions: { dimension: "country", measure: "value", top_n: 8, tag: null, set_id: null },
    fields: [
      {
        key: "dimension",
        label: "Group by",
        kind: "choice",
        choices: [
          { value: "country", label: "Country" },
          { value: "type", label: "Type" },
          { value: "decade", label: "Decade" },
          { value: "grade", label: "Grade" },
          { value: "tag", label: "Tag" },
          { value: "acquisition_year", label: "Year acquired" },
        ],
      },
      {
        key: "measure",
        label: "Measure",
        kind: "choice",
        choices: [
          { value: "value", label: "Estimated value" },
          { value: "count", label: "Items" },
          { value: "cost", label: "Cost basis" },
        ],
      },
      countField("top_n", "Bars at most", 3, 20, "The rest become one Other bar."),
      { key: "tag", label: "Only this tag", kind: "tag" },
      { key: "set_id", label: "Only this set", kind: "set" },
    ],
    title: breakdownTitle,
    Component: BreakdownWidget,
  },
  notes_by_signature: {
    name: "Notes by signature",
    description: "Owned notes grouped by series and signature pair.",
    group: "Collection",
    defaultSize: "full",
    defaultOptions: {},
    title: "Notes by series and signature",
    Component: NotesBySignatureWidget,
  },
  unrealized_movers: {
    name: "Unrealized gain/loss",
    description: "The best and worst performers among what is owned.",
    group: "Value",
    defaultSize: "full",
    defaultOptions: { top_n: 5 },
    fields: [countField("top_n", "Best and worst", 3, 25, "This many of each.")],
    title: "Unrealized gain/loss",
    Component: UnrealizedMoversWidget,
  },
  realized_gains: {
    name: "Realized gain/loss",
    description: "What sold items actually made, net of fees.",
    group: "Value",
    defaultSize: "full",
    defaultOptions: { top_n: 20 },
    fields: [countField("top_n", "Rows at most", 3, 50)],
    title: "Realized gain/loss (sold)",
    Component: RealizedGainsWidget,
  },
  counts: {
    name: "Counts",
    description: "How many coins, notes, sold, and wanted pieces there are.",
    group: "Breakdowns",
    defaultSize: "third",
    defaultOptions: {},
    title: "Counts",
    Component: CountsWidget,
  },
  recent_additions: {
    name: "Recent additions",
    description: "The newest items, with their thumbnails and shown value.",
    group: "Collection",
    defaultSize: "half",
    defaultOptions: { count: 6 },
    fields: [countField("count", "Items", 3, 20)],
    title: "Recent additions",
    Component: RecentAdditionsWidget,
  },
  wishlist: {
    name: "Wish list",
    description: "Wanted pieces by priority, or the ones whose target has been reached.",
    group: "Collection",
    defaultSize: "half",
    defaultOptions: { mode: "priority", count: 6 },
    fields: [
      {
        key: "mode",
        label: "Show",
        kind: "choice",
        choices: [
          { value: "priority", label: "By priority" },
          { value: "reached", label: "Target reached" },
        ],
      },
      countField("count", "Items", 3, 20),
    ],
    title: "Wish list",
    Component: WishlistWidget,
  },
  fancy_serials: {
    name: "Fancy serial numbers",
    description: "Notes whose serial number is a radar, repeater, solid, and so on.",
    group: "Collection",
    defaultSize: "half",
    defaultOptions: { count: 6 },
    fields: [countField("count", "Notes", 3, 20)],
    title: "Fancy serial numbers",
    Component: FancySerialsWidget,
  },
  checklists: {
    name: "Checklists",
    description: "Progress against target sets, least complete first.",
    group: "Collection",
    defaultSize: "half",
    defaultOptions: { count: 6 },
    fields: [countField("count", "Checklists", 3, 20)],
    title: "Checklists",
    Component: ChecklistsWidget,
  },
  pricing_coverage: {
    name: "Pricing coverage",
    description: "How many owned items have a sourced estimate, and what failed.",
    group: "Pricing",
    defaultSize: "third",
    defaultOptions: {},
    title: "Pricing coverage",
    Component: PricingCoverageWidget,
  },
  stale_estimates: {
    name: "Stale estimates",
    description: "Values past their age, or built from expired source data.",
    group: "Pricing",
    defaultSize: "half",
    defaultOptions: { days: 30, count: 6 },
    fields: [
      {
        key: "days",
        label: "Older than",
        kind: "choice",
        choices: [
          { value: 7, label: "7 days" },
          { value: 30, label: "30 days" },
          { value: 90, label: "90 days" },
          { value: 365, label: "a year" },
        ],
      },
      countField("count", "Rows", 3, 20),
    ],
    title: "Stale estimates",
    Component: StaleEstimatesWidget,
  },
  source_disagreements: {
    name: "Source disagreements",
    description: "Items where the price sources are furthest apart.",
    group: "Pricing",
    defaultSize: "half",
    defaultOptions: { count: 5 },
    fields: [countField("count", "Rows", 3, 20)],
    title: "Where sources disagree most",
    Component: SourceDisagreementsWidget,
  },
  estimate_accuracy: {
    name: "Estimate accuracy",
    description: "How the estimates held up against what items sold for.",
    group: "Pricing",
    defaultSize: "half",
    defaultOptions: {},
    title: "Accuracy against sales",
    Component: EstimateAccuracyWidget,
  },
  backup_status: {
    name: "Backup status",
    description: "The schedule, the last run, and how much room is left.",
    group: "Operations",
    defaultSize: "third",
    defaultOptions: {},
    title: "Backups",
    Component: BackupStatusWidget,
  },
  alerts_status: {
    name: "Alerts",
    description: "What is failing now, and the last scheduled refreshes.",
    group: "Operations",
    defaultSize: "third",
    defaultOptions: {},
    title: "Alerts",
    Component: AlertsStatusWidget,
  },
  market_data: {
    name: "Cached market data",
    description: "The spot prices and exchange rates behind every conversion.",
    group: "Operations",
    defaultSize: "third",
    defaultOptions: {},
    title: "Cached market data",
    Component: MarketDataWidget,
  },
  trash: {
    name: "Trash",
    description: "What is waiting to be restored or deleted for good.",
    group: "Operations",
    defaultSize: "third",
    defaultOptions: { count: 5 },
    fields: [countField("count", "Items", 3, 20)],
    title: "Trash",
    Component: TrashWidget,
  },
};

export const specFor = (type: string): WidgetSpec | undefined => REGISTRY[type];

/** The heading a card shows: the override, or the widget's own. */
export function widgetTitle(widget: DashboardWidget): string {
  if (widget.title) return widget.title;
  const spec = REGISTRY[widget.type];
  if (!spec) return widget.type;
  return typeof spec.title === "function" ? spec.title(widget.options) : spec.title;
}

const ID_CHARS = "abcdefghijklmnopqrstuvwxyz0123456789";

/** A fresh instance of a type, with an id unique in this layout. */
export function newWidget(type: string, taken: Iterable<string>): DashboardWidget {
  const spec = REGISTRY[type];
  const used = new Set(taken);
  let id = "";
  do {
    id = "w-";
    for (let i = 0; i < 6; i++) {
      id += ID_CHARS[Math.floor(Math.random() * ID_CHARS.length)];
    }
  } while (used.has(id));
  return {
    id,
    type,
    size: spec.defaultSize,
    title: null,
    options: { ...spec.defaultOptions },
  };
}

/** Today's dashboard, as widgets. The server sends this when nothing is
 * saved; it stands in only when that request fails, so the page still draws. */
export const DEFAULT_WIDGETS: DashboardWidget[] = [
  { id: "d-1", type: "setup", size: "full", title: null, options: {} },
  { id: "d-2", type: "value_summary", size: "full", title: null, options: {} },
  { id: "d-3", type: "value_history", size: "full", title: null, options: { months: 24 } },
  {
    id: "d-4",
    type: "breakdown",
    size: "third",
    title: null,
    options: { dimension: "country", measure: "value", top_n: 8, tag: null, set_id: null },
  },
  {
    id: "d-5",
    type: "breakdown",
    size: "third",
    title: null,
    options: { dimension: "tag", measure: "value", top_n: 8, tag: null, set_id: null },
  },
  {
    id: "d-6",
    type: "breakdown",
    size: "third",
    title: null,
    options: { dimension: "decade", measure: "count", top_n: 8, tag: null, set_id: null },
  },
  {
    id: "d-7",
    type: "breakdown",
    size: "third",
    title: null,
    options: { dimension: "acquisition_year", measure: "count", top_n: 8, tag: null, set_id: null },
  },
  {
    id: "d-8",
    type: "breakdown",
    size: "third",
    title: null,
    options: { dimension: "grade", measure: "count", top_n: 8, tag: null, set_id: null },
  },
  { id: "d-9", type: "notes_by_signature", size: "full", title: null, options: {} },
  { id: "d-10", type: "unrealized_movers", size: "full", title: null, options: { top_n: 5 } },
  { id: "d-11", type: "realized_gains", size: "full", title: null, options: { top_n: 20 } },
];
