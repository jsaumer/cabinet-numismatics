import { Link } from "react-router-dom";

import { api, METAL_LABELS, money } from "../../api";
import { delta } from "./value";
import { optionOrNull, optionText } from "../options";
import { useWidgetData, useWidgetEmpty, WidgetProps } from "../WidgetFrame";

const oz = (v: number) =>
  v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 3 });

/** The bullion stack: a compact table by metal, or tiles for one metal. */
export function StackWidget({ options }: WidgetProps) {
  const metal = optionText(options, "metal", "all");
  const tag = optionOrNull(options, "tag");
  const { data, pending } = useWidgetData(`stack:${tag ?? ""}`, () =>
    api.getStack({ tag: tag ?? undefined }),
  );
  const rows = data ? (metal === "all" ? data.metals : data.metals.filter((m) => m.metal === metal)) : [];
  useWidgetEmpty(data !== null && rows.length === 0);
  if (!data) return pending;
  if (rows.length === 0) return null;

  if (metal !== "all") {
    const m = rows[0];
    return (
      <div className="tiles">
        <div className="tile">
          <span className="tile-label">Fine ounces</span>
          <span className="tile-value">{oz(m.fine_oz)}</span>
        </div>
        <div className="tile">
          <span className="tile-label">Melt value</span>
          <span className="tile-value">
            {m.melt_value != null ? money(m.melt_value, data.currency) : "–"}
          </span>
        </div>
        <div className="tile">
          <span className="tile-label">Cost per oz</span>
          <span className="tile-value">
            {m.cost_per_oz != null ? money(m.cost_per_oz, data.currency) : "–"}
          </span>
        </div>
        <div className="tile">
          <span className="tile-label">Gain</span>
          <span className="tile-value">{m.gain != null ? delta(m.gain, data.currency) : "–"}</span>
        </div>
      </div>
    );
  }

  return (
    <div className="table-scroll">
      <table className="estimates">
        <thead>
          <tr>
            <th>Metal</th>
            <th className="num">Fine oz</th>
            <th className="num">Melt</th>
            <th className="num">Cost/oz</th>
            <th className="num">Gain</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((m) => (
            <tr key={m.metal}>
              <td>{METAL_LABELS[m.metal]}</td>
              <td className="num">{oz(m.fine_oz)}</td>
              <td className="num">{m.melt_value != null ? money(m.melt_value, data.currency) : "–"}</td>
              <td className="num">
                {m.cost_per_oz != null ? money(m.cost_per_oz, data.currency) : "–"}
              </td>
              <td className="num">{m.gain != null ? delta(m.gain, data.currency) : "–"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {data.skipped > 0 && (
        <p className="muted" style={{ marginBottom: 0 }}>
          {data.skipped} {data.skipped === 1 ? "piece is" : "pieces are"} left out for want of a weight
          or fineness: see <Link to="/stack">the Stack page</Link>.
        </p>
      )}
    </div>
  );
}
