import { Link } from "react-router-dom";

import { api, money, photoUrl, ShowcasePiece } from "../../api";
import { optionNumber } from "../options";
import { useWidgetData, useWidgetEmpty, WidgetProps } from "../WidgetFrame";

/** One piece shown for its own sake: its photo, its name, its value. */
function Piece({ piece, note }: { piece: ShowcasePiece; note?: string }) {
  const key = piece.thumb_key ?? piece.photo_key;
  return (
    <div className="showcase">
      {key ? (
        <img className="showcase-photo" src={photoUrl(key)} alt="" loading="lazy" />
      ) : (
        <div className="showcase-photo placeholder" />
      )}
      <div className="showcase-body">
        <Link to={`/items/${piece.id}`}>{piece.label}</Link>
        <span className="muted">
          {/* The label already ends with the year. */}
          {[piece.value != null ? money(piece.value, piece.currency) : null, note]
            .filter(Boolean)
            .join(" · ")}
        </span>
      </div>
    </div>
  );
}

const year = (iso: string | null) => (iso ? new Date(iso).getFullYear() : null);

/** A different piece each day, the same one all day. */
export function PieceOfTheDayWidget() {
  const { data, pending } = useWidgetData("showcase", () => api.showcase());
  useWidgetEmpty(data !== null && data.piece_of_the_day === null);
  if (!data) return pending;
  if (!data.piece_of_the_day) return null;
  return <Piece piece={data.piece_of_the_day} />;
}

/** The earliest piece by the year on it. */
export function OldestPieceWidget() {
  const { data, pending } = useWidgetData("showcase", () => api.showcase());
  useWidgetEmpty(data !== null && data.oldest === null);
  if (!data) return pending;
  if (!data.oldest) return null;
  return <Piece piece={data.oldest} />;
}

/** The piece that arrived most recently. */
export function NewestAcquisitionWidget() {
  const { data, pending } = useWidgetData("showcase", () => api.showcase());
  useWidgetEmpty(data !== null && data.newest === null);
  if (!data) return pending;
  if (!data.newest) return null;
  const acquired = data.newest.acquisition_date;
  return (
    <Piece
      piece={data.newest}
      note={acquired ? `acquired ${new Date(acquired).toLocaleDateString()}` : undefined}
    />
  );
}

/** Pieces acquired on today's date in an earlier year. */
export function OnThisDayWidget() {
  const { data, pending } = useWidgetData("showcase", () => api.showcase());
  useWidgetEmpty(data !== null && data.on_this_day.length === 0);
  if (!data) return pending;
  if (data.on_this_day.length === 0) return null;
  return (
    <div className="showcase-list">
      {data.on_this_day.map((piece) => {
        const acquired = year(piece.acquisition_date);
        return (
          <Piece
            key={piece.id}
            piece={piece}
            note={acquired ? `acquired in ${acquired}` : undefined}
          />
        );
      })}
    </div>
  );
}

/** The most valuable owned pieces, by their shown value. */
export function MostValuableWidget({ options }: WidgetProps) {
  const count = optionNumber(options, "count", 5);
  const query = `status=owned&sort=-value&limit=${count}`;
  const { data, pending } = useWidgetData(`items:${query}`, () =>
    api.listItems(new URLSearchParams(query)),
  );
  const rows = (data?.items ?? []).filter((i) => i.latest_value != null);
  useWidgetEmpty(data !== null && rows.length === 0);
  if (!data) return pending;
  if (rows.length === 0) return null;

  return (
    <ul className="dash-list">
      {rows.map((item) => (
        <li key={item.id}>
          {item.primary_thumb_key ? (
            <img className="thumb" src={photoUrl(item.primary_thumb_key)} alt="" />
          ) : (
            <div className="thumb placeholder">◎</div>
          )}
          <span className="dash-list-main">
            <Link to={`/items/${item.id}`}>
              {`${item.country} ${item.denomination}, ${item.year_label}`}
            </Link>
            {item.grade_label && <span className="muted"> · {item.grade_label}</span>}
          </span>
          <span className="num">
            {money(item.latest_value, item.latest_value_currency ?? item.currency)}
          </span>
        </li>
      ))}
    </ul>
  );
}

/** Nothing but photographs: the newest pieces that have one. */
export function PhotoMosaicWidget({ options }: WidgetProps) {
  const count = optionNumber(options, "count", 12);
  const query = `sort=-created_at&limit=${count}`;
  const { data, pending } = useWidgetData(`items:${query}`, () =>
    api.listItems(new URLSearchParams(query)),
  );
  const shown = (data?.items ?? []).filter((i) => i.primary_thumb_key);
  useWidgetEmpty(data !== null && shown.length === 0);
  if (!data) return pending;
  if (shown.length === 0) return null;

  return (
    <div className="photo-mosaic">
      {shown.map((item) => (
        <Link
          key={item.id}
          to={`/items/${item.id}`}
          title={`${item.country} ${item.denomination}, ${item.year_label}`}
        >
          <img src={photoUrl(item.primary_thumb_key!)} alt="" loading="lazy" />
        </Link>
      ))}
    </div>
  );
}
