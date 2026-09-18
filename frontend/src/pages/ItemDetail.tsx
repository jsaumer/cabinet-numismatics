import { FormEvent, Fragment, useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import {
  Angle,
  api,
  certLookupUrl,
  Estimate,
  ItemDetail as ItemDetailData,
  ItemEvent,
  money,
  Photo,
  photoUrl,
  SourceStatus,
} from "../api";
import { LineChart } from "../components/charts";
import { Lightbox, PhotoEditor, WebcamCapture } from "../components/photos";
import { SalesLog } from "../components/sales";

const ANGLES: Angle[] = ["obverse", "reverse", "edge", "other"];
const SOURCE_LABELS: Record<string, string> = {
  melt: "⚖ Melt value",
  numista: "🔎 Numista value",
  pcgs: "🏷 PCGS value",
  comps: "📈 Comps value",
};

function timeSince(iso: string): string {
  const diffMs = Date.now() - new Date(iso).getTime();
  const minutes = Math.floor(diffMs / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  return new Date(iso).toLocaleDateString();
}

function sourceKey(source: string): string {
  const i = source.indexOf(":");
  return i === -1 ? source : source.slice(0, i);
}

type Details = Record<string, unknown>;
const num = (value: unknown) => (typeof value === "number" ? value : null);
const text = (value: unknown) => (typeof value === "string" && value ? value : null);
const externalUrl = (url: string) => (/^https?:\/\//i.test(url) ? url : `https://${url}`);

function DataAge({ details }: { details: Details }) {
  const asOf = text(details.data_as_of);
  if (!asOf) return null;
  return details.stale ? (
    <span className="error"> · served from cache, fetched {timeSince(asOf)} (refresh failed)</span>
  ) : (
    <span className="muted"> · data fetched {timeSince(asOf)}</span>
  );
}

// What the source returned that produced an estimate — or the note left on a
// manual one. Unknown shapes fall back to a plain field list.
function Provenance({ estimate }: { estimate: Estimate }) {
  const d: Details = estimate.details ?? {};
  const key = sourceKey(estimate.source);

  if (key === "melt") {
    const quantity = num(d.quantity) ?? 1;
    return (
      <div className="provenance">
        {num(d.weight_g)} g × {num(d.fineness)?.toFixed(3)} fine
        {d.fineness_from === "composition" && <span className="muted"> (from composition)</span>}
        {" × "}
        {num(d.spot_per_gram)?.toFixed(4)} {text(d.spot_currency)}/g {text(d.metal)} spot
        {quantity !== 1 && ` × ${quantity} pieces`}
        {text(d.spot_source) && <span className="muted"> · {text(d.spot_source)}</span>}
        <DataAge details={d} />
      </div>
    );
  }

  if (key === "numista") {
    const prices = (d.prices && typeof d.prices === "object" ? d.prices : {}) as Record<
      string,
      number
    >;
    const used = text(d.grade_used);
    const wanted = text(d.grade_wanted);
    const currency = text(d.currency) ?? estimate.currency;
    const quantity = num(d.quantity) ?? 1;
    return (
      <div className="provenance">
        <div>
          <a
            href={`https://en.numista.com/catalogue/pieces${String(d.type_id)}.html`}
            target="_blank"
            rel="noreferrer"
          >
            N#{String(d.type_id)}
          </a>
          {num(d.issue_year) != null && ` · ${num(d.issue_year)} issue`}
          {text(d.mint_letter) && ` (${text(d.mint_letter)})`}
          {used && (
            <>
              {" · priced at "}
              <b>{used.toUpperCase()}</b>
            </>
          )}
          {wanted && used && wanted !== used && (
            <span className="muted"> — no {wanted.toUpperCase()} price, nearest bucket used</span>
          )}
          {quantity !== 1 && <span className="muted"> · per piece, × {quantity}</span>}
          <DataAge details={d} />
        </div>
        <div className="chip-row">
          {Object.entries(prices).map(([grade, price]) => (
            <span key={grade} className={grade === used ? "chip active" : "chip"}>
              {grade.toUpperCase()} {money(price, currency)}
            </span>
          ))}
        </div>
      </div>
    );
  }

  if (key === "pcgs") {
    const lots = Array.isArray(d.lots) ? (d.lots as Details[]) : [];
    const guide = num(d.price_guide_value);
    const coinfacts = text(d.coinfacts_url);
    return (
      <div className="provenance">
        <div>
          {d.lookup === "cert"
            ? `Cert ${String(d.cert)}`
            : `PCGS #${String(d.pcgs_number)} ${String(d.grade ?? "")}`}
          {" · "}
          {d.basis === "apr"
            ? `median of ${lots.length} recent auction sale${lots.length === 1 ? "" : "s"}`
            : "price guide (no recent auction sales)"}
          {guide != null && <span className="muted"> · guide {money(guide, "USD")}</span>}
          {coinfacts && (
            <>
              {" · "}
              <a href={externalUrl(coinfacts)} target="_blank" rel="noreferrer">
                CoinFacts
              </a>
            </>
          )}
          <DataAge details={d} />
        </div>
        {lots.length > 0 && (
          <ul className="provenance-lots">
            {lots.map((lot, index) => {
              const url = text(lot.url);
              return (
                <li key={index}>
                  {text(lot.date) ?? "undated"} — {money(num(lot.price), "USD")}
                  {text(lot.auctioneer) && <span className="muted"> · {text(lot.auctioneer)}</span>}
                  {url && (
                    <>
                      {" · "}
                      <a href={externalUrl(url)} target="_blank" rel="noreferrer">
                        lot
                      </a>
                    </>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </div>
    );
  }

  if (key === "comps") {
    const sales = Array.isArray(d.sales) ? (d.sales as Details[]) : [];
    const currency = text(d.currency) ?? estimate.currency;
    const quantity = num(d.quantity) ?? 1;
    const excluded = num(d.excluded_other_currency) ?? 0;
    const bucket = text(d.grade_bucket);
    return (
      <div className="provenance">
        <div>
          Median {money(num(d.median), currency)} of {sales.length} logged sale
          {sales.length === 1 ? "" : "s"}
          {bucket && ` in ${bucket.toUpperCase()}`}
          {num(d.spread_pct) != null && (
            <span className="muted"> · typical spread ±{num(d.spread_pct)}%</span>
          )}
          {quantity !== 1 && <span className="muted"> · per piece, × {quantity}</span>}
          {d.older_sales_used === true && (
            <span className="muted"> · includes sales older than {num(d.window_years)} years</span>
          )}
          {excluded > 0 && (
            <span className="muted"> · {excluded} left out (no exchange rate)</span>
          )}
        </div>
        <ul className="provenance-lots">
          {sales.map((sale, index) => {
            const url = text(sale.url);
            return (
              <li key={index}>
                {text(sale.date)} — {money(num(sale.converted), currency)}
                {text(sale.currency) !== currency && (
                  <span className="muted"> ({money(num(sale.price), text(sale.currency))})</span>
                )}
                {" · "}
                {url ? (
                  <a href={externalUrl(url)} target="_blank" rel="noreferrer">
                    {text(sale.venue)}
                  </a>
                ) : (
                  text(sale.venue)
                )}
                {text(sale.grade) && <span className="muted"> · {text(sale.grade)}</span>}
                {sale.source === "numista" && <span className="muted"> · via Numista</span>}
              </li>
            );
          })}
        </ul>
      </div>
    );
  }

  const note = text(d.note);
  if (note) return <div className="provenance note">{note}</div>;

  return (
    <div className="provenance">
      {Object.entries(d).map(([field, value]) => (
        <span key={field}>
          <code>{field}</code> <span className="muted">{JSON.stringify(value)}</span>{" "}
        </span>
      ))}
    </div>
  );
}

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
  const [estimating, setEstimating] = useState<string | null>(null);
  const [estimateError, setEstimateError] = useState<string | null>(null);
  const [estimateSuccess, setEstimateSuccess] = useState<string | null>(null);
  const [events, setEvents] = useState<ItemEvent[] | null>(null);
  const [sources, setSources] = useState<SourceStatus[]>([]);
  const [numistaSales, setNumistaSales] = useState(false);
  const [estNote, setEstNote] = useState("");
  const [historySource, setHistorySource] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [photoError, setPhotoError] = useState<string | null>(null);
  const [photoNote, setPhotoNote] = useState<string | null>(null);
  const [photoSource, setPhotoSource] = useState("");
  const [dragging, setDragging] = useState(false);
  const [lightbox, setLightbox] = useState<number | null>(null);
  const [editing, setEditing] = useState<Photo | null>(null);
  const [webcam, setWebcam] = useState(false);

  // Which automatic sources this build offers, and whether they're switched on.
  useEffect(() => {
    api
      .getSettings()
      .then((s) => {
        setSources(s.sources);
        setNumistaSales(s.numista_sales_enabled);
      })
      .catch(() => setSources([]));
  }, []);

  const loadHistory = () => {
    if (!id) return;
    api.itemHistory(id).then(setEvents).catch(() => setEvents([]));
  };

  const reload = useCallback(() => {
    if (!id) return;
    api.getItem(id).then(setItem).catch((e: Error) => setError(e.message));
  }, [id]);

  useEffect(reload, [reload]);

  // One path for picked, dropped, and pasted files.
  const uploadFiles = useCallback(
    async (files: File[], how: string) => {
      if (!id) return;
      const images = files.filter((f) => f.type.startsWith("image/"));
      if (images.length === 0) {
        setPhotoError("Only image files can be added as photos.");
        return;
      }
      setUploading(true);
      setPhotoError(null);
      setPhotoNote(null);
      let added = 0;
      try {
        for (const file of images) {
          await api.uploadPhoto(id, file, uploadAngle);
          added++;
        }
        setPhotoNote(`${how} ${added} photo${added > 1 ? "s" : ""}.`);
      } catch (err) {
        setPhotoError((err as Error).message);
      } finally {
        setUploading(false);
        reload(); // earlier files in the batch may have landed
      }
    },
    [id, uploadAngle, reload],
  );

  // Paste an image anywhere on the item page to add it.
  useEffect(() => {
    const onPaste = (e: ClipboardEvent) => {
      const files = Array.from(e.clipboardData?.files ?? []);
      if (!files.some((f) => f.type.startsWith("image/"))) return;
      e.preventDefault();
      uploadFiles(files, "Pasted");
    };
    window.addEventListener("paste", onPaste);
    return () => window.removeEventListener("paste", onPaste);
  }, [uploadFiles]);

  // default the manual-estimate currency to the item's own currency
  const itemCurrency = item?.currency;
  useEffect(() => {
    if (itemCurrency) setEstCurrency(itemCurrency);
  }, [itemCurrency]);

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

  function upload(e: FormEvent<HTMLInputElement>) {
    const files = Array.from(e.currentTarget.files ?? []);
    e.currentTarget.value = "";
    if (files.length) uploadFiles(files, "Added");
  }

  async function importFromUrl() {
    const url = photoSource.trim();
    if (!id || !url) return;
    setUploading(true);
    setPhotoError(null);
    setPhotoNote(null);
    try {
      await api.importPhoto(id, url, uploadAngle);
      setPhotoSource("");
      setPhotoNote("Imported the photo from the URL.");
      reload();
    } catch (err) {
      setPhotoError((err as Error).message);
    } finally {
      setUploading(false);
    }
  }

  // Errors propagate to the editor, which shows them and stays open.
  async function saveEdit(image: Blob, filename: string, asCopy: boolean) {
    if (!id || !editing) return;
    if (asCopy) {
      await api.uploadPhoto(id, new File([image], filename, { type: image.type }), editing.angle ?? "");
    } else {
      await api.replacePhotoImage(editing.id, image, filename);
    }
    setEditing(null);
    setPhotoNote(asCopy ? "Saved the edit as a new photo." : "Replaced the photo with the edit.");
    reload();
  }

  async function captureWebcam(image: Blob) {
    if (!id) return;
    const file = new File([image], `webcam-${Date.now()}.jpg`, { type: "image/jpeg" });
    await api.uploadPhoto(id, file, uploadAngle);
    reload();
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
        note: estNote.trim() || null,
      });
      setEstValue("");
      setEstNote("");
      reload();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function autoEstimate(source: string) {
    if (!id) return;
    setEstimating(source);
    setEstimateError(null);
    setEstimateSuccess(null);
    try {
      await api.autoEstimate(id, source);
      setEstimateSuccess(`${SOURCE_LABELS[source] ?? source} updated.`);
      reload();
    } catch (err) {
      setEstimateError((err as Error).message);
    } finally {
      setEstimating(null);
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
      navigate("/collection");
    } catch (err) {
      setError((err as Error).message);
    }
  }

  const bySource = new Map<string, (typeof item.estimates)[number]>();
  for (const est of item.estimates) {
    const key = sourceKey(est.source);
    if (!bySource.has(key)) bySource.set(key, est);
  }
  const sourceValues = [...bySource.entries()];
  const activeSource = historySource && bySource.has(historySource) ? historySource : null;
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
  const certUrl = certLookupUrl(item.cert_service, item.cert_number);

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
          <div>
            <dt>Set / lot</dt>
            <dd>
              {item.set ? <Link to={`/collection?set_id=${item.set.id}`}>{item.set.name}</Link> : "—"}
            </dd>
          </div>
          {fact("Grade", item.grade ? `${item.grade_label} (${item.grade.label})` : null)}
          {item.strike !== "business" &&
            fact("Strike", item.strike === "proof" ? "Proof" : "Specimen")}
          {item.cac_sticker &&
            fact("CAC", item.cac_sticker === "gold" ? "Gold sticker" : "Green sticker")}
          <div>
            <dt>Certification</dt>
            <dd>
              {item.cert_service ? `${item.cert_service} ${item.cert_number ?? ""}`.trim() : "—"}
              {certUrl && (
                <>
                  {" "}
                  <a href={certUrl} target="_blank" rel="noreferrer"
                    title="Check this certification with the grading service">
                    verify ↗
                  </a>
                </>
              )}
            </dd>
          </div>
          {fact("Composition", item.composition)}
          {item.type === "coin" &&
            fact("Weight", item.weight_g != null ? `${item.weight_g} g` : null)}
          {item.type === "coin" && fact("Fineness", item.fineness)}
          {item.diameter_mm != null && fact("Diameter", `${item.diameter_mm} mm`)}
          {item.thickness_mm != null && fact("Thickness", `${item.thickness_mm} mm`)}
          {item.edge && fact("Edge", item.edge)}
          {item.shape && fact("Shape", item.shape)}
          {item.mintage != null &&
            fact(item.type === "note" ? "Print run" : "Mintage", item.mintage.toLocaleString())}
          {item.serial_number && fact("Serial number", item.serial_number)}
          {item.prefix_block && fact("Prefix / block", item.prefix_block)}
          {item.signatures && fact("Signatures", item.signatures)}
          {item.issuer && fact("Issuer", item.issuer)}
          {item.replacement_note && fact("Replacement note", "Yes")}
          {fact("Quantity", item.quantity)}
          {fact("Acquired", item.acquisition_date)}
          {fact("Paid", money(item.acquisition_price, item.currency))}
          {item.acquisition_fees != null &&
            fact("Fees, shipping & tax", money(item.acquisition_fees, item.currency))}
          {item.acquisition_fees != null &&
            fact("Cost basis", money(item.cost_basis, item.currency))}
          {fact("From", item.acquired_from)}
          {fact("Storage", item.storage_location)}
          {item.status === "sold" && fact("Sold on", item.sold_date)}
          {item.status === "sold" && fact("Sold for", money(item.sold_price, item.currency))}
          {item.status === "sold" && item.sold_fees != null &&
            fact("Selling fees", money(item.sold_fees, item.currency))}
          {item.status === "sold" && item.sold_fees != null &&
            fact("Net proceeds", money(item.sale_proceeds, item.currency))}
          {item.status === "sold" && item.sold_to && fact("Sold to / venue", item.sold_to)}
          <div style={{ gridColumn: "1 / -1" }}>
            <dt>Latest value</dt>
            <dd>
              {sourceValues.length === 0 && "—"}
              {sourceValues.length === 1 && (
                <>
                  {money(sourceValues[0][1].estimated_value, sourceValues[0][1].currency)}{" "}
                  <span className="muted">({timeSince(sourceValues[0][1].fetched_at)})</span>
                </>
              )}
              {sourceValues.length > 1 && (
                <div className="chip-row">
                  {sourceValues.map(([key, est]) => (
                    <span key={key} className="chip">
                      {key}: {money(est.estimated_value, est.currency)}{" "}
                      <span className="muted">({timeSince(est.fetched_at)})</span>
                    </span>
                  ))}
                </div>
              )}
            </dd>
          </div>
          {Object.entries(item.custom_fields ?? {}).map(([key, value]) => (
            <div key={key}><dt>{key}</dt><dd>{value}</dd></div>
          ))}
        </dl>
        {(item.tags.length > 0 || item.catalog_refs.length > 0) && (
          <p style={{ marginBottom: 0 }}>
            {item.tags.map((t) => (
              <Link key={t} className="chip" to={`/collection?tag=${encodeURIComponent(t)}`}>{t}</Link>
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

      <div
        className={`card photo-drop${dragging ? " dragging" : ""}`}
        onDragOver={(e) => {
          if (e.dataTransfer.types.includes("Files")) {
            e.preventDefault();
            setDragging(true);
          }
        }}
        onDragLeave={(e) => {
          if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setDragging(false);
        }}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          uploadFiles(Array.from(e.dataTransfer.files), "Dropped");
        }}
      >
        <h2>Photos</h2>
        {photoError && <p className="error">{photoError}</p>}
        {photoNote && <p className="muted">{photoNote}</p>}
        {item.photos.length === 0 && (
          <p className="muted">No photos yet — drop images here, paste one, or add them below.</p>
        )}
        <div className="photo-grid">
          {item.photos.map((photo, index) => (
            <div key={photo.id} className={`photo-card${photo.is_primary ? " primary" : ""}`}>
              <button type="button" className="photo-open" title="View larger"
                onClick={() => setLightbox(index)}>
                <img src={photoUrl(photo.thumb_key ?? photo.file_key)}
                  alt={photo.angle ?? "photo"} />
              </button>
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
                <button
                  title="Delete photo"
                  onClick={() => {
                    if (window.confirm("Delete this photo?")) {
                      act(() => api.deletePhoto(photo.id))();
                    }
                  }}
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
                <button title="Crop, turn, or straighten" onClick={() => setEditing(photo)}>
                  ✎ Edit
                </button>
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
            {uploading ? "Uploading…" : "Add photos"}
            <input type="file" accept="image/jpeg,image/png,image/webp" multiple
              disabled={uploading} onChange={upload} />
          </label>
          <label className="field">
            📷 Camera
            {/* capture opens the camera directly on phones; a normal picker elsewhere */}
            <input type="file" accept="image/jpeg,image/png,image/webp"
              capture="environment" disabled={uploading} onChange={upload} />
          </label>
          <button type="button" disabled={uploading} onClick={() => setWebcam(true)}
            title="Take photos with a webcam">
            🎥 Webcam
          </button>
          <label className="field">
            Import from URL
            <input type="url" value={photoSource} placeholder="https://…"
              onChange={(e) => setPhotoSource(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") importFromUrl();
              }} />
          </label>
          <button type="button" disabled={uploading || !photoSource.trim()} onClick={importFromUrl}>
            Import
          </button>
        </div>
        <p className="muted" style={{ marginBottom: 0 }}>
          You can also drop image files onto this card, or paste an image anywhere on the page.
          New photos get the angle chosen above.
        </p>
        {lightbox !== null && item.photos[lightbox] && (
          <Lightbox photos={item.photos} index={lightbox} onIndex={setLightbox}
            onClose={() => setLightbox(null)} />
        )}
        {editing && (
          <PhotoEditor photo={editing} onCancel={() => setEditing(null)} onSave={saveEdit} />
        )}
        {webcam && <WebcamCapture onCancel={() => setWebcam(false)} onCapture={captureWebcam} />}
      </div>

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

      <SalesLog
        item={item}
        compsEnabled={sources.some((s) => s.key === "comps" && s.enabled)}
        numistaSales={numistaSales}
        onChanged={reload}
      />

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
