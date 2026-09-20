import { Item } from "../api";

/** Outbound lookups for an item: eBay's sold listings for the same coin or
 * note, PCGS Photograde for judging a grade by eye, CoinFacts when a PCGS
 * number is known, and a web search for a note's Friedberg or Pick number.
 * Links only: no request leaves the browser until
 * one is clicked. */
export function LookupLinks({ item }: { item: Item }) {
  const query = [
    item.year,
    item.mint_mark ? `${item.mint_mark}` : null,
    item.denomination,
    item.series,
    item.grade_label,
  ]
    .filter(Boolean)
    .join(" ");
  const ebay = `https://www.ebay.com/sch/i.html?${new URLSearchParams({
    _nkw: query,
    LH_Sold: "1",
    LH_Complete: "1",
  })}`;
  // A catalogue goes by several names: the Numista fill writes Pick as "P".
  const refFor = (...catalogs: string[]) =>
    item.catalog_refs.find((r) => catalogs.includes(r.catalog.trim().toLowerCase()));
  // "P#109" and "Fr. 1500" both mean the bare number.
  const bare = (code: string) => code.trim().replace(/^[a-z.]+\s*#?\s*/i, "") || code.trim();
  const search = (...words: (string | null)[]) =>
    `https://www.google.com/search?${new URLSearchParams({ q: words.filter(Boolean).join(" ") })}`;
  const pcgsNumber = refFor("pcgs");
  const friedberg = item.type === "note" ? refFor("friedberg", "fr", "fr.", "f") : undefined;
  const pick = item.type === "note" ? refFor("pick", "p") : undefined;
  const links: [string, string, string][] = [[ebay, "eBay sold listings", "What the same piece actually sold for"]];
  if (item.type === "coin") {
    links.push(["https://www.pcgs.com/photograde", "PCGS Photograde", "Reference photos for each grade"]);
  }
  if (pcgsNumber) {
    links.push([
      `https://www.pcgs.com/coinfacts/coin/${encodeURIComponent(pcgsNumber.ref_code.trim())}`,
      "CoinFacts",
      "PCGS's page for this coin",
    ]);
  }
  if (friedberg) {
    links.push([
      search("Friedberg", bare(friedberg.ref_code), item.denomination),
      `Friedberg ${bare(friedberg.ref_code)}`,
      "Search the web for this Friedberg number",
    ]);
  }
  if (pick) {
    links.push([
      search("Pick", bare(pick.ref_code), item.country, "banknote"),
      `Pick ${bare(pick.ref_code)}`,
      "Search the web for this Pick number",
    ]);
  }
  return (
    <p className="muted lookup-links" style={{ marginBottom: 0 }}>
      Look it up:{" "}
      {links.map(([href, label, title], i) => (
        <span key={href}>
          {i > 0 && " · "}
          <a href={href} target="_blank" rel="noreferrer" title={title}>
            {label} ↗
          </a>
        </span>
      ))}
    </p>
  );
}
