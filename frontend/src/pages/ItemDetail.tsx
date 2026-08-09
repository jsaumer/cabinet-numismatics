import { FormEvent, useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { Angle, api, ItemDetail as ItemDetailData, money, photoUrl } from "../api";

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

  const reload = useCallback(() => {
    if (!id) return;
    api.getItem(id).then(setItem).catch((e: Error) => setError(e.message));
  }, [id]);

  useEffect(reload, [reload]);

  if (error) return <p className="error">{error}</p>;
  if (!item) return <p className="muted">Loading…</p>;

  const act = (fn: () => Promise<unknown>) => () =>
    fn().then(reload).catch((e: Error) => setError(e.message));

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
      });
      setEstValue("");
      reload();
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

  return (
    <>
      <div className="detail-header">
        <h1>
          {item.country} {item.denomination}, {item.year}
          {item.mint_mark ? ` "${item.mint_mark}"` : ""}
        </h1>
        <span className={`badge ${item.type}`}>{item.type}</span>
        <div className="spacer" />
        <Link className="button" to={`/items/${item.id}/edit`}>Edit</Link>
        <button className="danger" onClick={deleteItem}>Delete</button>
      </div>

      <div className="card">
        <dl className="facts">
          <div><dt>Series</dt><dd>{item.series ?? "—"}</dd></div>
          <div><dt>Quantity</dt><dd>{item.quantity}</dd></div>
          <div><dt>Acquired</dt><dd>{item.acquisition_date ?? "—"}</dd></div>
          <div><dt>Paid</dt><dd>{money(item.acquisition_price, item.currency)}</dd></div>
          <div><dt>Latest value</dt>
            <dd>{latest ? money(latest.estimated_value, latest.currency) : "—"}</dd></div>
        </dl>
        {item.notes && <p style={{ marginBottom: 0, whiteSpace: "pre-wrap" }}>{item.notes}</p>}
      </div>

      <div className="card">
        <h2>Photos</h2>
        {item.photos.length === 0 && <p className="muted">No photos yet.</p>}
        <div className="photo-grid">
          {item.photos.map((photo) => (
            <div key={photo.id} className={`photo-card${photo.is_primary ? " primary" : ""}`}>
              <a href={photoUrl(photo.file_key)} target="_blank" rel="noreferrer">
                <img src={photoUrl(photo.file_key)} alt={photo.angle ?? "photo"} />
              </a>
              <div className="row">
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
                <button
                  title="Delete photo"
                  onClick={act(() => api.deletePhoto(photo.id))}
                >
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
            <select value={uploadAngle} onChange={(e) => setUploadAngle(e.target.value as Angle | "")}>
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
          <p className="muted">No value recorded yet — add one you researched below.</p>
        )}
        {item.estimates.length > 0 && (
          <table className="estimates">
            <thead>
              <tr><th>Date</th><th>Value</th><th>Source</th></tr>
            </thead>
            <tbody>
              {item.estimates.map((est) => (
                <tr key={est.id}>
                  <td>{new Date(est.fetched_at).toLocaleDateString()}</td>
                  <td>{money(est.estimated_value, est.currency)}</td>
                  <td className="muted">{est.source}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
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
          <button className="primary" type="submit">Record value</button>
        </form>
      </div>
    </>
  );
}
