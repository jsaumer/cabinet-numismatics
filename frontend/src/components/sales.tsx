import { FormEvent, useState } from "react";

import { api, Comparable, ComparableInput, ItemDetail, money } from "../api";

// Numista's grade buckets, and the Sheldon/PMG rank cutoffs the backend uses
// (services/numista.py): a sale with a known bucket counts only when it matches.
const RANK_CUTOFFS: [number, string][] = [
  [8, "g"], [12, "vg"], [20, "f"], [40, "vf"], [50, "xf"], [60, "au"],
];
const bucketForRank = (rank: number) => RANK_CUTOFFS.find(([cutoff]) => rank < cutoff)?.[1] ?? "unc";

const VENUES = [
  "eBay",
  "Heritage Auctions",
  "GreatCollections",
  "Stack's Bowers",
  "David Lawrence (DLRC)",
  "Spink",
  "Lyn Knight",
  "Dealer",
  "Coin show",
];

const today = () => new Date().toISOString().slice(0, 10);
const externalUrl = (url: string) => (/^https?:\/\//i.test(url) ? url : `https://${url}`);

interface Draft {
  sold_on: string;
  venue: string;
  grade: string;
  price: string;
  currency: string;
  premium: "" | "yes" | "no";
  fees: string;
  url: string;
  lot: string;
  note: string;
}

const emptyDraft = (currency: string): Draft => ({
  sold_on: today(),
  venue: "",
  grade: "",
  price: "",
  currency,
  premium: "",
  fees: "",
  url: "",
  lot: "",
  note: "",
});

const draftOf = (sale: Comparable): Draft => ({
  sold_on: sale.sold_on,
  venue: sale.venue,
  grade: sale.grade ?? "",
  price: String(sale.price),
  currency: sale.currency,
  premium: sale.premium_included == null ? "" : sale.premium_included ? "yes" : "no",
  fees: sale.fees == null ? "" : String(sale.fees),
  url: sale.url ?? "",
  lot: sale.lot ?? "",
  note: sale.note ?? "",
});

const inputOf = (d: Draft): ComparableInput => ({
  sold_on: d.sold_on,
  venue: d.venue.trim(),
  grade: d.grade.trim() || null,
  price: Number(d.price),
  currency: d.currency.trim().toUpperCase(),
  premium_included: d.premium === "" ? null : d.premium === "yes",
  fees: d.fees === "" ? null : Number(d.fees),
  url: d.url.trim() || null,
  lot: d.lot.trim() || null,
  note: d.note.trim() || null,
});

function priceNotes(sale: Comparable): string {
  const notes: string[] = [];
  if (sale.fees) notes.push(`${money(sale.price, null)} + ${money(sale.fees, null)} fees`);
  if (sale.premium_included === true) notes.push("premium included");
  if (sale.premium_included === false) notes.push("before buyer's premium");
  return notes.join(" · ");
}

/** The item's sales log: sales of comparable pieces, which the comps
 * estimate takes its median from. */
export function SalesLog({
  item,
  compsEnabled,
  numistaSales,
  onChanged,
}: {
  item: ItemDetail;
  compsEnabled: boolean;
  numistaSales: boolean;
  onChanged: () => void;
}) {
  const [draft, setDraft] = useState<Draft>(() => emptyDraft(item.currency));
  const [editingId, setEditingId] = useState<number | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  const sales = item.comparables;
  const bucket = item.grade ? bucketForRank(item.grade.rank) : null;
  const hasNumistaRef = item.catalog_refs.some((r) => r.catalog.trim().toLowerCase() === "numista");
  const set = (field: keyof Draft) => (value: string) => setDraft((d) => ({ ...d, [field]: value }));

  async function run(label: string, fn: () => Promise<string | void>) {
    setBusy(label);
    setError(null);
    setNote(null);
    try {
      const message = await fn();
      if (message) setNote(message);
      onChanged();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(null);
    }
  }

  function startEdit(sale: Comparable) {
    setEditingId(sale.id);
    setDraft(draftOf(sale));
    setFormOpen(true);
  }

  function closeForm() {
    setEditingId(null);
    setDraft(emptyDraft(item.currency));
    setFormOpen(false);
  }

  function save(e: FormEvent) {
    e.preventDefault();
    const input = inputOf(draft);
    run("save", async () => {
      if (editingId !== null) {
        await api.updateComparable(editingId, input);
        closeForm();
        return "Sale updated.";
      }
      await api.addComparable(item.id, input);
      setDraft(emptyDraft(input.currency)); // keep the form open for the next one
      return "Sale logged.";
    });
  }

  const countsToward = (sale: Comparable) =>
    sale.included && (bucket === null || sale.grade_bucket === null || sale.grade_bucket === bucket);
  const counted = sales.filter(countsToward).length;

  return (
    <div className="card">
      <h2>Sales log</h2>
      <p className="muted" style={{ marginTop: 0 }}>
        Sales of pieces like this one: eBay sold listings, auction results, dealer sales. The{" "}
        <b>comps</b> estimate is the median of recent ones (the last three years, or older when
        fewer than three are that recent), converted to your display currency; confidence grows
        with the number of sales and shrinks when they disagree.
      </p>
      {error && <p className="error">{error}</p>}
      {note && <p className="gain">{note}</p>}

      {sales.length === 0 ? (
        <p className="muted">No sales logged yet.</p>
      ) : (
        <div className="table-scroll">
          <table className="estimates sales-log">
            <thead>
              <tr>
                <th title="Counts toward the comps estimate">Use</th>
                <th>Sold</th>
                <th>Where</th>
                <th>Grade</th>
                <th>Price</th>
                <th>From</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {sales.map((sale) => {
                const otherGrade =
                  bucket !== null && sale.grade_bucket !== null && sale.grade_bucket !== bucket;
                return (
                  <tr key={sale.id} className={countsToward(sale) ? undefined : "left-out"}>
                    <td>
                      <input
                        type="checkbox"
                        checked={sale.included}
                        disabled={busy !== null}
                        title={sale.included ? "Leave this sale out" : "Count this sale"}
                        onChange={(e) =>
                          run("toggle", () =>
                            api.updateComparable(sale.id, { included: e.target.checked }).then(() => undefined),
                          )
                        }
                      />
                    </td>
                    <td>{sale.sold_on}</td>
                    <td>
                      {sale.url ? (
                        <a href={externalUrl(sale.url)} target="_blank" rel="noreferrer">
                          {sale.venue}
                        </a>
                      ) : (
                        sale.venue
                      )}
                      {sale.lot && <span className="muted"> · lot {sale.lot}</span>}
                      {sale.title && <div className="muted sale-title">{sale.title}</div>}
                      {sale.note && <div className="muted sale-title">{sale.note}</div>}
                    </td>
                    <td>
                      {sale.grade ?? "–"}
                      {otherGrade && (
                        <div className="muted sale-title">
                          other grade ({sale.grade_bucket?.toUpperCase()}), not counted
                        </div>
                      )}
                    </td>
                    <td>
                      {money(sale.price + (sale.fees ?? 0), sale.currency)}
                      <div className="muted sale-title">{priceNotes(sale)}</div>
                    </td>
                    <td className="muted">{sale.source === "numista" ? "Numista" : "you"}</td>
                    <td className="provenance-toggle">
                      <button type="button" className="link-button" onClick={() => startEdit(sale)}>
                        edit
                      </button>{" "}
                      <button
                        type="button"
                        className="link-button"
                        disabled={busy !== null}
                        onClick={() => {
                          if (window.confirm("Remove this sale from the log?")) {
                            run("delete", () => api.deleteComparable(sale.id).then(() => "Sale removed."));
                          }
                        }}
                      >
                        remove
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <div className="estimate-form">
        <button
          disabled={busy !== null || !compsEnabled || counted === 0}
          title={
            !compsEnabled
              ? "Comps estimates are switched off in Settings"
              : counted === 0
                ? "Log at least one sale that counts first"
                : "Record a comps estimate from these sales"
          }
          onClick={() =>
            run("estimate", async () => {
              const est = await api.autoEstimate(item.id, "comps");
              return `Comps estimate recorded: ${money(est.estimated_value, est.currency)} from ${
                est.sample_size
              } sale${est.sample_size === 1 ? "" : "s"}.`;
            })
          }
        >
          {busy === "estimate" ? "Estimating…" : `Estimate from ${counted} sale${counted === 1 ? "" : "s"}`}
        </button>
        {!formOpen && <button onClick={() => setFormOpen(true)}>＋ Log a sale</button>}
        {numistaSales && (
          <button
            disabled={busy !== null || !hasNumistaRef}
            title={
              hasNumistaRef
                ? "Add Numista's recorded auction sales for this issue (paid Numista API plan)"
                : "Add a 'numista' catalog reference (e.g. N#1234) first"
            }
            onClick={() =>
              run("numista", async () => {
                const r = await api.fetchNumistaSales(item.id);
                return r.found === 0
                  ? "Numista has no recorded auction sales for this issue."
                  : `Numista returned ${r.found} sale${r.found === 1 ? "" : "s"}: ${r.added} added, ${
                      r.already_logged
                    } already in the log.`;
              })
            }
          >
            {busy === "numista" ? "Fetching…" : "Fetch Numista auction sales"}
          </button>
        )}
      </div>

      {formOpen && (
        <form className="estimate-form sale-form" onSubmit={save}>
          <label className="field">
            Sold on
            <input required type="date" value={draft.sold_on} max={today()}
              onChange={(e) => set("sold_on")(e.target.value)} />
          </label>
          <label className="field">
            Where
            <input required list="sale-venues" maxLength={200} value={draft.venue}
              placeholder="eBay, Heritage…" onChange={(e) => set("venue")(e.target.value)} />
            <datalist id="sale-venues">
              {VENUES.map((v) => <option key={v} value={v} />)}
            </datalist>
          </label>
          <label className="field">
            Grade as sold
            <input maxLength={100} value={draft.grade} placeholder="e.g. NGC MS64, raw VF"
              style={{ width: "9rem" }} onChange={(e) => set("grade")(e.target.value)} />
          </label>
          <label className="field">
            Price (per piece)
            <input required type="number" step="0.01" min="0.01" value={draft.price}
              style={{ width: "7rem" }} onChange={(e) => set("price")(e.target.value)} />
          </label>
          <label className="field">
            Currency
            <input required maxLength={3} value={draft.currency} style={{ width: "4.5rem" }}
              onChange={(e) => set("currency")(e.target.value)} />
          </label>
          <label className="field">
            Buyer's premium
            <select value={draft.premium} onChange={(e) => set("premium")(e.target.value)}>
              <option value="">not sure</option>
              <option value="yes">included</option>
              <option value="no">not included</option>
            </select>
          </label>
          <label className="field">
            Fees on top
            <input type="number" step="0.01" min="0" value={draft.fees} placeholder="optional"
              style={{ width: "6rem" }} onChange={(e) => set("fees")(e.target.value)} />
          </label>
          <label className="field">
            Link
            <input type="url" maxLength={1000} value={draft.url} placeholder="https://…"
              onChange={(e) => set("url")(e.target.value)} />
          </label>
          <label className="field">
            Lot
            <input maxLength={50} value={draft.lot} style={{ width: "5rem" }}
              onChange={(e) => set("lot")(e.target.value)} />
          </label>
          <label className="field">
            Note
            <input maxLength={1000} value={draft.note} placeholder="optional"
              onChange={(e) => set("note")(e.target.value)} />
          </label>
          <button className="primary" type="submit" disabled={busy !== null}>
            {editingId !== null ? "Save changes" : "Log sale"}
          </button>
          <button type="button" onClick={closeForm}>
            {editingId !== null ? "Cancel" : "Done"}
          </button>
        </form>
      )}

      <details className="history" style={{ marginTop: "0.75rem" }}>
        <summary>Where to find sold prices</summary>
        <ul className="sale-help">
          <li>
            <b>eBay</b>: search for the coin or note, then tick <i>Sold items</i> under Filter.
            Shows roughly the last 90 days. Shipping is listed separately, so add it under
            <i> Fees on top</i> if you want it counted.
          </li>
          <li>
            <b>Heritage Auctions</b> (coins.ha.com, currency.ha.com): free membership opens the
            prices-realized archive back to 1997. Prices include the buyer's premium.
          </li>
          <li>
            <b>GreatCollections</b>: a free archive of about 1.6 million certified US coins and
            notes. Prices include the buyer's premium.
          </li>
          <li>
            <b>NGC Auction Central</b> and <b>PCGS Auction Prices</b>: free results from several
            auction houses, by grading-service number and grade.
          </li>
          <li>
            <b>Spink</b>, <b>Stack's Bowers</b>, <b>Sixbid</b>, <b>NumisBids</b>: archives with
            prices realized, strong on world coins and banknotes.
          </li>
        </ul>
        <p className="muted">
          Log sales in the same grade as your piece where you can; a sale with a known grade
          bucket that differs from this item's is kept but not counted. Numista's auction records
          can fill this log automatically, but only on Numista's paid API plan; see Settings →
          Price sources.
        </p>
      </details>
    </div>
  );
}
