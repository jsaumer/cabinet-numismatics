import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { api, ItemPage, money, photoUrl } from "../api";

const PAGE_SIZE = 50;

const SORTS = [
  { value: "-created_at", label: "Newest first" },
  { value: "created_at", label: "Oldest first" },
  { value: "year", label: "Year ↑" },
  { value: "-year", label: "Year ↓" },
  { value: "country", label: "Country A–Z" },
  { value: "-acquisition_price", label: "Paid ↓" },
];

export default function ItemList() {
  const navigate = useNavigate();
  const [type, setType] = useState("");
  const [country, setCountry] = useState("");
  const [year, setYear] = useState("");
  const [q, setQ] = useState("");
  const [sort, setSort] = useState("-created_at");
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<ItemPage | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const params = new URLSearchParams({ sort, limit: String(PAGE_SIZE), offset: String(offset) });
    if (type) params.set("type", type);
    if (country) params.set("country", country);
    if (year) params.set("year", year);
    if (q) params.set("q", q);
    const timer = setTimeout(() => {
      api.listItems(params).then(setPage).catch((e: Error) => setError(e.message));
    }, 250); // debounce text input
    return () => clearTimeout(timer);
  }, [type, country, year, q, sort, offset]);

  const resetOffset = () => setOffset(0);

  return (
    <>
      <div className="toolbar">
        <label className="field">
          Type
          <select value={type} onChange={(e) => { setType(e.target.value); resetOffset(); }}>
            <option value="">All</option>
            <option value="coin">Coins</option>
            <option value="note">Notes</option>
          </select>
        </label>
        <label className="field">
          Country
          <input value={country} placeholder="e.g. Canada"
            onChange={(e) => { setCountry(e.target.value); resetOffset(); }} />
        </label>
        <label className="field">
          Year
          <input value={year} type="number" style={{ width: "6rem" }}
            onChange={(e) => { setYear(e.target.value); resetOffset(); }} />
        </label>
        <label className="field">
          Search
          <input value={q} placeholder="notes, series…"
            onChange={(e) => { setQ(e.target.value); resetOffset(); }} />
        </label>
        <label className="field">
          Sort
          <select value={sort} onChange={(e) => { setSort(e.target.value); resetOffset(); }}>
            {SORTS.map((s) => (
              <option key={s.value} value={s.value}>{s.label}</option>
            ))}
          </select>
        </label>
        <div className="spacer" />
        <a className="button" href="/api/items/export.csv">Export CSV</a>
        <Link className="button primary" to="/items/new">Add item</Link>
      </div>

      {error && <p className="error">{error}</p>}

      {page && page.items.length === 0 && (
        <div className="empty">
          {page.total === 0 && !type && !country && !year && !q
            ? "No items yet — add the first piece of your collection."
            : "Nothing matches these filters."}
        </div>
      )}

      {page && page.items.length > 0 && (
        <table className="items">
          <thead>
            <tr>
              <th></th>
              <th>Type</th>
              <th>Country</th>
              <th>Denomination</th>
              <th>Year</th>
              <th>Series</th>
              <th className="num">Qty</th>
              <th className="num">Paid</th>
              <th className="num">Value</th>
            </tr>
          </thead>
          <tbody>
            {page.items.map((item) => (
              <tr key={item.id} onClick={() => navigate(`/items/${item.id}`)}>
                <td style={{ width: "52px" }}>
                  {item.primary_photo_key ? (
                    <img className="thumb" src={photoUrl(item.primary_photo_key)} alt="" />
                  ) : (
                    <div className="thumb placeholder">{item.type === "coin" ? "◎" : "▭"}</div>
                  )}
                </td>
                <td><span className={`badge ${item.type}`}>{item.type}</span></td>
                <td>{item.country}</td>
                <td>
                  {item.denomination}
                  {item.mint_mark && <span className="muted"> · {item.mint_mark}</span>}
                </td>
                <td>{item.year}</td>
                <td className="muted">{item.series ?? ""}</td>
                <td className="num">{item.quantity}</td>
                <td className="num">{money(item.acquisition_price, item.currency)}</td>
                <td className="num">{money(item.latest_value, item.latest_value_currency)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {page && page.total > PAGE_SIZE && (
        <div className="pagination">
          <button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>
            ← Prev
          </button>
          <span className="muted">
            {offset + 1}–{Math.min(offset + PAGE_SIZE, page.total)} of {page.total}
          </span>
          <button
            disabled={offset + PAGE_SIZE >= page.total}
            onClick={() => setOffset(offset + PAGE_SIZE)}
          >
            Next →
          </button>
        </div>
      )}
    </>
  );
}
