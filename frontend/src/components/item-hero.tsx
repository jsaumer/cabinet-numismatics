import { ReactNode, useState } from "react";
import { Link } from "react-router-dom";

import { certLookupUrl, ItemDetail, money, photoUrl, PRIORITY_LABELS } from "../api";
import { CoinIcon, NoteIcon } from "./icons";
import { Lightbox } from "./photos";
import { latestBySource, timeSince } from "./provenance";

/** The top of the item page: the piece itself, large, and the handful of facts
 * worth reading before anything else. The photos card below still manages
 * photos; this only shows the primary one and opens the lightbox. */
export function ItemHero({ item, actions }: { item: ItemDetail; actions: ReactNode }) {
  const [lightbox, setLightbox] = useState<number | null>(null);

  const primary = Math.max(
    0,
    item.photos.findIndex((p) => p.is_primary),
  );
  const photo = item.photos[primary];
  const sourceValues = latestBySource(item.estimates);
  const latest = item.estimates[0] ?? null;
  const cost = item.cost_basis;
  // Only comparable in one currency: nothing is converted here.
  const gain =
    latest != null && cost != null && latest.currency === item.currency
      ? latest.estimated_value - cost
      : null;
  const certUrl = certLookupUrl(item.cert_service, item.cert_number);
  const cert = item.cert_service
    ? `${item.cert_service} ${item.cert_number ?? ""}`.trim()
    : null;

  // dt/dd pairs rather than prose: these are short and read as a list.
  const extras: { label: string; value: ReactNode; note?: ReactNode }[] = [];
  if (item.quantity !== 1) extras.push({ label: "Quantity", value: item.quantity });
  if (item.status === "sold") {
    if (item.sold_date) extras.push({ label: "Sold on", value: item.sold_date });
    if (item.sold_price != null) {
      extras.push({ label: "Sold for", value: money(item.sold_price, item.currency) });
    }
  }
  if (item.target_price != null) {
    extras.push({
      label: "Target",
      value: money(item.target_price, item.currency),
      note:
        item.target_gap == null ? undefined : (
          <span className={item.target_gap <= 0 ? "gain fact-note" : "muted fact-note"}>
            {item.target_gap === 0
              ? "at target"
              : `${money(Math.abs(item.target_gap), item.currency)} ${
                  item.target_gap < 0 ? "under" : "over"
                } target`}
          </span>
        ),
    });
  }
  if (item.priority != null) {
    extras.push({ label: "Priority", value: PRIORITY_LABELS[item.priority] });
  }

  return (
    <div className="card item-hero">
      <div className="hero-photo">
        {photo ? (
          <button type="button" className="hero-photo-open" title="View larger"
            onClick={() => setLightbox(primary)}>
            <img src={photoUrl(photo.thumb_key ?? photo.file_key)} alt={photo.angle ?? "photo"} />
          </button>
        ) : (
          <div className="hero-photo-empty" title="No photo yet">
            {item.type === "coin" ? <CoinIcon /> : <NoteIcon />}
          </div>
        )}
      </div>
      <div className="hero-main">
        <div className="detail-header">
          <h1>
            {item.country} {item.denomination}, {item.year_label}
            {item.mint_mark ? ` "${item.mint_mark}"` : ""}
          </h1>
          <span className={`badge ${item.type}`}>{item.type}</span>
          {item.status !== "owned" && (
            <span className={`badge status-${item.status}`}>{item.status}</span>
          )}
          {item.deleted_at && <span className="badge status-sold">in trash</span>}
          <div className="spacer" />
          {actions}
        </div>

        {(item.grade_label || cert) && (
          <p className="hero-grade">
            {item.grade_label && <b>{item.grade_label}</b>}
            {item.grade_label && item.grade && (
              <span className="muted"> ({item.grade.label})</span>
            )}
            {item.grade_label && cert && <span className="muted"> · </span>}
            {cert}
            {certUrl && (
              <>
                {" "}
                <a href={certUrl} target="_blank" rel="noreferrer"
                  title="Check this certification with the grading service">
                  verify ↗
                </a>
              </>
            )}
          </p>
        )}

        {latest && (
          <div className="hero-money">
            <span className="hero-amount">
              {money(latest.estimated_value, latest.currency)}
            </span>
            <span className="muted">{timeSince(latest.fetched_at)}</span>
            {cost != null && (
              <span className="muted">cost basis {money(cost, item.currency)}</span>
            )}
            {gain != null && (
              <span className={gain >= 0 ? "gain" : "loss"}>
                {gain >= 0 ? "+" : ""}
                {money(gain, item.currency)}
              </span>
            )}
          </div>
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

        {extras.length > 0 && (
          <dl className="facts hero-facts">
            {extras.map((e) => (
              <div key={e.label}>
                <dt>{e.label}</dt>
                <dd>
                  {e.value}
                  {e.note}
                </dd>
              </div>
            ))}
          </dl>
        )}

        {(item.tags.length > 0 || item.catalog_refs.length > 0) && (
          <p className="hero-chips">
            {item.tags.map((t) => (
              <Link key={t} className="chip" to={`/collection?tag=${encodeURIComponent(t)}`}>
                {t}
              </Link>
            ))}
            {item.catalog_refs.map((r) => (
              <span key={`${r.catalog}:${r.ref_code}`} className="chip ref">
                {r.catalog}: {r.ref_code}
              </span>
            ))}
          </p>
        )}
      </div>
      {lightbox !== null && item.photos[lightbox] && (
        <Lightbox photos={item.photos} index={lightbox} onIndex={setLightbox}
          onClose={() => setLightbox(null)} />
      )}
    </div>
  );
}
