import { ReactNode, useState } from "react";
import { Link } from "react-router-dom";

import {
  CalendarReference,
  certLookupUrl,
  ItemDetail,
  ItemType,
  money,
  SerialTrait,
  TROY_OUNCE_G,
} from "../api";
import { TraitBadges } from "./serial-traits";

/** "AH 1340", "Showa 12": the year as written, with its calendar's short name. */
function struckDate(item: ItemDetail, reference: CalendarReference | null): string {
  if (item.struck_calendar === "japanese") {
    const era = reference?.eras.find((e) => e.key === item.struck_era)?.label ?? item.struck_era;
    return `${era ?? "Japanese era"} ${item.struck_year}`;
  }
  const label = reference?.calendars.find((c) => c.key === item.struck_calendar)?.label;
  const short = label?.match(/\(([^)]+)\)\s*$/)?.[1] ?? label ?? item.struck_calendar;
  return `${short} ${item.struck_year}`;
}

const dieAxis = (degrees: number) =>
  degrees === 0
    ? "Medal alignment (0°)"
    : degrees === 180
      ? "Coin alignment (180°)"
      : `${degrees}°`;

const date = (iso: string) => new Date(iso).toLocaleDateString();
const count = (n: number) => n.toLocaleString();

const strikeLabel = (item: ItemDetail) =>
  item.strike === "business" ? null : item.strike === "proof" ? "Proof" : "Specimen";

interface Fact {
  label: string;
  /** Empty when null, undefined, or "": the field is left out unless every
   * field is being shown. */
  value: ReactNode;
  /** A quiet second line under the value. */
  note?: ReactNode;
  /** Offered as an empty field only for this kind (or these kinds) of piece. */
  forType?: ItemType | ItemType[];
  /** Already in the hero: a group holding nothing else isn't worth a block. */
  inHero?: boolean;
}

interface Group {
  title: string;
  facts: Fact[];
}

const filled = (value: ReactNode) => value !== null && value !== undefined && value !== "";

const STORE_KEY = "cabinet.item.showEmpty";

const remembered = () => {
  try {
    return window.localStorage.getItem(STORE_KEY) === "true";
  } catch {
    return false;
  }
};

/** Everything known about a piece, in titled groups. A group and a field only
 * appear when there is something to show, unless "Show empty fields" is on. */
export function ItemFacts({
  item,
  calendars,
  traitReference,
}: {
  item: ItemDetail;
  calendars: CalendarReference | null;
  traitReference: SerialTrait[];
}) {
  const [showEmpty, setShowEmpty] = useState(remembered);

  const toggle = () => {
    const next = !showEmpty;
    setShowEmpty(next);
    try {
      window.localStorage.setItem(STORE_KEY, String(next));
    } catch {
      // a browser that refuses storage still gets the choice for this visit
    }
  };

  const certUrl = certLookupUrl(item.cert_service, item.cert_number);
  const population = [
    item.pcgs_population != null && `${count(item.pcgs_population)} at this grade`,
    item.pcgs_pop_higher != null && `${count(item.pcgs_pop_higher)} higher`,
  ]
    .filter(Boolean)
    .join(" · ");
  const size =
    item.width_mm != null && item.height_mm != null
      ? `${item.width_mm} × ${item.height_mm} mm`
      : item.width_mm != null
        ? `${item.width_mm} mm wide`
        : item.height_mm != null
          ? `${item.height_mm} mm tall`
          : null;

  const groups: Group[] = [
    {
      title: "Identity",
      facts: [
        { label: "Series", value: item.series },
        { label: "Variety", value: item.variety },
        {
          label: "Set / lot",
          value: item.set ? (
            <Link to={`/collection?set_id=${item.set.id}`}>{item.set.name}</Link>
          ) : null,
        },
        { label: "Strike", value: strikeLabel(item) },
        { label: "Mint mark", value: item.mint_mark, forType: "coin" },
        {
          label: item.type === "note" ? "Print run" : "Mintage",
          value: item.mintage != null ? count(item.mintage) : null,
          forType: ["coin", "note"],
        },
        {
          label: "Date as struck",
          value:
            item.struck_calendar && item.struck_year != null
              ? `${struckDate(item, calendars)} (${item.year_label})`
              : null,
          forType: "coin",
        },
        {
          label: item.type === "bullion" ? "Refiner or mint" : "Issuer",
          value: item.issuer,
          forType: ["note", "bullion"],
        },
        { label: "Charter number", value: item.charter_number, forType: "note" },
        {
          label: "Bank location",
          value: [item.bank_city, item.bank_state].filter(Boolean).join(", "),
          forType: "note",
        },
        { label: "Signatures", value: item.signatures, forType: "note" },
        {
          label: "Serial number",
          value:
            item.serial_number || item.serial_traits.length > 0 ? (
              <>
                {item.serial_number ?? "–"}{" "}
                <TraitBadges traits={item.serial_traits} reference={traitReference} />
              </>
            ) : null,
          forType: ["note", "bullion"],
        },
        { label: "Prefix / block", value: item.prefix_block, forType: "note" },
        { label: "Replacement note", value: item.replacement_note ? "Yes" : null, forType: "note" },
        { label: "Plate / position", value: item.plate_position, forType: "note" },
      ],
    },
    {
      title: "Grade & certification",
      facts: [
        {
          label: "Grade",
          value: item.grade ? `${item.grade_label} (${item.grade.label})` : null,
          inHero: true,
        },
        // The grade label above already carries these; on an ungraded piece
        // nothing else would show them.
        { label: "Details grade", value: item.grade ? null : item.grade_details },
        {
          label: "Designations",
          value: item.grade ? null : (item.designations ?? []).join(", "),
        },
        {
          label: "CAC",
          value: item.cac_sticker
            ? item.cac_sticker === "gold"
              ? "Gold sticker"
              : "Green sticker"
            : null,
          forType: "coin",
        },
        {
          label: "Certification",
          value: item.cert_service ? (
            <>
              {`${item.cert_service} ${item.cert_number ?? ""}`.trim()}
              {certUrl && (
                <>
                  {" "}
                  <a href={certUrl} target="_blank" rel="noreferrer"
                    title="Check this certification with the grading service">
                    verify ↗
                  </a>
                </>
              )}
            </>
          ) : null,
        },
        {
          label: "Population",
          value: population,
          note: (
            <div className="muted fact-note">
              PCGS{item.population_as_of && `, ${date(item.population_as_of)}`}
            </div>
          ),
          forType: "coin",
        },
      ],
    },
    {
      title: "Physical",
      facts: [
        { label: "Composition", value: item.composition },
        { label: "Weight", value: item.weight_g != null ? `${item.weight_g} g` : null },
        { label: "Fineness", value: item.fineness },
        {
          label: "Fine weight",
          value:
            item.fine_oz != null
              ? `${item.fine_oz.toLocaleString(undefined, {
                  minimumFractionDigits: 2,
                  maximumFractionDigits: 3,
                })} oz`
              : null,
          note:
            item.fine_oz != null ? (
              <div className="muted fact-note">{(item.fine_oz * TROY_OUNCE_G).toFixed(2)} g</div>
            ) : undefined,
        },
        {
          label: "Diameter",
          value: item.diameter_mm != null ? `${item.diameter_mm} mm` : null,
          forType: "coin",
        },
        {
          label: "Thickness",
          value: item.thickness_mm != null ? `${item.thickness_mm} mm` : null,
          forType: ["coin", "bullion"],
        },
        { label: "Size", value: size, forType: ["note", "bullion"] },
        { label: "Edge", value: item.edge, forType: "coin" },
        { label: "Shape", value: item.shape, forType: ["coin", "bullion"] },
        {
          label: "Die axis",
          value: item.die_axis != null ? dieAxis(item.die_axis) : null,
          forType: "coin",
        },
        { label: "Printer", value: item.printer, forType: "note" },
        { label: "Watermark", value: item.watermark, forType: "note" },
        {
          label: "Demonetised",
          value: item.demonetized_on ? date(item.demonetized_on) : null,
          forType: ["coin", "note"],
        },
      ],
    },
    {
      title: "Acquisition",
      facts: [
        { label: "Acquired", value: item.acquisition_date },
        {
          label: "Paid",
          value:
            item.acquisition_price != null
              ? money(item.acquisition_price, item.currency)
              : null,
        },
        {
          label: "Fees, shipping & tax",
          value:
            item.acquisition_fees != null
              ? money(item.acquisition_fees, item.currency)
              : null,
        },
        // Only worth its own line once fees make it differ from what was paid.
        {
          label: "Cost basis",
          value:
            item.acquisition_fees != null ? money(item.cost_basis, item.currency) : null,
        },
        { label: "From", value: item.acquired_from },
        {
          label: "Spot at purchase",
          value:
            item.spot_at_purchase != null
              ? `${money(item.spot_at_purchase, item.currency)} / oz`
              : null,
          note:
            item.spot_at_purchase_source === "auto" ? (
              <div className="muted fact-note">looked up for the purchase date</div>
            ) : undefined,
        },
        {
          label: "Premium over spot",
          value:
            item.premium_paid_pct != null
              ? `${item.premium_paid_pct > 0 ? "+" : ""}${item.premium_paid_pct.toFixed(1)}%`
              : null,
        },
        { label: "Storage", value: item.storage_location },
        { label: "Sold to / venue", value: item.status === "sold" ? item.sold_to : null },
        {
          label: "Selling fees",
          value:
            item.status === "sold" && item.sold_fees != null
              ? money(item.sold_fees, item.currency)
              : null,
        },
        {
          label: "Net proceeds",
          value:
            item.status === "sold" && item.sold_fees != null
              ? money(item.sale_proceeds, item.currency)
              : null,
        },
      ],
    },
    {
      title: "Custom fields",
      facts: Object.entries(item.custom_fields ?? {}).map(([label, value]) => ({ label, value })),
    },
  ];

  const forTypeMatches = (forType?: ItemType | ItemType[]) =>
    !forType || (Array.isArray(forType) ? forType.includes(item.type) : forType === item.type);

  const offered = (fact: Fact) => filled(fact.value) || (showEmpty && forTypeMatches(fact.forType));

  const blocks = groups
    .map((group) => ({ title: group.title, facts: group.facts.filter(offered) }))
    .filter((group) => group.facts.some((fact) => showEmpty || !fact.inHero));

  return (
    <div className="card item-facts">
      {blocks.length === 0 && (
        <p className="muted" style={{ margin: 0 }}>
          Nothing recorded beyond the title yet. <Link to={`/items/${item.id}/edit`}>Edit</Link> to
          fill it in.
        </p>
      )}
      {blocks.map((group) => (
        <section className="fact-group" key={group.title}>
          <h3>{group.title}</h3>
          <dl className="facts">
            {group.facts.map((fact) => (
              <div key={fact.label}>
                <dt>{fact.label}</dt>
                <dd>
                  {filled(fact.value) ? fact.value : "–"}
                  {filled(fact.value) && fact.note}
                </dd>
              </div>
            ))}
          </dl>
        </section>
      ))}
      <button type="button" className="link-button fact-toggle" onClick={toggle}>
        {showEmpty ? "Hide empty fields" : "Show empty fields"}
      </button>
    </div>
  );
}
