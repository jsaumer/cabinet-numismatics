import { ChangeEvent, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { api, CollectionStats, ImportResult, ItemPage, money, photoUrl } from "../api";

const PAGE_SIZE = 50;

const SORTS = [
  { value: "-created_at", label: "Newest first" },
  { value: "created_at", label: "Oldest first" },
  { value: "year", label: "Year ↑" },
  { value: "-year", label: "Year ↓" },
  { value: "country", label: "Country A–Z" },
  { value: "-grade", label: "Grade ↓" },
  { value: "-acquisition_price", label: "Paid ↓" },
];

const FILTER_KEYS = [
  "type", "status", "country", "year", "q", "tag", "set_id",
  "year_min", "year_max", "grade_min", "grade_max", "value_min", "value_max",
] as const;

export default function ItemList() {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const [page, setPage] = useState<ItemPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showAdvanced, setShowAdvanced] = useState(
    ["year_min", "year_max", "grade_min", "grade_max", "value_min", "value_max"].some((k) =>
      params.has(k),
    ),
  );
  const [importResult, setImportResult] = useState<ImportResult | null>(null);
  const [stats, setStats] = useState<CollectionStats | null>(null);
  const [tagNames, setTagNames] = useState<string[]>([]);

  useEffect(() => {
    api.listTags().then((ts) => setTagNames(ts.map((t) => t.name))).catch(() => setTagNames([]));
  }, []);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [bulkStatus, setBulkStatus] = useState("");
  const [bulkStorage, setBulkStorage] = useState("");
  const [bulkAddTag, setBulkAddTag] = useState("");
  const [bulkRemoveTag, setBulkRemoveTag] = useState("");
  const [bulkBusy, setBulkBusy] = useState(false);
  const importInput = useRef<HTMLInputElement>(null);

  const toggle = (id: string) =>
    setSelected((s) => {
      const next = new Set(s);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  async function applyBulk() {
    if (selected.size === 0) return;
    setBulkBusy(true);
    setError(null);
    try {
      const set: Record<string, string> = {};
      if (bulkStatus) set.status = bulkStatus;
      if (bulkStorage.trim()) set.storage_location = bulkStorage.trim();
      await api.bulkUpdate({
        ids: [...selected],
        set: Object.keys(set).length ? (set as never) : undefined,
        add_tags: bulkAddTag.trim() ? [bulkAddTag.trim()] : [],
        remove_tags: bulkRemoveTag.trim() ? [bulkRemoveTag.trim()] : [],
      });
      setSelected(new Set());
      setBulkStatus("");
      setBulkStorage("");
      setBulkAddTag("");
      setBulkRemoveTag("");
      set0(); // refetch
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBulkBusy(false);
    }
  }

  const set0 = () => setParams((prev) => new URLSearchParams(prev), { replace: true });

  useEffect(() => {
    api.collectionStats().then(setStats).catch(() => setStats(null));
  }, [page]); // refresh totals when the list data changes

  const sort = params.get("sort") ?? "-created_at";
  const offset = Number(params.get("offset") ?? "0");

  const get = (key: string) => params.get(key) ?? "";
  const set = (key: string, value: string) => {
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (value) next.set(key, value);
        else next.delete(key);
        if (key !== "offset") next.delete("offset"); // filter change resets paging
        return next;
      },
      { replace: true },
    );
  };

  useEffect(() => {
    const query = new URLSearchParams({
      sort,
      limit: String(PAGE_SIZE),
      offset: String(offset),
    });
    for (const key of FILTER_KEYS) {
      const value = params.get(key);
      if (value) query.set(key, value);
    }
    const timer = setTimeout(() => {
      api.listItems(query).then(setPage).catch((e: Error) => setError(e.message));
    }, 250); // debounce text input
    return () => clearTimeout(timer);
  }, [params, sort, offset]);

  async function doImport(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setError(null);
    setImportResult(null);
    try {
      setImportResult(await api.importCsv(file));
      set("offset", ""); // refresh from page one
    } catch (err) {
      setError((err as Error).message);
    } finally {
      e.target.value = "";
    }
  }

  const hasFilters = FILTER_KEYS.some((k) => params.get(k));

  const exportQuery = (() => {
    const p = new URLSearchParams();
    for (const key of FILTER_KEYS) {
      const value = params.get(key);
      if (value) p.set(key, value);
    }
    const s = p.toString();
    return s ? `?${s}` : "";
  })();

  const gain = (value: number) => (
    <b className={value >= 0 ? "gain" : "loss"}>
      {value >= 0 ? "+" : ""}
      {money(value, stats?.currency)}
    </b>
  );

  return (
    <>
      {stats && stats.counts.total > 0 && (
        <div className="stats-strip">
          <span><b>{stats.counts.owned}</b> owned</span>
          {stats.counts.sold > 0 && <span><b>{stats.counts.sold}</b> sold</span>}
          {stats.counts.wishlist > 0 && (
            <span><b>{stats.counts.wishlist}</b> wishlist</span>
          )}
          <span>cost basis <b>{money(stats.cost_basis, stats.currency)}</b></span>
          <span>
            est. value <b>{money(stats.estimated_value, stats.currency)}</b>
            {stats.estimated_items < stats.counts.owned && (
              <span className="muted"> ({stats.estimated_items} of {stats.counts.owned})</span>
            )}
          </span>
          <span>unrealized {gain(stats.unrealized_gain)}</span>
          {stats.counts.sold > 0 && <span>realized {gain(stats.realized_gain)}</span>}
          {stats.excluded_other_currency > 0 && (
            <span className="muted">
              {stats.excluded_other_currency} item(s) in other currencies excluded
            </span>
          )}
        </div>
      )}
      <div className="toolbar">
        <label className="field">
          Type
          <select value={get("type")} onChange={(e) => set("type", e.target.value)}>
            <option value="">All</option>
            <option value="coin">Coins</option>
            <option value="note">Notes</option>
          </select>
        </label>
        <label className="field">
          Status
          <select value={get("status")} onChange={(e) => set("status", e.target.value)}>
            <option value="">All</option>
            <option value="owned">Owned</option>
            <option value="sold">Sold</option>
            <option value="wishlist">Wishlist</option>
          </select>
        </label>
        <label className="field">
          Country
          <input value={get("country")} placeholder="e.g. Canada"
            onChange={(e) => set("country", e.target.value)} />
        </label>
        <label className="field">
          Tag
          <input value={get("tag")} placeholder="e.g. silver" list="tag-options"
            onChange={(e) => set("tag", e.target.value)} />
          <datalist id="tag-options">
            {tagNames.map((t) => (
              <option key={t} value={t} />
            ))}
          </datalist>
        </label>
        {get("set_id") && (
          <button title="Clear the set filter" style={{ alignSelf: "end" }}
            onClick={() => set("set_id", "")}>
            set filter ✕
          </button>
        )}
        <label className="field">
          Search
          <input value={get("q")} placeholder="notes, series, cert, ref…"
            onChange={(e) => set("q", e.target.value)} />
        </label>
        <label className="field">
          Sort
          <select value={sort} onChange={(e) => set("sort", e.target.value)}>
            {SORTS.map((s) => (
              <option key={s.value} value={s.value}>{s.label}</option>
            ))}
          </select>
        </label>
        <button onClick={() => setShowAdvanced(!showAdvanced)}>
          {showAdvanced ? "Less" : "More…"}
        </button>
        <div className="spacer" />
        <button onClick={() => importInput.current?.click()}>Import CSV</button>
        <input ref={importInput} type="file" accept=".csv,text/csv" hidden onChange={doImport} />
        <a className="button" href={`/api/items/export.csv${exportQuery}`}
          title={exportQuery ? "Exports the current filters" : "Exports everything"}>
          CSV
        </a>
        <a className="button" href={`/api/items/export.xlsx${exportQuery}`}
          title={exportQuery ? "Exports the current filters" : "Exports everything"}>
          Excel
        </a>
        <Link className="button primary" to="/items/new">Add item</Link>
      </div>

      {showAdvanced && (
        <div className="toolbar advanced">
          <label className="field">
            Year from
            <input type="number" value={get("year_min")}
              onChange={(e) => set("year_min", e.target.value)} />
          </label>
          <label className="field">
            Year to
            <input type="number" value={get("year_max")}
              onChange={(e) => set("year_max", e.target.value)} />
          </label>
          <label className="field">
            Grade ≥ (rank)
            <input type="number" min={1} max={70} value={get("grade_min")}
              onChange={(e) => set("grade_min", e.target.value)} />
          </label>
          <label className="field">
            Grade ≤ (rank)
            <input type="number" min={1} max={70} value={get("grade_max")}
              onChange={(e) => set("grade_max", e.target.value)} />
          </label>
          <label className="field">
            Value ≥
            <input type="number" min={0} value={get("value_min")}
              onChange={(e) => set("value_min", e.target.value)} />
          </label>
          <label className="field">
            Value ≤
            <input type="number" min={0} value={get("value_max")}
              onChange={(e) => set("value_max", e.target.value)} />
          </label>
        </div>
      )}

      {error && <p className="error">{error}</p>}
      {importResult && (
        <p className={importResult.errors.length ? "error" : "muted"}>
          Imported {importResult.created} item{importResult.created === 1 ? "" : "s"}.
          {importResult.skipped > 0 && ` ${importResult.skipped} already existed (skipped).`}
          {importResult.errors.length > 0 && (
            <>
              {" "}{importResult.errors.length} row(s) failed:{" "}
              {importResult.errors.map((e) => `row ${e.row}: ${e.error}`).join("; ")}
            </>
          )}
        </p>
      )}

      {page && page.items.length === 0 && (
        <div className="empty">
          {page.total === 0 && !hasFilters
            ? "No items yet — add the first piece of your collection."
            : "Nothing matches these filters."}
        </div>
      )}

      {selected.size > 0 && (
        <div className="toolbar advanced">
          <span style={{ alignSelf: "center" }}><b>{selected.size}</b> selected</span>
          <label className="field">
            Set status
            <select value={bulkStatus} onChange={(e) => setBulkStatus(e.target.value)}>
              <option value="">unchanged</option>
              <option value="owned">Owned</option>
              <option value="sold">Sold</option>
              <option value="wishlist">Wishlist</option>
            </select>
          </label>
          <label className="field">
            Set storage
            <input value={bulkStorage} placeholder="unchanged"
              onChange={(e) => setBulkStorage(e.target.value)} />
          </label>
          <label className="field">
            Add tag
            <input value={bulkAddTag} list="tag-options"
              onChange={(e) => setBulkAddTag(e.target.value)} />
          </label>
          <label className="field">
            Remove tag
            <input value={bulkRemoveTag} list="tag-options"
              onChange={(e) => setBulkRemoveTag(e.target.value)} />
          </label>
          <button className="primary" style={{ alignSelf: "end" }} disabled={bulkBusy}
            onClick={applyBulk}>
            {bulkBusy ? "Applying…" : "Apply"}
          </button>
          <button style={{ alignSelf: "end" }} onClick={() => setSelected(new Set())}>
            Clear
          </button>
        </div>
      )}

      {page && page.items.length > 0 && (
        <table className="items">
          <thead>
            <tr>
              <th style={{ width: "28px" }}>
                <input
                  type="checkbox"
                  checked={page.items.every((i) => selected.has(i.id))}
                  onChange={(e) =>
                    setSelected(
                      e.target.checked
                        ? new Set([...selected, ...page.items.map((i) => i.id)])
                        : new Set(
                            [...selected].filter((id) => !page.items.some((i) => i.id === id)),
                          ),
                    )
                  }
                />
              </th>
              <th></th>
              <th>Type</th>
              <th>Country</th>
              <th>Denomination</th>
              <th>Year</th>
              <th>Grade</th>
              <th className="hide-sm">Series</th>
              <th className="num hide-sm">Qty</th>
              <th className="num hide-sm">Paid</th>
              <th className="num">Value</th>
            </tr>
          </thead>
          <tbody>
            {page.items.map((item) => (
              <tr key={item.id} onClick={() => navigate(`/items/${item.id}`)}>
                <td onClick={(e) => e.stopPropagation()}>
                  <input type="checkbox" checked={selected.has(item.id)}
                    onChange={() => toggle(item.id)} />
                </td>
                <td style={{ width: "52px" }}>
                  {item.primary_thumb_key ? (
                    <img className="thumb" src={photoUrl(item.primary_thumb_key)} alt="" />
                  ) : (
                    <div className="thumb placeholder">{item.type === "coin" ? "◎" : "▭"}</div>
                  )}
                </td>
                <td>
                  <span className={`badge ${item.type}`}>{item.type}</span>
                  {item.status !== "owned" && (
                    <span className={`badge status-${item.status}`}>{item.status}</span>
                  )}
                </td>
                <td>{item.country}</td>
                <td>
                  {item.denomination}
                  {item.mint_mark && <span className="muted"> · {item.mint_mark}</span>}
                </td>
                <td>{item.year}</td>
                <td>{item.grade ? item.grade.code : <span className="muted">—</span>}</td>
                <td className="muted hide-sm">{item.series ?? ""}</td>
                <td className="num hide-sm">{item.quantity}</td>
                <td className="num hide-sm">{money(item.acquisition_price, item.currency)}</td>
                <td className="num">{money(item.latest_value, item.latest_value_currency)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {page && page.total > PAGE_SIZE && (
        <div className="pagination">
          <button
            disabled={offset === 0}
            onClick={() => set("offset", String(Math.max(0, offset - PAGE_SIZE)))}
          >
            ← Prev
          </button>
          <span className="muted">
            {offset + 1}–{Math.min(offset + PAGE_SIZE, page.total)} of {page.total}
          </span>
          <button
            disabled={offset + PAGE_SIZE >= page.total}
            onClick={() => set("offset", String(offset + PAGE_SIZE))}
          >
            Next →
          </button>
        </div>
      )}
    </>
  );
}
