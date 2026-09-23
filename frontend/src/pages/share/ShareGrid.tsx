import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api, ItemType, money, ShareItem, ShareManifest, sharePhotoUrl } from "../../api";
import { BullionIcon, CoinIcon, NoteIcon } from "../../components/icons";

const PAGE_SIZE = 100;

/** The same convention item-hero.tsx uses for an item's title: bullion
 * leads with its issuer or country, everything else with country,
 * denomination, year, and the mint mark. */
export function shareItemLabel(item: ShareItem): string {
  if (item.type === "bullion") {
    return [item.issuer || item.country, item.denomination, item.year_label]
      .filter(Boolean)
      .join(" ");
  }
  const mint = item.mint_mark ? ` "${item.mint_mark}"` : "";
  return `${item.country} ${item.denomination}, ${item.year_label}${mint}`;
}

function typeIcon(type: ItemType) {
  return type === "coin" ? <CoinIcon /> : type === "bullion" ? <BullionIcon /> : <NoteIcon />;
}

function matches(item: ShareItem, q: string): boolean {
  const haystack = [shareItemLabel(item), item.country, item.denomination, item.series, ...(item.tags ?? [])]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
  return haystack.includes(q);
}

/** The pieces a link covers, as a grid of cards; a search box filters what
 * has already loaded, and "Load more" fetches the next page of 100. */
export default function ShareGrid({ token, manifest }: { token: string; manifest: ShareManifest }) {
  const [items, setItems] = useState<ShareItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");

  async function loadPage(offset: number) {
    setLoading(true);
    setError(null);
    try {
      const page = await api.shareItems(token, offset, PAGE_SIZE);
      setItems((prev) => (offset === 0 ? page.items : [...prev, ...page.items]));
      setTotal(page.total);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    setItems([]);
    setTotal(0);
    loadPage(0);
    // Re-runs only when the token changes; loadPage reads the latest state
    // itself through the updater form of setItems.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  const q = query.trim().toLowerCase();
  const filtered = q ? items.filter((item) => matches(item, q)) : items;

  return (
    <div className="share-list">
      <input
        className="share-search"
        type="search"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Search this share…"
        aria-label="Search"
      />
      {error && <p className="error">{error}</p>}
      {!loading && items.length === 0 && !error && <p className="empty">Nothing to show here yet.</p>}
      {q && filtered.length === 0 && items.length > 0 && (
        <p className="empty">No pieces match &quot;{query}&quot;.</p>
      )}
      <div className="share-grid">
        {filtered.map((item) => {
          const photo = manifest.show_photos ? item.photos?.[0] : undefined;
          return (
            <Link key={item.id} className="card share-card" to={`/s/${token}/items/${item.id}`}>
              <div className="share-thumb">
                {photo ? (
                  <img src={sharePhotoUrl(token, photo.id, "thumb")} alt={photo.angle ?? "photo"} />
                ) : (
                  <div className="share-thumb-empty">{typeIcon(item.type)}</div>
                )}
              </div>
              <div className="share-card-body">
                <div className="share-card-label">{shareItemLabel(item)}</div>
                {manifest.show_grades && item.grade_label && <div className="muted">{item.grade_label}</div>}
                {manifest.show_values && item.value && (
                  <div className="share-card-value">{money(item.value.amount, item.value.currency)}</div>
                )}
              </div>
            </Link>
          );
        })}
      </div>
      {loading && <p className="muted">Loading…</p>}
      {!loading && items.length < total && (
        <button type="button" onClick={() => loadPage(items.length)}>
          Load more
        </button>
      )}
    </div>
  );
}
