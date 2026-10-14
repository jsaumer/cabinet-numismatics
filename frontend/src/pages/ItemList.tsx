import { useEffect, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";

import {
  api,
  CollectionStats,
  ItemPage,
  METAL_LABELS,
  money,
  photoUrl,
  PRIORITY_LABELS,
} from "../api";
import { FreshLink } from "../auth/FreshLink";
import { Menu } from "../components/controls";
import { TraitBadges, useSerialTraits } from "../components/serial-traits";
import ItemDetail from "./ItemDetail";
import { detectMetal } from "./item-form/model";

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

// Offered when the list shows the wishlist.
const WISHLIST_SORTS = [
  { value: "priority", label: "Priority" },
  { value: "target_price", label: "Target price ↑" },
  { value: "-target_price", label: "Target price ↓" },
];

// Filters behind "More…"; any of them in the URL opens it.
const ADVANCED_KEYS = [
  "year_min", "year_max", "nd", "grade_min", "grade_max", "value_min", "value_max",
  "fancy", "serial_trait", "target_reached",
];

const FILTER_KEYS = [
  "type", "status", "strike", "country", "metal", "year", "q", "tag", "set_id",
  "year_min", "year_max", "nd", "grade_min", "grade_max", "value_min", "value_max",
  "fancy", "serial_trait", "target_reached",
] as const;

const WIDE = "(min-width: 1100px)";

/** Whether the list and the inspector fit side by side. */
function useWide() {
  const [wide, setWide] = useState(() => window.matchMedia(WIDE).matches);
  useEffect(() => {
    const query = window.matchMedia(WIDE);
    const onChange = () => setWide(query.matches);
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, []);
  return wide;
}

export default function ItemList() {
  const navigate = useNavigate();
  const { id: selectedId } = useParams();
  const wide = useWide();
  const [params, setParams] = useSearchParams();
  const [page, setPage] = useState<ItemPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showAdvanced, setShowAdvanced] = useState(ADVANCED_KEYS.some((k) => params.has(k)));
  const traitReference = useSerialTraits();
  const [stats, setStats] = useState<CollectionStats | null>(null);
  const [tagNames, setTagNames] = useState<string[]>([]);

  useEffect(() => {
    api.listTags().then((ts) => setTagNames(ts.map((t) => t.name))).catch(() => setTagNames([]));
  }, []);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [, setTrashCount] = useState(0);
  useEffect(() => {
    api.listTrash().then((t) => setTrashCount(t.items.length)).catch(() => setTrashCount(0));
  }, []);
  const [bulkType, setBulkType] = useState("");
  const [bulkStatus, setBulkStatus] = useState("");
  const [bulkStorage, setBulkStorage] = useState("");
  const [bulkPriority, setBulkPriority] = useState("");
  const [bulkAddTag, setBulkAddTag] = useState("");
  const [bulkRemoveTag, setBulkRemoveTag] = useState("");
  const [bulkBusy, setBulkBusy] = useState(false);

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
      const set: Record<string, string | number> = {};
      if (bulkType) set.type = bulkType;
      if (bulkStatus) set.status = bulkStatus;
      if (bulkPriority) set.priority = Number(bulkPriority);
      if (bulkStorage.trim()) set.storage_location = bulkStorage.trim();
      await api.bulkUpdate({
        ids: [...selected],
        set: Object.keys(set).length ? (set as never) : undefined,
        add_tags: bulkAddTag.trim() ? [bulkAddTag.trim()] : [],
        remove_tags: bulkRemoveTag.trim() ? [bulkRemoveTag.trim()] : [],
      });
      setSelected(new Set());
      setBulkType("");
      setBulkStatus("");
      setBulkStorage("");
      setBulkPriority("");
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

  async function trashSelected() {
    const count = selected.size;
    if (!count || !window.confirm(`Move ${count} item${count === 1 ? "" : "s"} to the trash?`)) return;
    setBulkBusy(true);
    setError(null);
    try {
      await api.trashItems([...selected]);
      setSelected(new Set());
      setTrashCount((n) => n + count);
      set0(); // refetch
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBulkBusy(false);
    }
  }

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


  const hasFilters = FILTER_KEYS.some((k) => params.get(k));
  const wishlistView = get("status") === "wishlist";
  const sorts =
    wishlistView || WISHLIST_SORTS.some((s) => s.value === sort)
      ? [...SORTS, ...WISHLIST_SORTS]
      : SORTS;
  // One select, two parameters: "any" is fancy=true, a trait is serial_trait=<key>.
  const fancyChoice = get("serial_trait") || (get("fancy") === "true" ? "any" : "");
  const setFancy = (choice: string) =>
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.delete("fancy");
        next.delete("serial_trait");
        next.delete("offset");
        if (choice === "any") next.set("fancy", "true");
        else if (choice) next.set("serial_trait", choice);
        return next;
      },
      { replace: true },
    );

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

  const exportTitle = exportQuery ? "Exports the current filters" : "Exports everything";

  const viewTitle = get("q")
    ? `Search: ${get("q")}`
    : { owned: "Owned", wishlist: "Wish list", sold: "Sold" }[get("status")] ?? "Everything";
  const items = page?.items ?? [];
  const selectedIndex = items.findIndex((i) => i.id === selectedId);
  const search = params.toString() ? `?${params.toString()}` : "";
  const rowLink = (itemId: string) => (wide ? `/collection/${itemId}${search}` : `/items/${itemId}`);

  // Keyboard moves through the list while nothing is being typed into.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      const t = e.target as HTMLElement | null;
      if (t && (t.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName))) return;
      if (document.querySelector("dialog[open], .modal-backdrop")) return;
      const move = (to: number) => {
        const next = items[Math.max(0, Math.min(items.length - 1, to))];
        if (next) {
          e.preventDefault();
          navigate(rowLink(next.id), { replace: true });
          document.getElementById(`row-${next.id}`)?.scrollIntoView({ block: "nearest" });
        }
      };
      if (e.key === "j" || e.key === "ArrowDown") move(selectedIndex + 1);
      else if (e.key === "k" || e.key === "ArrowUp") move(selectedIndex < 0 ? 0 : selectedIndex - 1);
      else if (e.key === "Enter" && selectedId) navigate(`/items/${selectedId}`);
      else if (e.key === "e" && selectedId) navigate(`/items/${selectedId}/edit`);
      else if (e.key === "n") navigate("/items/new");
      else if (e.key === "Escape" && selectedId) navigate(`/collection${search}`, { replace: true });
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const listHeader = (
    <div className="wb-head">
      <h1>{viewTitle}</h1>
      {page && <span className="muted">{page.total} {page.total === 1 ? "piece" : "pieces"}</span>}
      <div className="spacer" />
      <Menu label="Export / import">
        <FreshLink role="menuitem" href={`/api/items/export.csv${exportQuery}`} title={exportTitle}>
          Export as CSV
        </FreshLink>
        <FreshLink role="menuitem" href={`/api/items/export.xlsx${exportQuery}`} title={exportTitle}>
          Export as Excel
        </FreshLink>
        <Link role="menuitem" to="/import"
          title="From Numista, OpenNumismat, a spreadsheet, or a Cabinet export">
          Import…
        </Link>
      </Menu>
      <Link className="button" to="/items/run" title="One item per date and mint of a type">
        Add a run
      </Link>
    </div>
  );

  const filters = (
    <>
      <div className="wb-filters">
        <select aria-label="Type" value={get("type")} onChange={(e) => set("type", e.target.value)}>
          <option value="">All types</option>
          <option value="coin">Coins</option>
          <option value="note">Notes</option>
          <option value="bullion">Bars and rounds</option>
        </select>
        <select aria-label="Metal" value={get("metal")} onChange={(e) => set("metal", e.target.value)}>
          <option value="">Any metal</option>
          {Object.entries(METAL_LABELS).map(([key, label]) => (
            <option key={key} value={key}>{label}</option>
          ))}
          <option value="none">No precious metal</option>
        </select>
        <select aria-label="Sort" value={sort} onChange={(e) => set("sort", e.target.value)}>
          {sorts.map((s) => (
            <option key={s.value} value={s.value}>{s.label}</option>
          ))}
        </select>
        <button type="button" onClick={() => setShowAdvanced(!showAdvanced)}
          aria-expanded={showAdvanced}>
          {showAdvanced ? "Fewer filters" : "More filters"}
        </button>
        {get("set_id") && (
          <button type="button" title="Clear the set filter" onClick={() => set("set_id", "")}>
            set filter ✕
          </button>
        )}
      </div>
      {showAdvanced && (
        <div className="wb-advanced">
          <label className="field">
            Status
            <select value={get("status")} onChange={(e) => set("status", e.target.value)}>
              <option value="">All</option>
              <option value="owned">Owned</option>
              <option value="sold">Sold</option>
              <option value="wishlist">Wish list</option>
            </select>
          </label>
          <label className="field">
            Country
            <input value={get("country")} placeholder="Canada"
              onChange={(e) => set("country", e.target.value)} />
          </label>
          <label className="field">
            Tag
            <input value={get("tag")} placeholder="silver" list="tag-options"
              onChange={(e) => set("tag", e.target.value)} />
          </label>
          <label className="field">
            Strike
            <select value={get("strike")} onChange={(e) => set("strike", e.target.value)}>
              <option value="">All</option>
              <option value="business">Business / regular</option>
              <option value="proof">Proof</option>
              <option value="specimen">Specimen</option>
            </select>
          </label>
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
            Dating
            <select value={get("nd")} onChange={(e) => set("nd", e.target.value)}>
              <option value="">All</option>
              <option value="true">Undated (ND)</option>
              <option value="false">Dated</option>
            </select>
          </label>
          <label className="field">
            Grade from (rank)
            <input type="number" min={1} max={70} value={get("grade_min")}
              onChange={(e) => set("grade_min", e.target.value)} />
          </label>
          <label className="field">
            Grade to (rank)
            <input type="number" min={1} max={70} value={get("grade_max")}
              onChange={(e) => set("grade_max", e.target.value)} />
          </label>
          <label className="field">
            Value from
            <input type="number" min={0} value={get("value_min")}
              onChange={(e) => set("value_min", e.target.value)} />
          </label>
          <label className="field">
            Value to
            <input type="number" min={0} value={get("value_max")}
              onChange={(e) => set("value_max", e.target.value)} />
          </label>
          <label className="field">
            Fancy serial
            <select value={fancyChoice} onChange={(e) => setFancy(e.target.value)}>
              <option value="">All</option>
              <option value="any">Any fancy serial</option>
              {traitReference.map((t) => (
                <option key={t.key} value={t.key} title={t.description}>{t.label}</option>
              ))}
              {get("serial_trait") && !traitReference.some((t) => t.key === get("serial_trait")) && (
                <option value={get("serial_trait")}>{get("serial_trait")}</option>
              )}
            </select>
          </label>
          <label className="field">
            Wish-list target
            <select value={get("target_reached")}
              onChange={(e) => set("target_reached", e.target.value)}>
              <option value="">All</option>
              <option value="true">Target reached</option>
            </select>
          </label>
        </div>
      )}
      <datalist id="tag-options">
        {tagNames.map((t) => (
          <option key={t} value={t} />
        ))}
      </datalist>
    </>
  );

  const bulk = selected.size > 0 && (
    <div className="wb-bulk">
      <span><b>{selected.size}</b> selected</span>
      <select aria-label="Set type" value={bulkType} onChange={(e) => setBulkType(e.target.value)}>
        <option value="">Type unchanged</option>
        <option value="coin">Coin</option>
        <option value="note">Note</option>
        <option value="bullion">Bar or round</option>
      </select>
      <select aria-label="Set status" value={bulkStatus} onChange={(e) => setBulkStatus(e.target.value)}>
        <option value="">Status unchanged</option>
        <option value="owned">Owned</option>
        <option value="sold">Sold</option>
        <option value="wishlist">Wish list</option>
      </select>
      <input aria-label="Set storage" value={bulkStorage} placeholder="Storage unchanged"
        onChange={(e) => setBulkStorage(e.target.value)} />
      <select aria-label="Set priority" value={bulkPriority} onChange={(e) => setBulkPriority(e.target.value)}>
        <option value="">Priority unchanged</option>
        <option value="1">High</option>
        <option value="2">Medium</option>
        <option value="3">Low</option>
      </select>
      <input aria-label="Add tag" value={bulkAddTag} placeholder="Add tag" list="tag-options"
        onChange={(e) => setBulkAddTag(e.target.value)} />
      <input aria-label="Remove tag" value={bulkRemoveTag} placeholder="Remove tag" list="tag-options"
        onChange={(e) => setBulkRemoveTag(e.target.value)} />
      <button className="primary" disabled={bulkBusy} onClick={applyBulk}>
        {bulkBusy ? "Applying…" : "Apply"}
      </button>
      <button className="danger" disabled={bulkBusy} onClick={trashSelected}>Move to trash</button>
      <button onClick={() => setSelected(new Set())}>Clear</button>
    </div>
  );

  const allChecked = items.length > 0 && items.every((i) => selected.has(i.id));

  return (
    <div className={`workbench${selectedId && wide ? " has-selection" : ""}`}>
      <section className="wb-list" aria-label="Pieces">
        {listHeader}
        {stats && stats.counts.total > 0 && (
          <p className="wb-summary">
            <span>est. <b>{money(stats.estimated_value, stats.currency)}</b></span>
            <span>cost <b>{money(stats.cost_basis, stats.currency)}</b></span>
            <span>unrealized {gain(stats.unrealized_gain)}</span>
            {stats.counts.sold > 0 && <span>realized {gain(stats.realized_gain)}</span>}
            {stats.estimated_items < stats.counts.owned && (
              <span className="muted">{stats.estimated_items} of {stats.counts.owned} priced</span>
            )}
          </p>
        )}
        {filters}
        {bulk}
        {error && <p className="error">{error}</p>}
        {page && items.length === 0 && (
          <div className="empty">
            {page.total === 0 && !hasFilters
              ? "No items yet. Add the first piece of your collection, or import one."
              : "Nothing matches these filters."}
          </div>
        )}
        {items.length > 0 && (
          <>
            <div className="wb-colhead">
              <input
                type="checkbox"
                aria-label="Select every piece on this page"
                checked={allChecked}
                onChange={(e) =>
                  setSelected(
                    e.target.checked
                      ? new Set([...selected, ...items.map((i) => i.id)])
                      : new Set([...selected].filter((id) => !items.some((i) => i.id === id))),
                  )
                }
              />
              <span>Piece</span>
              <span>Grade</span>
              <span className="num">{wishlistView ? "Target" : "Value"}</span>
            </div>
            <ul className="wb-rows">
              {items.map((item) => {
                const metal = item.composition ? detectMetal(item.composition) : null;
                const title =
                  item.type === "bullion"
                    ? [item.issuer || item.country, item.denomination].filter(Boolean).join(" ")
                    : `${item.year_label}${item.mint_mark ? `-${item.mint_mark}` : ""} ${item.denomination}`;
                const sub = [
                  item.type === "bullion" ? null : item.series,
                  item.country,
                  item.status === "sold" ? "sold" : null,
                  item.status === "wishlist" ? "wish list" : null,
                  item.quantity > 1 ? `×${item.quantity}` : null,
                ].filter(Boolean).join(" · ");
                return (
                  <li
                    key={item.id}
                    id={`row-${item.id}`}
                    className={[
                      "wb-row",
                      item.id === selectedId ? "selected" : "",
                      item.status === "sold" ? "sold" : "",
                    ].join(" ")}
                  >
                    <input
                      type="checkbox"
                      aria-label={`Select ${title}`}
                      checked={selected.has(item.id)}
                      onChange={() => toggle(item.id)}
                    />
                    <Link
                      to={rowLink(item.id)}
                      replace={wide && Boolean(selectedId)}
                      aria-current={item.id === selectedId ? "true" : undefined}
                    >
                      {item.primary_thumb_key ? (
                        <img className="wb-thumb" src={photoUrl(item.primary_thumb_key)} alt="" />
                      ) : (
                        <span
                          className={`wb-glyph ${item.type} ${metal ?? "base"}${item.status === "wishlist" ? " hollow" : ""}`}
                          aria-hidden="true"
                        />
                      )}
                      <span className="wb-title">
                        <span className="t">
                          {title}{" "}
                          <TraitBadges traits={item.serial_traits} reference={traitReference} max={1} />
                        </span>
                        {sub && <span className="s">{sub}</span>}
                      </span>
                      <span className="wb-grade">{item.grade_label ?? ""}</span>
                      <span className="wb-value num">
                        {wishlistView ? (
                          <>
                            {item.target_reached && <span className="badge reached">reached</span>}{" "}
                            {money(item.target_price, item.currency)}
                            {item.priority != null && (
                              <span className="muted"> · {PRIORITY_LABELS[item.priority]}</span>
                            )}
                          </>
                        ) : item.latest_value != null ? (
                          money(item.latest_value, item.latest_value_currency)
                        ) : (
                          <span className="muted">unpriced</span>
                        )}
                      </span>
                    </Link>
                  </li>
                );
              })}
            </ul>
          </>
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
        <p className="wb-keys muted" aria-hidden="true">
          <kbd>J</kbd> <kbd>K</kbd> move · <kbd>Enter</kbd> open · <kbd>E</kbd> edit ·{" "}
          <kbd>N</kbd> new · <kbd>/</kbd> search · <kbd>Esc</kbd> close
        </p>
      </section>
      {wide && (
        <section className="wb-inspector" aria-label="Selected piece">
          {selectedId ? (
            <ItemDetail key={selectedId} itemId={selectedId} embedded onChanged={set0} />
          ) : (
            <div className="wb-pick">
              <p>Pick a piece to see it here.</p>
              <p className="muted">
                <kbd>J</kbd> and <kbd>K</kbd> move through the list; everything about a piece opens
                beside it, and <kbd>Enter</kbd> opens its full page.
              </p>
            </div>
          )}
        </section>
      )}
    </div>
  );
}
