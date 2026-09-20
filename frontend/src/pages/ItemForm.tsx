import { FormEvent, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { api, CatalogRef, Grade, gradeScaleFor, ItemType, SetInfo } from "../api";
import {
  CustomField,
  DESIGNATIONS,
  EDGES,
  EMPTY,
  FlagField,
  FormState,
  fromItem,
  PROBLEMS,
  SHAPES,
  TextField,
  toPayload,
} from "./item-form/model";
import { NumistaFill } from "./item-form/NumistaFill";
import { PcgsFill } from "./item-form/PcgsFill";
import { DuplicateWarning } from "../components/duplicates";

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
      setSavedNote(`Added ${saved.country} ${saved.denomination}, ${saved.year}.`);
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
            {text("year", "Year *", { required: true, type: "number" })}
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
                {text("weight_g", "Weight (g)", { type: "number", step: "0.001", min: 0 })}
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
              </>
            )}
            {!isCoin && (
              <>
                {text("serial_number", "Serial number")}
                {text("prefix_block", "Prefix / block")}
                {text("signatures", "Signatures", { placeholder: "e.g. Coyne–Towers" })}
                {text("issuer", "Issuer", { placeholder: "issuing bank or authority" })}
              </>
            )}
            {text("mintage", isCoin ? "Mintage" : "Print run", { type: "number", min: 0, step: 1 })}
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
                  <input value={ref.catalog} placeholder="catalog (krause, numista…)"
                    onChange={(e) => setRef(i, "catalog", e.target.value)} />
                  <input value={ref.ref_code} placeholder="reference code"
                    onChange={(e) => setRef(i, "ref_code", e.target.value)} />
                  <button type="button" title="Remove"
                    onClick={() => setRefs((rs) => rs.filter((_, j) => j !== i))}>
                    ✕
                  </button>
                </div>
              ))}
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
