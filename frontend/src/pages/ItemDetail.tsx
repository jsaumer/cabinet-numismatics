import { FormEvent, useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { Angle, api, ItemDetail as ItemDetailData, ItemEvent, money, photoUrl } from "../api";
import { LineChart } from "../components/charts";

const ANGLES: Angle[] = ["obverse", "reverse", "edge", "other"];

export default function ItemDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [item, setItem] = useState<ItemDetailData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadAngle, setUploadAngle] = useState<Angle | "">("");
  const [estValue, setEstValue] = useState("");
  const [estCurrency, setEstCurrency] = useState("USD");
  const [estSource, setEstSource] = useState("manual");
  const [estConfidence, setEstConfidence] = useState("");
  const [estimating, setEstimating] = useState(false);
  const [estimateError, setEstimateError] = useState<string | null>(null);
  const [events, setEvents] = useState<ItemEvent[] | null>(null);

  const loadHistory = () => {
    if (!id) return;
    api.itemHistory(id).then(setEvents).catch(() => setEvents([]));
  };

  const reload = useCallback(() => {
    if (!id) return;
    api.getItem(id).then(setItem).catch((e: Error) => setError(e.message));
  }, [id]);

  useEffect(reload, [reload]);

  if (error) return <p className="error">{error}</p>;
  if (!item) return <p className="muted">Loading…</p>;

  const act = (fn: () => Promise<unknown>) => () =>
    fn().then(reload).catch((e: Error) => setError(e.message));

  const movePhoto = (index: number, delta: number) => {
    const order = item.photos.map((p) => p.id);
    const target = index + delta;
    if (target < 0 || target >= order.length) return;
    [order[index], order[target]] = [order[target], order[index]];
    act(() => api.reorderPhotos(item.id, order))();
  };

  async function upload(e: FormEvent<HTMLInputElement>) {
    const file = e.currentTarget.files?.[0];
    if (!file || !id) return;
    setUploading(true);
    setError(null);
    try {
      await api.uploadPhoto(id, file, uploadAngle);
      reload();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setUploading(false);
      e.currentTarget.value = "";
    }
  }

  async function addEstimate(e: FormEvent) {
    e.preventDefault();
    if (!id || !estValue) return;
    setError(null);
    try {
      await api.addEstimate(id, {
        estimated_value: Number(estValue),
        currency: estCurrency.trim().toUpperCase(),
        source: estSource.trim() || "manual",
        confidence: estConfidence === "" ? null : Number(estConfidence),
      });
      setEstValue("");
      reload();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function autoEstimate() {
    if (!id) return;
    setEstimating(true);
    setEstimateError(null);
    try {
      await api.autoEstimate(id);
      reload();
    } catch (err) {
      setEstimateError((err as Error).message);
    } finally {
      setEstimating(false);
    }
  }

  async function cloneItem() {
    if (!id) return;
    try {
      const copy = await api.cloneItem(id);
      navigate(`/items/${copy.id}/edit`);
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function deleteItem() {
    if (!id || !window.confirm("Delete this item and all its photos?")) return;
    try {
      await api.deleteItem(id);
      navigate("/");
    } catch (err) {
      setError((err as Error).message);
    }
  }

  const latest = item.estimates[0];
  const fact = (label: string, value: string | number | null | undefined) => (
    <div>
      <dt>{label}</dt>
      <dd>{value == null || value === "" ? "—" : value}</dd>
    </div>
  );

  return (
    <>
      <div className="detail-header">
        <h1>
          {item.country} {item.denomination}, {item.year}
          {item.mint_mark ? ` "${item.mint_mark}"` : ""}
        </h1>
        <span className={`badge ${item.type}`}>{item.type}</span>
        {item.status !== "owned" && (
          <span className={`badge status-${item.status}`}>{item.status}</span>
        )}
        <div className="spacer" />
        <button onClick={cloneItem}>Clone</button>
        <Link className="button" to={`/items/${item.id}/edit`}>Edit</Link>
        <button className="danger" onClick={deleteItem}>Delete</button>
      </div>

      <div className="card">
        <dl className="facts">
          {fact("Series", item.series)}
          {fact("Variety", item.variety)}
          {fact("Set / lot", item.set?.name)}
          {fact("Grade", item.grade ? `${item.grade.code} (${item.grade.label})` : null)}
          {fact(
            "Certification",
            item.cert_service ? `${item.cert_service} ${item.cert_number ?? ""}`.trim() : null,
          )}
          {fact("Composition", item.composition)}
          {fact("Weight", item.weight_g != null ? `${item.weight_g} g` : null)}
          {fact("Fineness", item.fineness)}
          {fact("Quantity", item.quantity)}
          {fact("Acquired", item.acquisition_date)}
          {fact("Paid", money(item.acquisition_price, item.currency))}
          {fact("From", item.acquired_from)}
          {fact("Storage", item.storage_location)}
          {item.status === "sold" && fact("Sold on", item.sold_date)}
          {item.status === "sold" && fact("Sold for", money(item.sold_price, item.currency))}
          {fact("Latest value", latest ? money(latest.estimated_value, latest.currency) : null)}
          {Object.entries(item.custom_fields ?? {}).map(([key, value]) => (
            <div key={key}><dt>{key}</dt><dd>{value}</dd></div>
          ))}
        </dl>
        {(item.tags.length > 0 || item.catalog_refs.length > 0) && (
          <p style={{ marginBottom: 0 }}>
            {item.tags.map((t) => (
              <Link key={t} className="chip" to={`/?tag=${encodeURIComponent(t)}`}>{t}</Link>
            ))}
            {item.catalog_refs.map((r) => (
              <span key={`${r.catalog}:${r.ref_code}`} className="chip ref">
                {r.catalog}: {r.ref_code}
              </span>
            ))}
          </p>
        )}
        {item.notes && <p style={{ marginBottom: 0, whiteSpace: "pre-wrap" }}>{item.notes}</p>}
      </div>

      <div className="card">
        <h2>Photos</h2>
        {item.photos.length === 0 && <p className="muted">No photos yet.</p>}
        <div className="photo-grid">
          {item.photos.map((photo, index) => (
            <div key={photo.id} className={`photo-card${photo.is_primary ? " primary" : ""}`}>
              <a href={photoUrl(photo.file_key)} target="_blank" rel="noreferrer">
                <img src={photoUrl(photo.thumb_key ?? photo.file_key)}
                  alt={photo.angle ?? "photo"} />
              </a>
              <div className="row">
                <button title="Move left" disabled={index === 0}
                  onClick={() => movePhoto(index, -1)}>←</button>
                <select
                  value={photo.angle ?? ""}
                  onChange={(e) =>
                    act(() => api.updatePhoto(photo.id, { angle: e.target.value as Angle }))()
                  }
                >
                  <option value="" disabled>angle…</option>
                  {ANGLES.map((a) => (
                    <option key={a} value={a}>{a}</option>
                  ))}
                </select>
                <button title="Move right" disabled={index === item.photos.length - 1}
                  onClick={() => movePhoto(index, 1)}>→</button>
                <button title="Delete photo" onClick={act(() => api.deletePhoto(photo.id))}>
                  ✕
                </button>
              </div>
              <div className="row">
                {photo.is_primary ? (
                  <span className="muted">★ primary</span>
                ) : (
                  <button onClick={act(() => api.updatePhoto(photo.id, { is_primary: true }))}>
                    Make primary
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
        <div className="estimate-form">
          <label className="field">
            Angle
            <select value={uploadAngle}
              onChange={(e) => setUploadAngle(e.target.value as Angle | "")}>
              <option value="">unspecified</option>
              {ANGLES.map((a) => (
                <option key={a} value={a}>{a}</option>
              ))}
            </select>
          </label>
          <label className="field">
            {uploading ? "Uploading…" : "Add photo"}
            <input type="file" accept="image/jpeg,image/png,image/webp"
              disabled={uploading} onChange={upload} />
          </label>
        </div>
      </div>

      <div className="card">
        <h2>Value history</h2>
        {item.estimates.length === 0 && (
          <p className="muted">
            No value recorded yet — add one you researched, or try an automatic estimate.
          </p>
        )}
        {item.estimates.length >= 2 && (
          <LineChart
            data={[...item.estimates].reverse().map((est) => ({
              key: new Date(est.fetched_at).toLocaleDateString(undefined, {
                month: "short", day: "numeric",
              }),
              value: est.estimated_value,
            }))}
            format={(v) => money(v, item.estimates[0].currency)}
          />
        )}
        {item.estimates.length > 0 && (
          <table className="estimates">
            <thead>
              <tr><th>Date</th><th>Value</th><th>Source</th><th>Confidence</th></tr>
            </thead>
            <tbody>
              {item.estimates.map((est) => (
                <tr key={est.id}>
                  <td>{new Date(est.fetched_at).toLocaleDateString()}</td>
                  <td>{money(est.estimated_value, est.currency)}</td>
                  <td className="muted">{est.source}</td>
                  <td className="muted">
                    {est.confidence == null ? "—" : `${Math.round(est.confidence * 100)}%`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <div className="estimate-form">
          <button onClick={autoEstimate} disabled={estimating}>
            {estimating ? "Estimating…" : "⚖ Melt value"}
          </button>
          {estimateError && <span className="error">{estimateError}</span>}
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
          <button className="primary" type="submit">Record value</button>
        </form>
      </div>

      <details className="history" onToggle={(e) => e.currentTarget.open && loadHistory()}>
        <summary>Edit history</summary>
        {events === null && <p className="muted">Loading…</p>}
        {events && events.length === 0 && <p className="muted">No history recorded.</p>}
        {events?.map((event) => (
          <div className="history-entry" key={event.id}>
            <span className="muted">{new Date(event.at).toLocaleString()}</span> — {event.action}
            {event.changes && (
              <>
                {": "}
                {Object.entries(event.changes).map(([field, [from, to]]) => (
                  <span key={field}>
                    <code>{field}</code>{" "}
                    <span className="muted">
                      {JSON.stringify(from)} → {JSON.stringify(to)}
                    </span>{" "}
                  </span>
                ))}
              </>
            )}
          </div>
        ))}
      </details>
    </>
  );
}
