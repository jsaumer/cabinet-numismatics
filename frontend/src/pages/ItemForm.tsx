import { FormEvent, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { api, CatalogRef, Grade, gradeScaleFor, ItemPayload, ItemStatus, ItemType } from "../api";

const EMPTY = {
  type: "coin" as ItemType,
  status: "owned" as ItemStatus,
  country: "",
  denomination: "",
  year: "",
  mint_mark: "",
  series: "",
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

function toPayload(form: FormState, refs: CatalogRef[]): ItemPayload {
  return {
    type: form.type,
    status: form.status,
    country: form.country.trim(),
    denomination: form.denomination.trim(),
    year: Number(form.year),
    mint_mark: opt(form.mint_mark),
    series: opt(form.series),
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
  const [grades, setGrades] = useState<Grade[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api.listGrades(gradeScaleFor(form.type)).then(setGrades).catch(() => setGrades([]));
  }, [form.type]);

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
      })
      .catch((e: Error) => setError(e.message));
  }, [id]);

  const set = (field: keyof FormState) => (value: string) =>
    setForm((f) => ({ ...f, [field]: value }));

  const setRef = (index: number, field: keyof CatalogRef, value: string) =>
    setRefs((rs) => rs.map((r, i) => (i === index ? { ...r, [field]: value } : r)));

  async function submit(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const payload = toPayload(form, refs);
      const saved = id ? await api.updateItem(id, payload) : await api.createItem(payload);
      navigate(`/items/${saved.id}`);
    } catch (err) {
      setError((err as Error).message);
      setSaving(false);
    }
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
      <form onSubmit={submit}>
        <div className="card">
          <h2>Identity</h2>
          <div className="item-form">
            <label className="field">
              Type
              <select value={form.type} onChange={(e) => set("type")(e.target.value)}>
                <option value="coin">Coin</option>
                <option value="note">Note</option>
              </select>
            </label>
            {text("country", "Country *", { required: true })}
            {text("denomination", "Denomination *", { required: true, placeholder: 'e.g. "25 cents"' })}
            {text("year", "Year *", { required: true, type: "number" })}
            {text("mint_mark", "Mint mark")}
            {text("series", "Series / variety")}
            {text("quantity", "Quantity", { type: "number", min: 1 })}
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
          <button type="button" onClick={() => navigate(-1)}>Cancel</button>
        </div>
      </form>
    </>
  );
}
