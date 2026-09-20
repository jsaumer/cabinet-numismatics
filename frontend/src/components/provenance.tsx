import { Estimate, money } from "../api";

export const SOURCE_LABELS: Record<string, string> = {
  melt: "Melt value",
  numista: "Numista value",
  pcgs: "PCGS value",
  comps: "Comps value",
};

export function timeSince(iso: string): string {
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

/** "numista:N#123 XF" → "numista"; a manual source is returned as is. */
export function sourceKey(source: string): string {
  const i = source.indexOf(":");
  return i === -1 ? source : source.slice(0, i);
}

/** Each source's most recent estimate, in the order they first appear
 * (the estimates arrive newest first). */
export function latestBySource(estimates: Estimate[]): [string, Estimate][] {
  const bySource = new Map<string, Estimate>();
  for (const est of estimates) {
    const key = sourceKey(est.source);
    if (!bySource.has(key)) bySource.set(key, est);
  }
  return [...bySource.entries()];
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

// What the source returned that produced an estimate, or the note left on a
// manual one. Unknown shapes fall back to a plain field list.
export function Provenance({ estimate }: { estimate: Estimate }) {
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
            <span className="muted"> (no {wanted.toUpperCase()} price, nearest bucket used)</span>
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
    const older = Array.isArray(d.older_lots) ? (d.older_lots as Details[]) : [];
    const guide = num(d.price_guide_value);
    const coinfacts = text(d.coinfacts_url);
    const lotLine = (lot: Details, index: number) => {
      const url = text(lot.url);
      return (
        <li key={index}>
          {text(lot.date) ?? "undated"}: {money(num(lot.price), "USD")}
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
    };
    return (
      <div className="provenance">
        <div>
          {d.lookup === "cert"
            ? `Cert ${String(d.cert)}`
            : `PCGS #${String(d.pcgs_number)} ${String(d.grade ?? "")}`}
          {" · "}
          {d.basis === "apr"
            ? `median of ${lots.length} recent auction sale${lots.length === 1 ? "" : "s"}`
            : d.basis === "apr_old"
              ? `median of ${lots.length} old auction sale${lots.length === 1 ? "" : "s"} ` +
                "(nothing recent, and no price guide value)"
              : "price guide (no auction sales in the last five years)"}
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
        {lots.length > 0 && <ul className="provenance-lots">{lots.map(lotLine)}</ul>}
        {older.length > 0 && (
          <>
            <div className="muted">
              Not counted (more than five years old, or undated):
            </div>
            <ul className="provenance-lots">{older.map(lotLine)}</ul>
          </>
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
                {text(sale.date)}: {money(num(sale.converted), currency)}
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
