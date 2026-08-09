import { useEffect, useState } from "react";

import { api, CollectionStats, ItemListEntry, money, photoUrl } from "../api";

/* Print-optimized insurance report: use the browser's Print → Save as PDF.
   The site chrome is hidden by the print stylesheet. */
export default function Report() {
  const [items, setItems] = useState<ItemListEntry[] | null>(null);
  const [stats, setStats] = useState<CollectionStats | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api.allItems(), api.collectionStats()])
      .then(([all, s]) => {
        setItems(all.filter((i) => i.status === "owned"));
        setStats(s);
      })
      .catch((e: Error) => setError(e.message));
  }, []);

  if (error) return <p className="error">{error}</p>;
  if (!items || !stats) return <p className="muted">Preparing report…</p>;

  const cur = stats.currency;

  return (
    <div className="report">
      <div className="report-actions no-print">
        <button className="primary" onClick={() => window.print()}>
          Print / save as PDF
        </button>
        <span className="muted">
          Values are estimates for guidance, not professional appraisals.
        </span>
      </div>

      <header className="report-header">
        <h1>Cabinet — Collection Report</h1>
        <p className="muted">
          Generated {new Date().toLocaleDateString()} · {items.length} owned item(s) · estimated
          value {money(stats.estimated_value, cur)}
          {stats.estimated_items < stats.counts.owned &&
            ` (${stats.estimated_items} of ${stats.counts.owned} items estimated)`}{" "}
          · cost basis {money(stats.cost_basis, cur)}
        </p>
      </header>

      <table className="report-table">
        <thead>
          <tr>
            <th></th>
            <th>Item</th>
            <th>Grade / cert</th>
            <th className="num">Qty</th>
            <th>Acquired</th>
            <th className="num">Paid</th>
            <th className="num">Est. value</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr key={item.id}>
              <td className="report-photo">
                {item.primary_thumb_key && (
                  <img src={photoUrl(item.primary_thumb_key)} alt="" />
                )}
              </td>
              <td>
                <b>
                  {item.country} {item.denomination}, {item.year}
                  {item.mint_mark ? ` "${item.mint_mark}"` : ""}
                </b>
                {item.series && <div className="muted">{item.series}</div>}
                {item.composition && (
                  <div className="muted">
                    {item.composition}
                    {item.weight_g != null && ` · ${item.weight_g} g`}
                  </div>
                )}
                {item.storage_location && <div className="muted">@ {item.storage_location}</div>}
              </td>
              <td>
                {item.grade?.code ?? "—"}
                {item.cert_service && (
                  <div className="muted">
                    {item.cert_service} {item.cert_number ?? ""}
                  </div>
                )}
              </td>
              <td className="num">{item.quantity}</td>
              <td>
                {item.acquisition_date ?? "—"}
                {item.acquired_from && <div className="muted">{item.acquired_from}</div>}
              </td>
              <td className="num">{money(item.acquisition_price, item.currency)}</td>
              <td className="num">{money(item.latest_value, item.latest_value_currency)}</td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr>
            <td colSpan={5}><b>Totals ({cur})</b></td>
            <td className="num"><b>{money(stats.cost_basis, cur)}</b></td>
            <td className="num"><b>{money(stats.estimated_value, cur)}</b></td>
          </tr>
        </tfoot>
      </table>

      <p className="muted report-footnote">
        Estimated values are the latest recorded estimate per item (manual research or automatic
        melt/source estimates) and are guidance only. For insurance or sale, obtain a professional
        appraisal. Items in currencies other than {cur} are shown per item but excluded from
        totals.
      </p>
    </div>
  );
}
