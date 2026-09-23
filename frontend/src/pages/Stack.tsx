import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api, METAL_LABELS, money, StackReport, TagInfo } from "../api";
import { delta } from "../dashboard/widgets/value";
import { timeSince } from "../components/provenance";

const oz = (v: number) =>
  v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 3 });

const pct = (v: number) => `${v > 0 ? "+" : ""}${v.toFixed(1)}%`;

export default function Stack() {
  const [tag, setTag] = useState("");
  const [tags, setTags] = useState<TagInfo[]>([]);
  const [data, setData] = useState<StackReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [backfilling, setBackfilling] = useState(false);
  const [backfillNote, setBackfillNote] = useState<string | null>(null);

  useEffect(() => {
    api.listTags().then(setTags).catch(() => setTags([]));
  }, []);

  function load() {
    api
      .getStack({ tag: tag || undefined })
      .then((r) => {
        setData(r);
        setError(null);
      })
      .catch((e: Error) => setError(e.message));
  }

  useEffect(load, [tag]);

  async function backfill() {
    setBackfilling(true);
    setBackfillNote(null);
    try {
      const r = await api.backfillStack();
      setBackfillNote(
        `Filled ${r.filled}${r.failed ? `, ${r.failed} failed` : ""}${
          r.remaining ? `, ${r.remaining} remaining` : ""
        }.`,
      );
      load();
    } catch (e) {
      setBackfillNote((e as Error).message);
    } finally {
      setBackfilling(false);
    }
  }

  if (error) return <p className="error">{error}</p>;
  if (!data) return <p className="muted">Loading…</p>;

  const empty = data.metals.length === 0;

  return (
    <>
      <div className="detail-header">
        <h1>Stack</h1>
        <div className="spacer" />
        <select aria-label="Scope" value={tag} onChange={(e) => setTag(e.target.value)}>
          <option value="">All</option>
          {tags.map((t) => (
            <option key={t.name} value={t.name}>
              {t.name}
            </option>
          ))}
        </select>
        {data.missing_spot > 0 && (
          <button disabled={backfilling} onClick={backfill}>
            {backfilling ? "Fetching…" : `Fetch purchase-day spot (${data.missing_spot})`}
          </button>
        )}
      </div>
      {backfillNote && <p className="muted">{backfillNote}</p>}

      {empty ? (
        <div className="empty">
          No precious-metal pieces with a weight and fineness yet. Name a precious metal and give a
          weight and fineness to include a coin or note, or{" "}
          <Link to="/items/new?type=bullion">Add a bar or round</Link>.
        </div>
      ) : (
        <>
          {data.metals.map((m) => (
            <div className="card" key={m.metal}>
              <h2>{METAL_LABELS[m.metal]}</h2>
              <div className="tiles">
                <div className="tile">
                  <span className="tile-label">Fine ounces</span>
                  <span className="tile-value">{oz(m.fine_oz)}</span>
                  <span className="muted">
                    {m.fine_g.toLocaleString(undefined, { maximumFractionDigits: 1 })} g
                  </span>
                </div>
                <div className="tile">
                  <span className="tile-label">Melt value at spot</span>
                  <span className="tile-value">
                    {m.melt_value != null ? money(m.melt_value, data.currency) : "–"}
                  </span>
                  <span className="muted">
                    {m.spot_per_oz != null
                      ? `${money(m.spot_per_oz, data.currency)}/oz (${
                          m.spot_fetched_at ? timeSince(m.spot_fetched_at) : "–"
                        }${m.spot_stale ? ", stale" : ""})`
                      : "spot unavailable"}
                  </span>
                </div>
                <div className="tile">
                  <span className="tile-label">Cost basis</span>
                  <span className="tile-value">
                    {m.cost_basis != null ? money(m.cost_basis, data.currency) : "–"}
                  </span>
                </div>
                <div className="tile">
                  <span className="tile-label">Cost per ounce (break-even spot)</span>
                  <span className="tile-value">
                    {m.cost_per_oz != null ? money(m.cost_per_oz, data.currency) : "–"}
                  </span>
                </div>
                <div className="tile">
                  <span className="tile-label">Gain or loss at melt</span>
                  <span className="tile-value">
                    {m.gain != null ? delta(m.gain, data.currency) : "–"}
                  </span>
                  <span className="muted">{m.gain_pct != null ? pct(m.gain_pct) : "–"}</span>
                </div>
                <div className="tile">
                  <span className="tile-label">Premium paid over spot</span>
                  <span className="tile-value">
                    {m.premium_paid_pct != null ? pct(m.premium_paid_pct) : "–"}
                  </span>
                  <span className="muted">
                    {m.premium_paid_pct != null
                      ? `known for ${oz(m.premium_known_oz)} of ${oz(m.fine_oz)} oz`
                      : "no purchase-day spot yet"}
                  </span>
                </div>
              </div>
            </div>
          ))}

          <div className="card">
            <h2>Items in the stack</h2>
            <div className="table-scroll">
              <table className="estimates">
                <thead>
                  <tr>
                    <th>Item</th>
                    <th>Metal</th>
                    <th className="num">Qty</th>
                    <th className="num">Fine oz</th>
                    <th className="num">Cost</th>
                    <th className="num">Cost/oz</th>
                    <th className="num">Spot at purchase</th>
                    <th className="num">Premium paid</th>
                    <th className="num">Melt</th>
                    <th className="num">Gain</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((it) => (
                    <tr key={it.item_id}>
                      <td>
                        <Link to={`/items/${it.item_id}`}>{it.label}</Link>
                      </td>
                      <td>{METAL_LABELS[it.metal]}</td>
                      <td className="num">{it.quantity}</td>
                      <td className="num">{oz(it.fine_oz)}</td>
                      <td className="num">
                        {it.cost_basis != null ? money(it.cost_basis, data.currency) : "–"}
                      </td>
                      <td className="num">
                        {it.cost_per_oz != null ? money(it.cost_per_oz, data.currency) : "–"}
                      </td>
                      <td className="num">
                        {it.spot_at_purchase != null ? (
                          <>
                            {money(it.spot_at_purchase, it.currency)}{" "}
                            <span className="muted">
                              ({it.spot_at_purchase_source === "manual" ? "typed" : "auto"})
                            </span>
                          </>
                        ) : (
                          "–"
                        )}
                      </td>
                      <td className="num">
                        {it.premium_paid_pct != null ? pct(it.premium_paid_pct) : "–"}
                      </td>
                      <td className="num">
                        {it.melt_value != null ? money(it.melt_value, data.currency) : "–"}
                      </td>
                      <td className="num">{it.gain != null ? delta(it.gain, data.currency) : "–"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <p className="muted">
            The stack is owned, untrashed items with a detected precious metal (gold, silver,
            platinum, palladium), a weight, and a fineness. Melt value is the metal content at
            spot; it ignores any numismatic premium the piece may carry beyond its metal.
            {data.skipped > 0 &&
              ` ${data.skipped} item(s) have a precious metal but no weight or fineness, so they're left out.`}
            {data.excluded_other_currency > 0 &&
              ` ${data.excluded_other_currency} amount(s) left out of the money figures (no exchange rate); their ounces still count.`}{" "}
            Purchase-day spot is filled in automatically for purchases from {data.history_start};
            earlier purchases need a hand-typed figure on the item.
          </p>
        </>
      )}
    </>
  );
}
