import { FormEvent, useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { api, CalendarReference, CatalogRef, Grade, gradeScaleFor, ItemType, SetInfo } from "../api";
import {
  CustomField,
  DESIGNATIONS,
  detectMetal,
  EDGES,
  EMPTY,
  FlagField,
  FormState,
  fromItem,
  inHistoricCoverage,
  PROBLEMS,
  SHAPES,
  TextField,
  toPayload,
} from "./item-form/model";
import { NumistaFill } from "./item-form/NumistaFill";
import { PcgsFill } from "./item-form/PcgsFill";
import { DuplicateWarning } from "../components/duplicates";

// Catalogues the reference rows suggest; any other name is accepted too.
const CATALOGS: Record<ItemType, string[]> = {
  coin: ["krause", "numista", "pcgs"],
  note: ["pick", "friedberg", "numista", "krause"],
};

export default function ItemForm() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [form, setForm] = useState<FormState>(EMPTY);
  const [refs, setRefs] = useState<CatalogRef[]>([]);
  const [customFields, setCustomFields] = useState<CustomField[]>([]);
  const [grades, setGrades] = useState<Grade[]>([]);
  const [sets, setSets] = useState<SetInfo[]>([]);
  const [countries, setCountries] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [savedNote, setSavedNote] = useState<string | null>(null);
  const [calendars, setCalendars] = useState<CalendarReference | null>(null);
  const [axisOther, setAxisOther] = useState(false);
  // The date as struck in Gregorian years, or why it couldn't be converted.
  const [converted, setConverted] = useState<number | null>(null);
  const [convertError, setConvertError] = useState<string | null>(null);
  const [spotBusy, setSpotBusy] = useState(false);
  const [spotError, setSpotError] = useState<string | null>(null);
  const autoYear = useRef(""); // the Year this form filled in itself, which it may replace

  useEffect(() => {
    api.calendars().then(setCalendars).catch(() => setCalendars(null));
  }, []);

  // Convert the date as struck (debounced). Year is filled only when empty,
  // or when it still holds an earlier conversion from this form.
  useEffect(() => {
    setConverted(null);
    setConvertError(null);
    const year = Number(form.struck_year);
    if (form.type !== "coin" || !form.struck_calendar || !(year > 0)) return;
    if (form.struck_calendar === "japanese" && !form.struck_era) return;
    let live = true;
    const timer = setTimeout(() => {
      api
        .convertDate(form.struck_calendar, year, form.struck_era || undefined)
        .then((r) => {
          if (!live) return;
          const gregorian = String(r.gregorian_year);
          setConverted(r.gregorian_year);
          setForm((f) => {
            if (f.year !== "" && f.year !== autoYear.current) return f;
            autoYear.current = gregorian;
            return { ...f, year: gregorian };
          });
        })
        .catch((e: Error) => live && setConvertError(e.message));
    }, 400);
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [form.type, form.struck_calendar, form.struck_year, form.struck_era]);

  useEffect(() => {
    api.listGrades(gradeScaleFor(form.type)).then(setGrades).catch(() => setGrades([]));
  }, [form.type]);

  useEffect(() => {
    api.listSets().then(setSets).catch(() => setSets([]));
    api
      .breakdowns()
      .then((b) => setCountries(b.by_country.map((e) => e.key)))
      .catch(() => setCountries([]));
  }, []);

  useEffect(() => {
    if (!id) return;
    api
      .getItem(id)
      .then((item) => {
        setForm(fromItem(item));
        setRefs(item.catalog_refs);
        setCustomFields(
          Object.entries(item.custom_fields ?? {}).map(([key, value]) => ({ key, value })),
        );
      })
      .catch((e: Error) => setError(e.message));
  }, [id]);

  async function newSet() {
    const name = window.prompt("New set name:");
    if (!name?.trim()) return;
    try {
      const created = await api.createSet(name.trim());
      setSets((s) => [...s, created]);
      setForm((f) => ({ ...f, set_id: String(created.id) }));
    } catch (e) {
      setError((e as Error).message);
    }
  }

  const set = (field: TextField) => (value: string) =>
    setForm((f) => ({ ...f, [field]: value }));

  async function lookUpSpot() {
    const metal = detectMetal(form.composition);
    if (!metal || !form.acquisition_date) return;
    setSpotBusy(true);
    setSpotError(null);
    try {
      const currency = form.currency.trim().toUpperCase() || "USD";
      const found = await api.historicSpot(metal, form.acquisition_date, currency);
      setForm((f) => ({ ...f, spot_at_purchase: String(found.per_oz) }));
    } catch (e) {
      setSpotError((e as Error).message);
    } finally {
      setSpotBusy(false);
    }
  }

  const setRef = (index: number, field: keyof CatalogRef, value: string) =>
    setRefs((rs) => rs.map((r, i) => (i === index ? { ...r, [field]: value } : r)));

  const toggleDesignation = (code: string) =>
    setForm((f) => ({
      ...f,
      designations: f.designations.includes(code)
        ? f.designations.filter((d) => d !== code)
        : [...f.designations, code],
    }));

  async function save(addAnother: boolean) {
    setSaving(true);
    setError(null);
    setSavedNote(null);
    try {
      const payload = toPayload(form, refs, customFields);
      const saved = id ? await api.updateItem(id, payload) : await api.createItem(payload);
      if (!addAnother) {
        navigate(`/items/${saved.id}`);
        return;
      }
      // keep the fields that tend to repeat during a bulk-entry session
      setForm((f) => ({
        ...EMPTY,
        type: f.type,
        country: f.country,
        currency: f.currency,
        acquisition_date: f.acquisition_date,
        acquired_from: f.acquired_from,
        storage_location: f.storage_location,
        set_id: f.set_id,
        composition: f.composition,
        fineness: f.fineness,
        tags: f.tags,
      }));
      setRefs([]);
      setCustomFields([]);
      setAxisOther(false);
      setSavedNote(`Added ${saved.country} ${saved.denomination}, ${saved.year_label}.`);
      window.scrollTo(0, 0);
      setSaving(false);
    } catch (err) {
      setError((err as Error).message);
      setSaving(false);
    }
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    save(false);
  }

  // A catalogue fill hands back the whole form plus references it didn't have.
  function applyFill(next: FormState, newRefs: CatalogRef[]) {
    setForm(next);
    if (newRefs.length) {
      setRefs((rs) => [...rs.filter((r) => r.catalog.trim() || r.ref_code.trim()), ...newRefs]);
    }
  }

  const text = (field: TextField, label: string, props: object = {}) => (
    <label className="field">
      {label}
      <input value={form[field]} onChange={(e) => set(field)(e.target.value)} {...props} />
    </label>
  );

  const flag = (field: FlagField, label: string, title?: string) => (
    <label className="slot" title={title}>
      <input
        type="checkbox"
        checked={form[field]}
        onChange={(e) => setForm((f) => ({ ...f, [field]: e.target.checked }))}
      />
      {label}
    </label>
  );

  // On the Sheldon scale a proof or specimen keeps the grade number and changes the prefix.
  const gradeCode = (g: Grade) =>
    g.scale === "sheldon" && form.strike !== "business"
      ? `${form.strike === "proof" ? "PR" : "SP"}-${g.rank}`
      : g.code;

  const isCoin = form.type === "coin";
  const metal = detectMetal(form.composition);
  const hasStruckDate = isCoin && form.struck_calendar !== "" && form.struck_year !== "";
  const axisChoice =
    axisOther || !["", "0", "180"].includes(form.die_axis) ? "other" : form.die_axis;

  return (
    <>
      <div className="detail-header">
        <h1>{id ? "Edit item" : "Add item"}</h1>
      </div>
      {error && <p className="error">{error}</p>}
      {savedNote && <p className="muted">{savedNote}</p>}
      <form onSubmit={submit}>
        <PcgsFill form={form} refs={refs} onApply={applyFill} />
        <NumistaFill form={form} refs={refs} onApply={applyFill} />
        <DuplicateWarning
          country={form.country}
          denomination={form.denomination}
          year={form.year}
          yearNd={form.year_nd}
          mintMark={form.mint_mark}
          certNumber={form.cert_number}
          refs={refs}
          excludeId={id}
        />

        <div className="card">
          <h2>Identity</h2>
          <div className="item-form">
            <label className="field">
              Type
              <select
                value={form.type}
                onChange={(e) => {
                  const type = e.target.value as ItemType;
                  // Switching type switches grading scale and designations; nothing
                  // from the other scale may survive the switch.
                  setForm((f) => ({
                    ...f,
                    type,
                    grade_id: "",
                    designations: [],
                    strike: type === "note" && f.strike === "proof" ? "business" : f.strike,
                  }));
                }}
              >
                <option value="coin">Coin</option>
                <option value="note">Note</option>
              </select>
            </label>
            {text("country", "Country *", { required: true, list: "country-options" })}
            <datalist id="country-options">
              {countries.map((c) => (
                <option key={c} value={c} />
              ))}
            </datalist>
            {text("denomination", "Denomination *", { required: true, placeholder: 'e.g. "25 cents"' })}
            {/* The ND box sits under the year it changes the meaning of. */}
            <div className="field">
              <label className="field">
                {form.year_nd ? "Attributed year" : hasStruckDate ? "Year" : "Year *"}
                <input
                  type="number"
                  required={!hasStruckDate && !form.year_nd}
                  value={form.year}
                  placeholder={form.year_nd ? "optional" : undefined}
                  title={
                    form.year_nd ? "The year it is known or believed to be from" : undefined
                  }
                  onChange={(e) => set("year")(e.target.value)}
                />
              </label>
              {flag("year_nd", "ND (no date on the piece)", "The piece carries no date")}
            </div>
            {isCoin && (
              <>
                <label className="field" title="For a date written in another calendar">
                  Date as struck: calendar
                  <select
                    value={form.struck_calendar}
                    onChange={(e) =>
                      setForm((f) => ({
                        ...f,
                        struck_calendar: e.target.value,
                        struck_era: e.target.value === "japanese" ? f.struck_era : "",
                      }))
                    }
                  >
                    <option value="">Gregorian</option>
                    {calendars?.calendars.map((c) => (
                      <option key={c.key} value={c.key}>{c.label}</option>
                    ))}
                  </select>
                </label>
                {form.struck_calendar !== "" && (
                  <>
                    {form.struck_calendar === "japanese" && (
                      <label className="field">
                        Era
                        <select value={form.struck_era} required
                          onChange={(e) => set("struck_era")(e.target.value)}>
                          <option value="">choose…</option>
                          {calendars?.eras.map((era) => (
                            <option key={era.key} value={era.key}>{era.label}</option>
                          ))}
                        </select>
                      </label>
                    )}
                    <label className="field">
                      Year as struck
                      <input type="number" min={1} max={9999} step={1} value={form.struck_year}
                        onChange={(e) => set("struck_year")(e.target.value)} />
                      {converted != null && <span className="muted">= {converted} CE</span>}
                      {convertError && <span className="muted">{convertError}</span>}
                    </label>
                  </>
                )}
              </>
            )}
            {text("mint_mark", "Mint mark")}
            {text("series", "Series")}
            {text("variety", "Variety / sub-type", { placeholder: "e.g. 1955 DDO, overdate" })}
            <label className="field">
              Strike
              <select value={form.strike} onChange={(e) => set("strike")(e.target.value)}>
                <option value="business">{isCoin ? "Business strike" : "Regular issue"}</option>
                {isCoin && <option value="proof">Proof</option>}
                <option value="specimen">Specimen</option>
              </select>
            </label>
            {text("quantity", "Quantity", { type: "number", min: 1 })}
            <label className="field">
              Set / lot
              <span style={{ display: "flex", gap: "0.3rem" }}>
                <select value={form.set_id} style={{ flex: 1 }}
                  onChange={(e) => set("set_id")(e.target.value)}>
                  <option value="">none</option>
                  {sets.map((s) => (
                    <option key={s.id} value={s.id}>{s.name}</option>
                  ))}
                </select>
                <button type="button" onClick={newSet} title="Create a new set">+</button>
              </span>
            </label>
          </div>
        </div>

        <div className="card">
          <h2>Grading &amp; certification</h2>
          <div className="item-form">
            <label className="field">
              Grade ({gradeScaleFor(form.type)})
              <select value={form.grade_id} onChange={(e) => set("grade_id")(e.target.value)}>
                <option value="">ungraded</option>
                {grades.map((g) => (
                  <option key={g.id} value={g.id}>
                    {gradeCode(g)}: {g.label}
                  </option>
                ))}
              </select>
            </label>
            {text("grade_details", "Details grade (problem)", {
              list: "problem-options",
              placeholder: "blank if problem-free",
            })}
            <datalist id="problem-options">
              {PROBLEMS[form.type].map((p) => (
                <option key={p} value={p} />
              ))}
            </datalist>
            {text("cert_service", "Cert service", { placeholder: "PCGS, NGC, PMG…" })}
            {text("cert_number", "Cert number")}
            {isCoin && (
              <>
                {text("pcgs_population", "PCGS population", {
                  type: "number", min: 0, step: 1, title: "Coins PCGS has graded at this grade",
                })}
                {text("pcgs_pop_higher", "Graded higher", {
                  type: "number", min: 0, step: 1, title: "Coins PCGS has graded higher",
                })}
              </>
            )}
            {isCoin && (
              <label className="field">
                CAC sticker
                <select value={form.cac_sticker} onChange={(e) => set("cac_sticker")(e.target.value)}>
                  <option value="">none</option>
                  <option value="green">Green</option>
                  <option value="gold">Gold</option>
                </select>
              </label>
            )}
            <div className="field full">
              Grade qualifiers
              <div className="chip-row">
                {flag("grade_plus", "Plus grade (+)")}
                {flag("grade_star", "Star (★)", "NGC or PMG star designation")}
              </div>
            </div>
            <div className="field full">
              Designations
              <div className="chip-row">
                {DESIGNATIONS[form.type].map(([code, meaning]) => (
                  <button
                    type="button"
                    key={code}
                    title={meaning}
                    className={form.designations.includes(code) ? "chip active" : "chip"}
                    onClick={() => toggleDesignation(code)}
                  >
                    {code}
                  </button>
                ))}
              </div>
            </div>
          </div>
        </div>

        <div className="card">
          <h2>{isCoin ? "Composition & physical" : "Note details"}</h2>
          <div className="item-form">
            {text("composition", "Composition", {
              placeholder: isCoin ? "e.g. 90% silver" : "e.g. paper, polymer",
            })}
            {isCoin && (
              <>
                {text("weight_g", "Weight (g)", { type: "number", step: "0.0001", min: 0 })}
                {text("fineness", "Fineness", {
                  type: "number", step: "0.0001", min: 0, max: 1, placeholder: "e.g. 0.900",
                })}
                {text("diameter_mm", "Diameter (mm)", { type: "number", step: "0.01", min: 0 })}
                {text("thickness_mm", "Thickness (mm)", { type: "number", step: "0.01", min: 0 })}
                {text("edge", "Edge", { list: "edge-options" })}
                <datalist id="edge-options">
                  {EDGES.map((v) => <option key={v} value={v} />)}
                </datalist>
                {text("shape", "Shape", { list: "shape-options" })}
                <datalist id="shape-options">
                  {SHAPES.map((v) => <option key={v} value={v} />)}
                </datalist>
                <label className="field">
                  Die axis
                  <select
                    value={axisChoice}
                    onChange={(e) => {
                      const choice = e.target.value;
                      setAxisOther(choice === "other");
                      set("die_axis")(choice === "other" ? "" : choice);
                    }}
                  >
                    <option value=""></option>
                    <option value="0">Medal alignment ↑↑ (0°)</option>
                    <option value="180">Coin alignment ↑↓ (180°)</option>
                    <option value="other">Other…</option>
                  </select>
                </label>
                {axisChoice === "other" &&
                  text("die_axis", "Die axis (degrees)", {
                    type: "number", min: 0, max: 359, step: 1,
                  })}
              </>
            )}
            {!isCoin && (
              <>
                {/* Width and height together: a note is measured both ways. */}
                <div className="field">
                  Size (mm)
                  <span className="size-pair">
                    <input
                      type="number" step="0.01" min={0} aria-label="Width (mm)" placeholder="width"
                      value={form.width_mm} onChange={(e) => set("width_mm")(e.target.value)}
                    />
                    <span className="muted">×</span>
                    <input
                      type="number" step="0.01" min={0} aria-label="Height (mm)" placeholder="height"
                      value={form.height_mm} onChange={(e) => set("height_mm")(e.target.value)}
                    />
                  </span>
                </div>
                {text("printer", "Printer", { maxLength: 200, placeholder: "e.g. BEP, De La Rue" })}
                {text("watermark", "Watermark", { maxLength: 200 })}
                {text("serial_number", "Serial number")}
                {text("prefix_block", "Prefix / block")}
                {text("signatures", "Signatures", { placeholder: "e.g. Coyne–Towers" })}
                {text("issuer", "Issuer", { placeholder: "issuing bank or authority" })}
                {text("charter_number", "Charter number", {
                  maxLength: 10, title: "National Bank Note charter",
                })}
                {text("bank_city", "Bank city", { maxLength: 100 })}
                {text("bank_state", "Bank state", { maxLength: 50 })}
                {text("plate_position", "Plate / position", {
                  maxLength: 20, title: "Plate and position letters",
                })}
              </>
            )}
            {text("mintage", isCoin ? "Mintage" : "Print run", { type: "number", min: 0, step: 1 })}
            {text("demonetized_on", "Demonetised on", {
              type: "date", title: "The date it stopped being legal tender",
            })}
            {!isCoin && (
              <div className="field">
                &nbsp;
                {flag("replacement_note", "Replacement / star note")}
              </div>
            )}
          </div>
        </div>

        <div className="card">
          <h2>Acquisition &amp; status</h2>
          <div className="item-form">
            {text("acquisition_date", "Acquired on", { type: "date" })}
            {text("acquisition_price", "Price paid", { type: "number", step: "0.01", min: 0 })}
            {text("acquisition_fees", "Fees, shipping & tax", {
              type: "number", step: "0.01", min: 0, title: "Counted in cost basis and gains",
            })}
            {metal && (
              <label className="field">
                Spot at purchase (per oz)
                <span style={{ display: "flex", gap: "0.3rem" }}>
                  <input
                    type="number" step="0.01" min={0} style={{ flex: 1 }}
                    value={form.spot_at_purchase}
                    onChange={(e) => set("spot_at_purchase")(e.target.value)}
                  />
                  <button
                    type="button"
                    disabled={spotBusy || !form.acquisition_date || !inHistoricCoverage(form.acquisition_date)}
                    title="The metal's spot price that day, per troy ounce. Looked up automatically for purchases from 2 March 2024."
                    onClick={lookUpSpot}
                  >
                    {spotBusy ? "Looking up…" : "Look up"}
                  </button>
                </span>
                {spotError && <span className="muted">{spotError}</span>}
              </label>
            )}
            {text("currency", "Currency", { maxLength: 3 })}
            {text("acquired_from", "Acquired from", { placeholder: "dealer, show, auction…" })}
            {text("storage_location", "Storage location", { placeholder: "album, slab box, safe…" })}
            <label className="field">
              Status
              <select value={form.status} onChange={(e) => set("status")(e.target.value)}>
                <option value="owned">Owned</option>
                <option value="sold">Sold</option>
                <option value="wishlist">Wishlist</option>
              </select>
            </label>
            {form.status === "wishlist" && (
              <>
                {text("target_price", "Target price", {
                  type: "number", step: "0.01", min: 0.01,
                  title: "In the item's currency; an estimate at or under it is flagged",
                })}
                <label className="field">
                  Priority
                  <select value={form.priority} onChange={(e) => set("priority")(e.target.value)}>
                    <option value=""></option>
                    <option value="1">High</option>
                    <option value="2">Medium</option>
                    <option value="3">Low</option>
                  </select>
                </label>
              </>
            )}
            {form.status === "sold" && (
              <>
                {text("sold_date", "Sold on", { type: "date" })}
                {text("sold_price", "Sold price", { type: "number", step: "0.01", min: 0 })}
                {text("sold_fees", "Selling fees", {
                  type: "number", step: "0.01", min: 0, title: "Commission, listing fees",
                })}
                {text("sold_to", "Sold to / venue", { placeholder: "buyer, auction house…" })}
              </>
            )}
          </div>
        </div>

        <div className="card">
          <h2>References &amp; notes</h2>
          <div className="item-form">
            {text("tags", "Tags (comma-separated)", { placeholder: "type set, silver, for sale" })}
            <div className="field full">
              Catalog references
              {refs.map((ref, i) => (
                <div className="ref-row" key={i}>
                  <input value={ref.catalog} list="catalog-options"
                    placeholder={isCoin ? "catalog (krause, numista…)" : "catalog (pick, friedberg…)"}
                    onChange={(e) => setRef(i, "catalog", e.target.value)} />
                  <input value={ref.ref_code} placeholder="reference code"
                    onChange={(e) => setRef(i, "ref_code", e.target.value)} />
                  <button type="button" title="Remove"
                    onClick={() => setRefs((rs) => rs.filter((_, j) => j !== i))}>
                    ✕
                  </button>
                </div>
              ))}
              <datalist id="catalog-options">
                {CATALOGS[form.type].map((c) => <option key={c} value={c} />)}
              </datalist>
              <div>
                <button type="button"
                  onClick={() => setRefs((rs) => [...rs, { catalog: "", ref_code: "" }])}>
                  + Add reference
                </button>
              </div>
            </div>
            <div className="field full">
              Custom fields
              {customFields.map((f, i) => (
                <div className="ref-row" key={i}>
                  <input value={f.key} placeholder="field name"
                    onChange={(e) => setCustomFields((cf) =>
                      cf.map((x, j) => (j === i ? { ...x, key: e.target.value } : x)))} />
                  <input value={f.value} placeholder="value"
                    onChange={(e) => setCustomFields((cf) =>
                      cf.map((x, j) => (j === i ? { ...x, value: e.target.value } : x)))} />
                  <button type="button" title="Remove"
                    onClick={() => setCustomFields((cf) => cf.filter((_, j) => j !== i))}>
                    ✕
                  </button>
                </div>
              ))}
              <div>
                <button type="button"
                  onClick={() => setCustomFields((cf) => [...cf, { key: "", value: "" }])}>
                  + Add field
                </button>
              </div>
            </div>
            <label className="field full">
              Notes
              <textarea rows={4} value={form.notes}
                onChange={(e) => set("notes")(e.target.value)} />
            </label>
          </div>
        </div>

        <div className="actions" style={{ marginBottom: "1.5rem" }}>
          <button className="primary" type="submit" disabled={saving}>
            {saving ? "Saving…" : id ? "Save changes" : "Add item"}
          </button>
          {!id && (
            <button type="button" disabled={saving}
              onClick={(e) => {
                const formEl = (e.target as HTMLElement).closest("form");
                if (formEl?.reportValidity()) save(true);
              }}>
              Save &amp; add another
            </button>
          )}
          <button type="button" onClick={() => navigate(-1)}>Cancel</button>
        </div>
      </form>
    </>
  );
}
