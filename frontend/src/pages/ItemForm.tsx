import { FormEvent, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { api, ItemPayload, ItemType } from "../api";

const EMPTY = {
  type: "coin" as ItemType,
  country: "",
  denomination: "",
  year: "",
  mint_mark: "",
  series: "",
  quantity: "1",
  acquisition_date: "",
  acquisition_price: "",
  currency: "USD",
  notes: "",
};

type FormState = typeof EMPTY;

function toPayload(form: FormState): ItemPayload {
  return {
    type: form.type,
    country: form.country.trim(),
    denomination: form.denomination.trim(),
    year: Number(form.year),
    mint_mark: form.mint_mark.trim() || null,
    series: form.series.trim() || null,
    quantity: Number(form.quantity),
    acquisition_date: form.acquisition_date || null,
    acquisition_price: form.acquisition_price === "" ? null : Number(form.acquisition_price),
    currency: form.currency.trim().toUpperCase(),
    notes: form.notes.trim() || null,
  };
}

export default function ItemForm() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [form, setForm] = useState<FormState>(EMPTY);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!id) return;
    api
      .getItem(id)
      .then((item) =>
        setForm({
          type: item.type,
          country: item.country,
          denomination: item.denomination,
          year: String(item.year),
          mint_mark: item.mint_mark ?? "",
          series: item.series ?? "",
          quantity: String(item.quantity),
          acquisition_date: item.acquisition_date ?? "",
          acquisition_price: item.acquisition_price == null ? "" : String(item.acquisition_price),
          currency: item.currency,
          notes: item.notes ?? "",
        }),
      )
      .catch((e: Error) => setError(e.message));
  }, [id]);

  const set = (field: keyof FormState) => (value: string) =>
    setForm((f) => ({ ...f, [field]: value }));

  async function submit(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const payload = toPayload(form);
      const saved = id ? await api.updateItem(id, payload) : await api.createItem(payload);
      navigate(`/items/${saved.id}`);
    } catch (err) {
      setError((err as Error).message);
      setSaving(false);
    }
  }

  return (
    <>
      <div className="detail-header">
        <h1>{id ? "Edit item" : "Add item"}</h1>
      </div>
      {error && <p className="error">{error}</p>}
      <div className="card">
        <form className="item-form" onSubmit={submit}>
          <label className="field">
            Type
            <select value={form.type} onChange={(e) => set("type")(e.target.value)}>
              <option value="coin">Coin</option>
              <option value="note">Note</option>
            </select>
          </label>
          <label className="field">
            Country *
            <input required value={form.country} onChange={(e) => set("country")(e.target.value)} />
          </label>
          <label className="field">
            Denomination *
            <input required value={form.denomination} placeholder='e.g. "25 cents"'
              onChange={(e) => set("denomination")(e.target.value)} />
          </label>
          <label className="field">
            Year *
            <input required type="number" value={form.year}
              onChange={(e) => set("year")(e.target.value)} />
          </label>
          <label className="field">
            Mint mark
            <input value={form.mint_mark} onChange={(e) => set("mint_mark")(e.target.value)} />
          </label>
          <label className="field">
            Series / variety
            <input value={form.series} onChange={(e) => set("series")(e.target.value)} />
          </label>
          <label className="field">
            Quantity
            <input type="number" min={1} value={form.quantity}
              onChange={(e) => set("quantity")(e.target.value)} />
          </label>
          <label className="field">
            Acquired on
            <input type="date" value={form.acquisition_date}
              onChange={(e) => set("acquisition_date")(e.target.value)} />
          </label>
          <label className="field">
            Price paid
            <input type="number" step="0.01" min={0} value={form.acquisition_price}
              onChange={(e) => set("acquisition_price")(e.target.value)} />
          </label>
          <label className="field">
            Currency
            <input value={form.currency} maxLength={3}
              onChange={(e) => set("currency")(e.target.value)} />
          </label>
          <label className="field full">
            Notes
            <textarea rows={4} value={form.notes} onChange={(e) => set("notes")(e.target.value)} />
          </label>
          <div className="actions">
            <button className="primary" type="submit" disabled={saving}>
              {saving ? "Saving…" : id ? "Save changes" : "Add item"}
            </button>
            <button type="button" onClick={() => navigate(-1)}>Cancel</button>
          </div>
        </form>
      </div>
    </>
  );
}
