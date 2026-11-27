import { FormEvent, Fragment, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api, Estimate, ItemDetail, money, SourceKey, SourceStatus } from "../api";
import { LineChart } from "./charts";
import { chipName, Provenance, SOURCE_LABELS } from "./provenance";

/** The item page's Value history card: the estimates with their provenance,
 * a per-source filter, the automatic-source buttons, and the manual form.
 * The item carries only the newest estimate per source, so the history is
 * fetched here, a page at a time ("Show older"). */
export function ValueHistory({
  item,
  sources,
  onChanged,
}: {
  item: ItemDetail;
  sources: SourceStatus[];
  onChanged: () => void;
}) {
  const [estValue, setEstValue] = useState("");
  const [estCurrency, setEstCurrency] = useState(item.currency);
  const [estSource, setEstSource] = useState("manual");
  const [estConfidence, setEstConfidence] = useState("");
  const [estNote, setEstNote] = useState("");
  const [estimating, setEstimating] = useState<string | null>(null);
  const [estimateError, setEstimateError] = useState<string | null>(null);
  const [estimateSuccess, setEstimateSuccess] = useState<string | null>(null);
  const [historySource, setHistorySource] = useState<SourceKey | null>(null);
  const [history, setHistory] = useState<Estimate[]>([]);
  const [total, setTotal] = useState(0);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [lastTried, setLastTried] = useState<string | null>(null);
  const [changes, setChanges] = useState(0);

  // default the manual-estimate currency to the item's own currency
  const itemCurrency = item.currency;
  useEffect(() => {
    setEstCurrency(itemCurrency);
  }, [itemCurrency]);

  async function addEstimate(e: FormEvent) {
    e.preventDefault();
    if (!estValue) return;
    setEstimateError(null);
    try {
      await api.addEstimate(item.id, {
        estimated_value: Number(estValue),
        currency: estCurrency.trim().toUpperCase(),
        source: estSource.trim() || "manual",
        confidence: estConfidence === "" ? null : Number(estConfidence),
        note: estNote.trim() || null,
      });
      setEstValue("");
      setEstNote("");
      setChanges((n) => n + 1);
      onChanged();
    } catch (err) {
      setEstimateError((err as Error).message);
    }
  }

  // Only a typed-in value can go; what a source said is the record.
  const typed = (est: Estimate) => est.source_key === "manual";

  async function removeEstimate(id: string) {
    if (!window.confirm("Delete this value? It can't be brought back.")) return;
    setEstimateError(null);
    setEstimateSuccess(null);
    try {
      await api.deleteEstimate(item.id, id);
      setChanges((n) => n + 1);
      onChanged();
    } catch (err) {
      setEstimateError((err as Error).message);
    }
  }

  async function autoEstimate(source: string) {
    setEstimating(source);
    setLastTried(source);
    setEstimateError(null);
    setEstimateSuccess(null);
    try {
      await api.autoEstimate(item.id, source);
      setEstimateSuccess(`${SOURCE_LABELS[source] ?? source} updated.`);
      setChanges((n) => n + 1);
      onChanged();
    } catch (err) {
      setEstimateError((err as Error).message);
    } finally {
      setEstimating(null);
    }
  }

  // Numista prices by its catalogue number; an item entered by hand has none.
  const needsNumistaRef =
    estimateError !== null &&
    lastTried === "numista" &&
    !item.catalog_refs.some((r) => r.catalog.trim().toLowerCase() === "numista");

  const sourceValues = item.latest_estimates;
  const activeSource =
    historySource && sourceValues.some((est) => est.source_key === historySource)
      ? historySource
      : null;

  // The first page again whenever the piece, the filter, or its values change
  // (the newest ids cover a refresh made elsewhere; `changes`, one made here
  // that left the newest as it was, such as deleting an older typed-in value).
  const newest = sourceValues.map((est) => est.id).join(",");
  useEffect(() => {
    let stale = false;
    setHistoryError(null);
    api
      .itemEstimates(item.id, activeSource)
      .then((page) => {
        if (stale) return;
        setHistory(page.items);
        setTotal(page.total);
      })
      .catch((err) => {
        if (!stale) setHistoryError((err as Error).message);
      });
    return () => {
      stale = true;
    };
  }, [item.id, activeSource, newest, changes]);

  async function showOlder() {
    try {
      const page = await api.itemEstimates(item.id, activeSource, history.length);
      setHistory((shown) => [...shown, ...page.items]);
      setTotal(page.total);
    } catch (err) {
      setHistoryError((err as Error).message);
    }
  }
  const toggleExpanded = (estId: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(estId)) next.delete(estId);
      else next.add(estId);
      return next;
    });

  return (
    <div className="card">
      <h2>Value history</h2>
      {sourceValues.length === 0 && (
        <p className="muted">
          No value recorded yet. Add one you researched, or try an automatic estimate.
        </p>
      )}
      {sourceValues.length >= 2 && (
        <div className="chip-row history-filter">
          <button
            type="button"
            className={activeSource === null ? "chip active" : "chip"}
            onClick={() => setHistorySource(null)}
          >
            All
          </button>
          {sourceValues.map((est) => (
            <button
              key={est.source_key}
              type="button"
              className={activeSource === est.source_key ? "chip active" : "chip"}
              onClick={() => setHistorySource(est.source_key)}
            >
              {est.source_key === "manual" ? "typed in" : chipName(est)}
            </button>
          ))}
        </div>
      )}
      {history.length >= 2 && (
        <LineChart
          data={[...history].reverse().map((est) => ({
            key: new Date(est.fetched_at).toLocaleDateString(undefined, {
              month: "short", day: "numeric",
            }),
            value: est.estimated_value,
          }))}
          format={(v) => money(v, history[0].currency)}
        />
      )}
      {history.length > 0 && (
        <table className="estimates">
          <thead>
            <tr><th>Date</th><th>Value</th><th>Source</th><th>Confidence</th><th></th></tr>
          </thead>
          <tbody>
            {history.map((est) => {
              const open = expanded.has(est.id);
              return (
                <Fragment key={est.id}>
                  <tr>
                    <td>{new Date(est.fetched_at).toLocaleDateString()}</td>
                    <td>{money(est.estimated_value, est.currency)}</td>
                    <td className="muted">{est.source}</td>
                    <td className="muted">
                      {est.confidence == null ? "–" : `${Math.round(est.confidence * 100)}%`}
                    </td>
                    <td className="provenance-toggle">
                      {est.details && (
                        <button
                          type="button"
                          className="link-button"
                          aria-expanded={open}
                          onClick={() => toggleExpanded(est.id)}
                        >
                          {open ? "▾ details" : "▸ details"}
                        </button>
                      )}
                      {typed(est) && (
                        <button
                          type="button"
                          className="link-button danger-link"
                          title="Delete this typed-in value"
                          onClick={() => removeEstimate(est.id)}
                        >
                          delete
                        </button>
                      )}
                    </td>
                  </tr>
                  {est.details && open && (
                    <tr className="provenance-row">
                      <td colSpan={5}>
                        <Provenance estimate={est} />
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      )}
      {history.length < total && (
        <p>
          <button type="button" className="link-button" onClick={showOlder}>
            Show older
          </button>{" "}
          <span className="muted">
            {history.length} of {total} shown
          </span>
        </p>
      )}
      {historyError && <p className="error">{historyError}</p>}
      <div className="estimate-form">
        {sources
          .filter((s) => s.available)
          .map((s) => (
            <button
              key={s.key}
              onClick={() => autoEstimate(s.key)}
              disabled={estimating !== null || !s.enabled}
              title={s.enabled ? s.note ?? undefined : `${s.name} is switched off in Settings`}
            >
              {estimating === s.key ? "Estimating…" : SOURCE_LABELS[s.key] ?? s.name}
            </button>
          ))}
        {estimateError && <span className="error">{estimateError}</span>}
        {needsNumistaRef && (
          <span>
            <Link to={`/items/${item.id}/edit`}>Find it on Numista</Link>:{" "}
            <span className="muted">
              “Fill from Numista” on the edit page looks the piece up and adds its number; what
              you've already filled in stays as it is.
            </span>
          </span>
        )}
        {estimateSuccess && <span className="gain">{estimateSuccess}</span>}
      </div>
      <form className="estimate-form" onSubmit={addEstimate}>
        <label className="field">
          Value
          <input required type="number" step="0.01" min="0.01" value={estValue}
            onChange={(e) => setEstValue(e.target.value)} style={{ width: "7rem" }} />
        </label>
        <label className="field">
          Currency
          <input value={estCurrency} maxLength={3} style={{ width: "4.5rem" }}
            onChange={(e) => setEstCurrency(e.target.value)} />
        </label>
        <label className="field">
          Source
          <input value={estSource} placeholder="e.g. eBay sold, Red Book"
            onChange={(e) => setEstSource(e.target.value)} />
        </label>
        <label className="field">
          Confidence (0–1)
          <input type="number" step="0.05" min="0" max="1" value={estConfidence}
            placeholder="optional" style={{ width: "6rem" }}
            onChange={(e) => setEstConfidence(e.target.value)} />
        </label>
        <label className="field">
          Note
          <input value={estNote} maxLength={500}
            placeholder="optional, e.g. eBay lot, sold 2026-08-01, raw"
            onChange={(e) => setEstNote(e.target.value)} />
        </label>
        <button className="primary" type="submit">Record value</button>
      </form>
    </div>
  );
}
