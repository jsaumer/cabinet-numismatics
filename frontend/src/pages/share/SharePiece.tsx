import { ReactNode, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api, money, ShareItem, ShareItemPhoto, sharePhotoUrl } from "../../api";
import { BullionIcon, CoinIcon, NoteIcon } from "../../components/icons";
import { shareItemLabel } from "./ShareGrid";

/** Keeps the page behind the lightbox from scrolling while it's open, the
 * same as components/photos.tsx's Lightbox (unexported there, so repeated
 * here rather than reworking that file for one caller). */
function useNoScroll() {
  useEffect(() => {
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previous;
    };
  }, []);
}

/** A read-only viewer for a shared piece's photos: the same look as the
 * item page's lightbox (arrows, Esc, a caption), without the zoom-and-pan
 * or editing a signed-in visitor never needs here. */
function ShareLightbox({
  token,
  photos,
  index,
  onIndex,
  onClose,
}: {
  token: string;
  photos: ShareItemPhoto[];
  index: number;
  onIndex: (index: number) => void;
  onClose: () => void;
}) {
  useNoScroll();
  const count = photos.length;
  const photo = photos[index];

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      else if (e.key === "ArrowRight" && count > 1) onIndex((index + 1) % count);
      else if (e.key === "ArrowLeft" && count > 1) onIndex((index - 1 + count) % count);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [index, count, onIndex, onClose]);

  return (
    <div className="lightbox" role="dialog" aria-modal="true" aria-label="Photo viewer" onClick={onClose}>
      <div className="lightbox-stage" onClick={(e) => e.stopPropagation()}>
        <img src={sharePhotoUrl(token, photo.id, "full")} alt={photo.angle ?? "photo"} draggable={false} />
      </div>
      <div className="lightbox-bar" onClick={(e) => e.stopPropagation()}>
        {count > 1 && (
          <button onClick={() => onIndex((index - 1 + count) % count)} title="Previous (←)">
            ←
          </button>
        )}
        <span>
          {index + 1} / {count}
          {photo.angle ? ` · ${photo.angle}` : ""}
        </span>
        {count > 1 && (
          <button onClick={() => onIndex((index + 1) % count)} title="Next (→)">
            →
          </button>
        )}
        <button onClick={onClose} title="Close (Esc)">
          ✕
        </button>
      </div>
    </div>
  );
}

interface Fact {
  label: string;
  value: ReactNode;
}

interface Group {
  title: string;
  facts: Fact[];
}

const filled = (value: ReactNode) => value !== null && value !== undefined && value !== "";

function typeIcon(item: ShareItem) {
  return item.type === "coin" ? <CoinIcon /> : item.type === "bullion" ? <BullionIcon /> : <NoteIcon />;
}

/** One shared piece: its photos (in the lightbox), the title and grade the
 * hero shows on the item page, and everything else in the same grouped-facts
 * style, built only from what the allowlist actually sent (a field absent
 * from `item` was left out by the link's own toggles, not by this page). */
export default function SharePiece({ token, shareName }: { token: string; shareName: string }) {
  const { itemId } = useParams<{ itemId: string }>();
  const [item, setItem] = useState<ShareItem | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lightbox, setLightbox] = useState<number | null>(null);

  useEffect(() => {
    setItem(null);
    setError(null);
    setLightbox(null);
    if (!itemId) return;
    api
      .shareItem(token, itemId)
      .then(setItem)
      .catch(() => setError("This piece isn't in this share."));
  }, [token, itemId]);

  const backLink = (
    <Link className="share-back" to={`/s/${token}`}>
      ← Back to {shareName}
    </Link>
  );

  if (error) {
    return (
      <div>
        {backLink}
        <p className="empty">{error}</p>
      </div>
    );
  }
  if (!item) return <p className="muted">Loading…</p>;

  const size =
    item.width_mm != null && item.height_mm != null
      ? `${item.width_mm} × ${item.height_mm} mm`
      : item.width_mm != null
        ? `${item.width_mm} mm wide`
        : item.height_mm != null
          ? `${item.height_mm} mm tall`
          : null;

  const groups: Group[] = [
    {
      title: "Identity",
      facts: [
        { label: "Series", value: item.series },
        { label: "Variety", value: item.variety },
        { label: "Mint mark", value: item.mint_mark },
        { label: "Issuer", value: item.issuer },
        { label: "Quantity", value: item.quantity !== 1 ? item.quantity : null },
      ],
    },
    {
      // item.grade_label is only present at all when the link shows grades
      // (see the allowlist in services/share.py); absent means "not shown,"
      // not "ungraded," so those facts are left out rather than shown empty.
      // item.cert_number is its own toggle (show_certs) and can be present
      // or absent independently of the grade fields, so it's checked on its
      // own rather than folded into the grade_label check above it.
      title: "Grade & certification",
      facts: [
        ...(item.grade_label === undefined
          ? []
          : [
              { label: "Grade", value: item.grade_label },
              { label: "Details grade", value: item.grade_details },
              { label: "Designations", value: (item.designations ?? []).join(", ") },
              {
                label: "CAC",
                value:
                  item.cac_sticker === "gold" ? "Gold sticker" : item.cac_sticker === "green" ? "Green sticker" : null,
              },
              { label: "Certification service", value: item.cert_service },
            ]),
        ...(item.cert_number === undefined ? [] : [{ label: "Cert number", value: item.cert_number }]),
      ],
    },
    {
      title: "Physical",
      facts: [
        { label: "Composition", value: item.composition },
        { label: "Weight", value: item.weight_g != null ? `${item.weight_g} g` : null },
        { label: "Fineness", value: item.fineness },
        { label: "Diameter", value: item.diameter_mm != null ? `${item.diameter_mm} mm` : null },
        { label: "Size", value: size },
        { label: "Shape", value: item.shape },
      ],
    },
    {
      title: "Tags",
      facts: item.tags === undefined ? [] : [{ label: "Tags", value: item.tags.join(", ") }],
    },
    {
      title: "Notes",
      facts: item.notes === undefined ? [] : [{ label: "Notes", value: item.notes }],
    },
  ];

  const blocks = groups
    .map((g) => ({ title: g.title, facts: g.facts.filter((f) => filled(f.value)) }))
    .filter((g) => g.facts.length > 0);

  return (
    <div>
      {backLink}
      <div className="card share-piece">
        <div className="share-photos">
          {item.photos && item.photos.length > 0 ? (
            item.photos.map((photo, i) => (
              <button key={photo.id} type="button" className="photo-open" onClick={() => setLightbox(i)}>
                <img src={sharePhotoUrl(token, photo.id, "thumb")} alt={photo.angle ?? "photo"} />
              </button>
            ))
          ) : (
            <div className="share-thumb-empty large">{typeIcon(item)}</div>
          )}
        </div>
        <div className="detail-header">
          <h1>{shareItemLabel(item)}</h1>
          <span className={`badge ${item.type}`}>{item.type}</span>
        </div>
        {item.grade_label && (
          <p className="hero-grade">
            <b>{item.grade_label}</b>
          </p>
        )}
        {item.value && (
          <p className="hero-money">
            <span className="hero-amount">{money(item.value.amount, item.value.currency)}</span>
          </p>
        )}
      </div>
      {blocks.length > 0 && (
        <div className="card item-facts">
          {blocks.map((group) => (
            <section className="fact-group" key={group.title}>
              <h3>{group.title}</h3>
              <dl className="facts">
                {group.facts.map((fact) => (
                  <div key={fact.label}>
                    <dt>{fact.label}</dt>
                    <dd>{fact.value}</dd>
                  </div>
                ))}
              </dl>
            </section>
          ))}
        </div>
      )}
      {lightbox !== null && item.photos?.[lightbox] && (
        <ShareLightbox
          token={token}
          photos={item.photos}
          index={lightbox}
          onIndex={setLightbox}
          onClose={() => setLightbox(null)}
        />
      )}
    </div>
  );
}
