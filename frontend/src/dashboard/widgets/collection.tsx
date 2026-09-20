import { Link } from "react-router-dom";

import { api, money, photoUrl, PRIORITY_LABELS } from "../../api";
import { TraitBadges, useSerialTraits } from "../../components/serial-traits";
import { optionNumber, optionText } from "../options";
import { useWidgetData, useWidgetEmpty, WidgetProps } from "../WidgetFrame";

/** The newest items, however they arrived. */
export function RecentAdditionsWidget({ options }: WidgetProps) {
  const count = optionNumber(options, "count", 6);
  const query = `sort=-created_at&limit=${count}`;
  const { data, pending } = useWidgetData(`items:${query}`, () =>
    api.listItems(new URLSearchParams(query)),
  );
  useWidgetEmpty(data !== null && data.items.length === 0);
  if (!data) return pending;
  if (data.items.length === 0) return null;

  return (
    <ul className="dash-list">
      {data.items.map((item) => (
        <li key={item.id}>
          {item.primary_thumb_key ? (
            <img className="thumb" src={photoUrl(item.primary_thumb_key)} alt="" />
          ) : (
            <div className="thumb placeholder">◎</div>
          )}
          <span className="dash-list-main">
            <Link to={`/items/${item.id}`}>{`${item.country} ${item.denomination}, ${item.year_label}`}</Link>
            {item.grade_label && <span className="muted"> · {item.grade_label}</span>}
          </span>
          <span className="num">
            {item.latest_value != null
              ? money(item.latest_value, item.latest_value_currency ?? item.currency)
              : "–"}
          </span>
        </li>
      ))}
    </ul>
  );
}

/** Wanted pieces, by priority or by which have reached their target. */
export function WishlistWidget({ options }: WidgetProps) {
  const count = optionNumber(options, "count", 6);
  const reached = optionText(options, "mode", "priority") === "reached";
  const query = `status=wishlist&sort=priority&limit=${count}${reached ? "&target_reached=true" : ""}`;
  const { data, pending } = useWidgetData(`items:${query}`, () =>
    api.listItems(new URLSearchParams(query)),
  );
  useWidgetEmpty(data !== null && data.items.length === 0);
  if (!data) return pending;
  if (data.items.length === 0) return null;

  return (
    <table className="estimates">
      <thead>
        <tr>
          <th>Item</th>
          <th>Priority</th>
          <th className="num">Target</th>
          <th className="num">Gap</th>
        </tr>
      </thead>
      <tbody>
        {data.items.map((item) => (
          <tr key={item.id}>
            <td>
              <Link to={`/items/${item.id}`}>{`${item.country} ${item.denomination}, ${item.year_label}`}</Link>
              {item.target_reached && <span className="badge reached">target reached</span>}
            </td>
            <td>{item.priority ? PRIORITY_LABELS[item.priority] : <span className="muted">–</span>}</td>
            <td className="num">
              {item.target_price != null ? money(item.target_price, item.currency) : "–"}
            </td>
            {/* The gap is the newest estimate less the target, and only where
                that estimate is in the item's own currency. */}
            <td className="num">
              {item.target_gap != null ? (
                <span className={item.target_gap <= 0 ? "gain" : "loss"}>
                  {item.target_gap > 0 ? "+" : ""}
                  {money(item.target_gap, item.currency)}
                </span>
              ) : (
                "–"
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** Notes whose serial number is worth a second look. */
export function FancySerialsWidget({ options }: WidgetProps) {
  const count = optionNumber(options, "count", 6);
  const query = `fancy=true&sort=-created_at&limit=${count}`;
  const { data, pending } = useWidgetData(`items:${query}`, () =>
    api.listItems(new URLSearchParams(query)),
  );
  const traits = useSerialTraits();
  useWidgetEmpty(data !== null && data.items.length === 0);
  if (!data) return pending;
  if (data.items.length === 0) return null;

  return (
    <ul className="dash-list">
      {data.items.map((item) => (
        <li key={item.id}>
          <span className="dash-list-main">
            <Link to={`/items/${item.id}`}>{item.serial_number ?? `${item.country} ${item.denomination}`}</Link>
            <span className="muted"> · {`${item.denomination}, ${item.year_label}`}</span>
          </span>
          <span>
            <TraitBadges traits={item.serial_traits} reference={traits} max={3} />
          </span>
        </li>
      ))}
    </ul>
  );
}

/** Owned notes grouped by series and signature pair. */
export function NotesBySignatureWidget() {
  const { data, pending } = useWidgetData("notes-by-signature", () => api.notesBySignature());
  useWidgetEmpty(data !== null && data.groups.length === 0);
  if (!data) return pending;
  if (data.groups.length === 0) return null;

  return (
    <div className="table-scroll">
      <table className="estimates">
        <thead>
          <tr>
            <th>Series</th>
            <th>Signatures</th>
            <th className="num">Notes</th>
            <th>Items</th>
          </tr>
        </thead>
        <tbody>
          {data.groups.map((g) => (
            <tr key={`${g.series ?? ""}|${g.signatures ?? ""}`}>
              <td>{g.series ?? <span className="muted">–</span>}</td>
              <td>{g.signatures ?? <span className="muted">–</span>}</td>
              <td
                className="num"
                title={g.quantity !== g.count ? `${g.quantity} pieces in all` : undefined}
              >
                {g.count}
              </td>
              <td>
                {g.items.map((n, i) => (
                  <span key={n.id}>
                    {i > 0 && " · "}
                    <Link
                      to={`/items/${n.id}`}
                      title={[n.label, n.grade_label].filter(Boolean).join(", ")}
                    >
                      {n.serial_number ?? n.label}
                    </Link>
                  </span>
                ))}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Checklist progress, least complete first. */
export function ChecklistsWidget({ options }: WidgetProps) {
  const count = optionNumber(options, "count", 6);
  const { data, pending } = useWidgetData("checklists", () => api.listChecklists());
  useWidgetEmpty(data !== null && data.length === 0);
  if (!data) return pending;
  if (data.length === 0) return null;

  const lists = [...data]
    .sort((a, b) => a.filled / (a.total || 1) - b.filled / (b.total || 1))
    .slice(0, count);

  return (
    <ul className="dash-list">
      {lists.map((list) => (
        <li key={list.id}>
          <span className="dash-list-main">
            <Link to="/checklists">{list.name}</Link>
          </span>
          <span className="progress">
            <span style={{ width: `${list.total ? (list.filled / list.total) * 100 : 0}%` }} />
          </span>
          <span className="num muted">
            {list.filled} / {list.total}
          </span>
        </li>
      ))}
    </ul>
  );
}
