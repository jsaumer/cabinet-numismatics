import { FormEvent, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import {
  api,
  CatalogRef,
  Grade,
  gradeScaleFor,
  ItemPayload,
  ItemStatus,
  ItemType,
  SetInfo,
} from "../api";

const EMPTY = {
  type: "coin" as ItemType,
  status: "owned" as ItemStatus,
  country: "",
  denomination: "",
  year: "",
  mint_mark: "",
  series: "",
  variety: "",
  set_id: "",
  composition: "",
  weight_g: "",
  fineness: "",
  grade_id: "",
  cert_service: "",
  cert_number: "",
  quantity: "1",
  acquisition_date: "",
  acquisition_price: "",
  currency: "USD",
  acquired_from: "",
  storage_location: "",
  sold_date: "",
  sold_price: "",
  notes: "",
  tags: "",
};

type FormState = typeof EMPTY;

const opt = (v: string) => v.trim() || null;
const optNum = (v: string) => (v === "" ? null : Number(v));

function toPayload(
  form: FormState,
  refs: CatalogRef[],
  fields: { key: string; value: string }[],
): ItemPayload {
  const custom: Record<string, string> = {};
  for (const f of fields) {
    if (f.key.trim()) custom[f.key.trim()] = f.value;
  }
  return {
    type: form.type,
    status: form.status,
    country: form.country.trim(),
    denomination: form.denomination.trim(),
    year: Number(form.year),
    mint_mark: opt(form.mint_mark),
    series: opt(form.series),
    variety: opt(form.variety),
    set_id: form.set_id === "" ? null : Number(form.set_id),
    custom_fields: Object.keys(custom).length ? custom : null,
    composition: opt(form.composition),
    weight_g: optNum(form.weight_g),
    fineness: optNum(form.fineness),
    grade_id: form.grade_id === "" ? null : Number(form.grade_id),
    cert_service: opt(form.cert_service),
    cert_number: opt(form.cert_number),
    quantity: Number(form.quantity),
    acquisition_date: form.acquisition_date || null,
    acquisition_price: optNum(form.acquisition_price),
    currency: form.currency.trim().toUpperCase(),
    acquired_from: opt(form.acquired_from),
    storage_location: opt(form.storage_location),
    sold_date: form.status === "sold" ? form.sold_date || null : null,
    sold_price: form.status === "sold" ? optNum(form.sold_price) : null,
    notes: opt(form.notes),
    tags: form.tags.split(",").map((t) => t.trim()).filter(Boolean),
    catalog_refs: refs.filter((r) => r.catalog.trim() && r.ref_code.trim()),
  };
}

export default function ItemForm() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [form, setForm] = useState<FormState>(EMPTY);
  const [refs, setRefs] = useState<CatalogRef[]>([]);
  const [customFields, setCustomFields] = useState<{ key: string; value: string }[]>([]);
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

  useEffect(() => {
    if (!id) return;
    api
      .getItem(id)
      .then((item) => {
        setForm({
          type: item.type,
          status: item.status,
          country: item.country,
          denomination: item.denomination,
          year: String(item.year),
          mint_mark: item.mint_mark ?? "",
          series: item.series ?? "",
          variety: item.variety ?? "",
          set_id: item.set ? String(item.set.id) : "",
          composition: item.composition ?? "",
          weight_g: item.weight_g == null ? "" : String(item.weight_g),
          fineness: item.fineness == null ? "" : String(item.fineness),
          grade_id: item.grade ? String(item.grade.id) : "",
          cert_service: item.cert_service ?? "",
          cert_number: item.cert_number ?? "",
          quantity: String(item.quantity),
          acquisition_date: item.acquisition_date ?? "",
          acquisition_price: item.acquisition_price == null ? "" : String(item.acquisition_price),
          currency: item.currency,
          acquired_from: item.acquired_from ?? "",
          storage_location: item.storage_location ?? "",
          sold_date: item.sold_date ?? "",
          sold_price: item.sold_price == null ? "" : String(item.sold_price),
          notes: item.notes ?? "",
          tags: item.tags.join(", "),
        });
        setRefs(item.catalog_refs);
        setCustomFields(
          Object.entries(item.custom_fields ?? {}).map(([key, value]) => ({ key, value })),
        );
      })
      .catch((e: Error) => setError(e.message));
  }, [id]);

  const set = (field: keyof FormState) => (value: string) =>
    setForm((f) => ({ ...f, [field]: value }));

  const setRef = (index: number, field: keyof CatalogRef, value: string) =>
    setRefs((rs) => rs.map((r, i) => (i === index ? { ...r, [field]: value } : r)));

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

  const text = (field: keyof FormState, label: string, props: object = {}) => (
    <label className="field">
      {label}
      <input value={form[field]} onChange={(e) => set(field)(e.target.value)} {...props} />
    </label>
  );

  return (
    <>
      <div className="detail-header">
        <h1>{id ? "Edit item" : "Add item"}</h1>
      </div>
      {error && <p className="error">{error}</p>}
      {savedNote && <p className="muted">{savedNote}</p>}
      <form onSubmit={submit}>
        <div className="card">
          <h2>Identity</h2>
          <div className="item-form">
            <label className="field">
              Type
              <select
                value={form.type}
                onChange={(e) =>
                  // switching type switches grading scale — a grade from the
                  // other scale must not survive the switch
                  setForm((f) => ({ ...f, type: e.target.value as ItemType, grade_id: "" }))
                }
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
          <h2>Grading &amp; composition</h2>
          <div className="item-form">
            <label className="field">
              Grade ({gradeScaleFor(form.type)})
              <select value={form.grade_id} onChange={(e) => set("grade_id")(e.target.value)}>
                <option value="">ungraded</option>
                {grades.map((g) => (
                  <option key={g.id} value={g.id}>
                    {g.code} — {g.label}
                  </option>
                ))}
              </select>
            </label>
            {text("cert_service", "Cert service", { placeholder: "PCGS, NGC, PMG…" })}
            {text("cert_number", "Cert number")}
            {text("composition", "Composition", { placeholder: "e.g. 90% silver" })}
            {text("weight_g", "Weight (g)", { type: "number", step: "0.001", min: 0 })}
            {text("fineness", "Fineness", {
              type: "number", step: "0.0001", min: 0, max: 1, placeholder: "e.g. 0.900",
            })}
          </div>
        </div>

        <div className="card">
          <h2>Acquisition &amp; status</h2>
          <div className="item-form">
            {text("acquisition_date", "Acquired on", { type: "date" })}
            {text("acquisition_price", "Price paid", { type: "number", step: "0.01", min: 0 })}
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
