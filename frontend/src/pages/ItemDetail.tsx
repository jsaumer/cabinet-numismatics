import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import {
  api,
  CalendarReference,
  certLookupUrl,
  ItemDetail as ItemDetailData,
  ItemEvent,
  money,
  PRIORITY_LABELS,
  SourceStatus,
} from "../api";
import { DocumentsCard } from "../components/documents";
import { LookupLinks } from "../components/lookup";
import { PhotoGallery } from "../components/photo-gallery";
import { latestBySource, timeSince } from "../components/provenance";
import { SalesLog } from "../components/sales";
import { TraitBadges, useSerialTraits } from "../components/serial-traits";
import { ValueHistory } from "../components/value-history";

/** "AH 1340", "Showa 12": the year as written, with its calendar's short name. */
function struckDate(item: ItemDetailData, reference: CalendarReference | null): string {
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

export default function ItemDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [item, setItem] = useState<ItemDetailData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [events, setEvents] = useState<ItemEvent[] | null>(null);
  const [sources, setSources] = useState<SourceStatus[]>([]);
  const [numistaSales, setNumistaSales] = useState(false);
  const [calendars, setCalendars] = useState<CalendarReference | null>(null);
  const traitReference = useSerialTraits();
  const struckCalendar = item?.struck_calendar ?? null;

  // Calendar names, only for a piece dated in one.
  useEffect(() => {
    if (struckCalendar) api.calendars().then(setCalendars).catch(() => setCalendars(null));
  }, [struckCalendar]);

  // Which automatic sources this build offers, and whether they're switched on.
  useEffect(() => {
    api
      .getSettings()
      .then((s) => {
        setSources(s.sources);
        setNumistaSales(s.numista_sales_enabled);
      })
      .catch(() => setSources([]));
  }, []);

  const loadHistory = () => {
    if (!id) return;
    api.itemHistory(id).then(setEvents).catch(() => setEvents([]));
  };

  const reload = useCallback(() => {
    if (!id) return;
    api.getItem(id).then(setItem).catch((e: Error) => setError(e.message));
  }, [id]);

  useEffect(reload, [reload]);

  if (error) return <p className="error">{error}</p>;
  if (!item) return <p className="muted">Loading…</p>;

  async function cloneItem() {
    if (!id) return;
    try {
      const copy = await api.cloneItem(id);
      navigate(`/items/${copy.id}/edit`);
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function deleteItem() {
    if (!id || !window.confirm("Move this item to the trash? You can restore it from there.")) return;
    try {
      await api.deleteItem(id);
      navigate("/collection");
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function restoreItem() {
    if (!id) return;
    try {
      await api.restoreItem(id);
      reload();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function purgeItem() {
    if (
      !id ||
      !window.confirm(
        "Delete this item for good? Its photos, values, and history go too; this can't be undone.",
      )
    )
      return;
    try {
      await api.deleteItem(id, true);
      navigate("/trash");
    } catch (err) {
      setError((err as Error).message);
    }
  }

  const sourceValues = latestBySource(item.estimates);
  const certUrl = certLookupUrl(item.cert_service, item.cert_number);

  const fact = (label: string, value: string | number | null | undefined) => (
    <div>
      <dt>{label}</dt>
      <dd>{value == null || value === "" ? "–" : value}</dd>
    </div>
  );

  return (
    <>
      <div className="detail-header">
        <h1>
          {item.country} {item.denomination}, {item.year_label}
          {item.mint_mark ? ` "${item.mint_mark}"` : ""}
        </h1>
        <span className={`badge ${item.type}`}>{item.type}</span>
        {item.status !== "owned" && (
          <span className={`badge status-${item.status}`}>{item.status}</span>
        )}
        {item.deleted_at && <span className="badge status-sold">in trash</span>}
        <div className="spacer" />
        {item.deleted_at ? (
          <>
            <button className="primary" onClick={restoreItem}>Restore</button>
            <button className="danger" onClick={purgeItem}>Delete for good</button>
          </>
        ) : (
          <>
            <button onClick={cloneItem}>Clone</button>
            <Link className="button" to={`/items/${item.id}/edit`}>Edit</Link>
            <button className="danger" onClick={deleteItem}>Delete</button>
          </>
        )}
      </div>
      {item.deleted_at && (
        <p className="trash-banner">
          This item is in the <Link to="/trash">trash</Link> since{" "}
          {new Date(item.deleted_at).toLocaleDateString()}. Restore it to edit it again.
        </p>
      )}
      <fieldset className="plain-fieldset" disabled={item.deleted_at !== null}>

      <div className="card">
        <dl className="facts">
          {fact("Series", item.series)}
          {fact("Variety", item.variety)}
          <div>
            <dt>Set / lot</dt>
            <dd>
              {item.set ? <Link to={`/collection?set_id=${item.set.id}`}>{item.set.name}</Link> : "–"}
            </dd>
          </div>
          {fact("Grade", item.grade ? `${item.grade_label} (${item.grade.label})` : null)}
          {(item.pcgs_population != null || item.pcgs_pop_higher != null) && (
            <div>
              <dt>Population</dt>
              <dd>
                {[
                  item.pcgs_population != null &&
                    `${item.pcgs_population.toLocaleString()} at this grade`,
                  item.pcgs_pop_higher != null &&
                    `${item.pcgs_pop_higher.toLocaleString()} higher`,
                ]
                  .filter(Boolean)
                  .join(" · ")}
                <div className="muted fact-note">
                  PCGS
                  {item.population_as_of &&
                    `, ${new Date(item.population_as_of).toLocaleDateString()}`}
                </div>
              </dd>
            </div>
          )}
          {item.strike !== "business" &&
            fact("Strike", item.strike === "proof" ? "Proof" : "Specimen")}
          {item.cac_sticker &&
            fact("CAC", item.cac_sticker === "gold" ? "Gold sticker" : "Green sticker")}
          <div>
            <dt>Certification</dt>
            <dd>
              {item.cert_service ? `${item.cert_service} ${item.cert_number ?? ""}`.trim() : "–"}
              {certUrl && (
                <>
                  {" "}
                  <a href={certUrl} target="_blank" rel="noreferrer"
                    title="Check this certification with the grading service">
                    verify ↗
                  </a>
                </>
              )}
            </dd>
          </div>
          {item.struck_calendar && item.struck_year != null &&
            fact("Date as struck", `${struckDate(item, calendars)} (${item.year_label})`)}
          {fact("Composition", item.composition)}
          {item.type === "coin" &&
            fact("Weight", item.weight_g != null ? `${item.weight_g} g` : null)}
          {item.type === "coin" && fact("Fineness", item.fineness)}
          {item.diameter_mm != null && fact("Diameter", `${item.diameter_mm} mm`)}
          {item.thickness_mm != null && fact("Thickness", `${item.thickness_mm} mm`)}
          {item.edge && fact("Edge", item.edge)}
          {item.shape && fact("Shape", item.shape)}
          {item.die_axis != null && fact("Die axis", dieAxis(item.die_axis))}
          {item.mintage != null &&
            fact(item.type === "note" ? "Print run" : "Mintage", item.mintage.toLocaleString())}
          {(item.serial_number || (item.serial_traits ?? []).length > 0) && (
            <div>
              <dt>Serial number</dt>
              <dd>
                {item.serial_number ?? "–"}{" "}
                <TraitBadges traits={item.serial_traits} reference={traitReference} />
              </dd>
            </div>
          )}
          {item.prefix_block && fact("Prefix / block", item.prefix_block)}
          {item.signatures && fact("Signatures", item.signatures)}
          {item.issuer && fact("Issuer", item.issuer)}
          {item.charter_number && fact("Charter number", item.charter_number)}
          {(item.bank_city || item.bank_state) &&
            fact("Bank location", [item.bank_city, item.bank_state].filter(Boolean).join(", "))}
          {item.plate_position && fact("Plate / position", item.plate_position)}
          {item.replacement_note && fact("Replacement note", "Yes")}
          {fact("Quantity", item.quantity)}
          {fact("Acquired", item.acquisition_date)}
          {fact("Paid", money(item.acquisition_price, item.currency))}
          {item.acquisition_fees != null &&
            fact("Fees, shipping & tax", money(item.acquisition_fees, item.currency))}
          {item.acquisition_fees != null &&
            fact("Cost basis", money(item.cost_basis, item.currency))}
          {fact("From", item.acquired_from)}
          {fact("Storage", item.storage_location)}
          {item.priority != null && fact("Priority", PRIORITY_LABELS[item.priority])}
          {item.target_price != null && (
            <div>
              <dt>Target</dt>
              <dd>
                {money(item.target_price, item.currency)}
                {item.target_gap != null && (
                  <div className={item.target_gap <= 0 ? "gain fact-note" : "muted fact-note"}>
                    {item.target_gap === 0
                      ? "at target"
                      : `${money(Math.abs(item.target_gap), item.currency)} ${
                          item.target_gap < 0 ? "under" : "over"
                        } target`}
                  </div>
                )}
              </dd>
            </div>
          )}
          {item.status === "sold" && fact("Sold on", item.sold_date)}
          {item.status === "sold" && fact("Sold for", money(item.sold_price, item.currency))}
          {item.status === "sold" && item.sold_fees != null &&
            fact("Selling fees", money(item.sold_fees, item.currency))}
          {item.status === "sold" && item.sold_fees != null &&
            fact("Net proceeds", money(item.sale_proceeds, item.currency))}
          {item.status === "sold" && item.sold_to && fact("Sold to / venue", item.sold_to)}
          <div style={{ gridColumn: "1 / -1" }}>
            <dt>Latest value</dt>
            <dd>
              {sourceValues.length === 0 && "–"}
              {sourceValues.length === 1 && (
                <>
                  {money(sourceValues[0][1].estimated_value, sourceValues[0][1].currency)}{" "}
                  <span className="muted">({timeSince(sourceValues[0][1].fetched_at)})</span>
                </>
              )}
              {sourceValues.length > 1 && (
                <div className="chip-row">
                  {sourceValues.map(([key, est]) => (
                    <span key={key} className="chip">
                      {key}: {money(est.estimated_value, est.currency)}{" "}
                      <span className="muted">({timeSince(est.fetched_at)})</span>
                    </span>
                  ))}
                </div>
              )}
            </dd>
          </div>
          {Object.entries(item.custom_fields ?? {}).map(([key, value]) => (
            <div key={key}><dt>{key}</dt><dd>{value}</dd></div>
          ))}
        </dl>
        {(item.tags.length > 0 || item.catalog_refs.length > 0) && (
          <p style={{ marginBottom: 0 }}>
            {item.tags.map((t) => (
              <Link key={t} className="chip" to={`/collection?tag=${encodeURIComponent(t)}`}>{t}</Link>
            ))}
            {item.catalog_refs.map((r) => (
              <span key={`${r.catalog}:${r.ref_code}`} className="chip ref">
                {r.catalog}: {r.ref_code}
              </span>
            ))}
          </p>
        )}
        {item.notes && <p style={{ marginBottom: 0, whiteSpace: "pre-wrap" }}>{item.notes}</p>}
        <LookupLinks item={item} />
      </div>

      <PhotoGallery item={item} onChanged={reload} />

      <DocumentsCard item={item} onChanged={reload} />

      <ValueHistory item={item} sources={sources} onChanged={reload} />

      <SalesLog
        item={item}
        compsEnabled={sources.some((s) => s.key === "comps" && s.enabled)}
        numistaSales={numistaSales}
        onChanged={reload}
      />

      <details className="history" onToggle={(e) => e.currentTarget.open && loadHistory()}>
        <summary>Edit history</summary>
        {events === null && <p className="muted">Loading…</p>}
        {events && events.length === 0 && <p className="muted">No history recorded.</p>}
        {events?.map((event) => (
          <div className="history-entry" key={event.id}>
            <span className="muted">{new Date(event.at).toLocaleString()}</span>: {event.action}
            {event.changes && (
              <>
                {": "}
                {Object.entries(event.changes).map(([field, [from, to]]) => (
                  <span key={field}>
                    <code>{field}</code>{" "}
                    <span className="muted">
                      {JSON.stringify(from)} → {JSON.stringify(to)}
                    </span>{" "}
                  </span>
                ))}
              </>
            )}
          </div>
        ))}
      </details>
      </fieldset>
    </>
  );
}
