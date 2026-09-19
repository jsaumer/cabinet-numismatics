import { FormEvent, Fragment, useEffect, useState } from "react";

import { api, ItemDetail, money, SourceStatus } from "../api";
import { LineChart } from "./charts";
import { latestBySource, Provenance, SOURCE_LABELS, sourceKey } from "./provenance";

/** The item page's Value history card: every estimate with its provenance,
 * a per-source filter, the automatic-source buttons, and the manual form. */
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
  const [historySource, setHistorySource] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

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
      onChanged();
    } catch (err) {
      setEstimateError((err as Error).message);
    }
  }

  async function autoEstimate(source: string) {
    setEstimating(source);
    setEstimateError(null);
    setEstimateSuccess(null);
    try {
      await api.autoEstimate(item.id, source);
      setEstimateSuccess(`${SOURCE_LABELS[source] ?? source} updated.`);
      onChanged();
    } catch (err) {
      setEstimateError((err as Error).message);
    } finally {
      setEstimating(null);
    }
  }

  const sourceValues = latestBySource(item.estimates);
  const activeSource =
    historySource && sourceValues.some(([key]) => key === historySource) ? historySource : null;
  const history = activeSource
    ? item.estimates.filter((est) => sourceKey(est.source) === activeSource)
    : item.estimates;
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
      {item.estimates.length === 0 && (
        <p className="muted">
          No value recorded yet — add one you researched, or try an automatic estimate.
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
          {sourceValues.map(([key]) => (
            <button
              key={key}
              type="button"
              className={activeSource === key ? "chip active" : "chip"}
              onClick={() => setHistorySource(key)}
            >
              {key}
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
                      {est.confidence == null ? "—" : `${Math.round(est.confidence * 100)}%`}
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
            placeholder="optional — e.g. eBay lot, sold 2026-08-01, raw"
            onChange={(e) => setEstNote(e.target.value)} />
        </label>
        <button className="primary" type="submit">Record value</button>
      </form>
    </div>
  );
}
