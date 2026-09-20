import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api, CatalogRef, SimilarItem } from "../api";

/** Warns, as the form is filled in, when the collection already holds
 * something with the same cert, reference, or country/denomination/year/mint. */
export function DuplicateWarning({
  country,
  denomination,
  year,
  mintMark,
  certNumber,
  refs,
  excludeId,
}: {
  country: string;
  denomination: string;
  year: string;
  mintMark: string;
  certNumber: string;
  refs: CatalogRef[];
  excludeId?: string;
}) {
  const [found, setFound] = useState<SimilarItem[]>([]);
  const refKey = refs
    .filter((r) => r.catalog.trim() && r.ref_code.trim())
    .map((r) => `${r.catalog.trim()}:${r.ref_code.trim()}`)
    .join("\n");

  useEffect(() => {
    const identity = country.trim() && denomination.trim() && /^-?\d+$/.test(year.trim());
    if (!identity && !certNumber.trim() && !refKey) {
      setFound([]);
      return;
    }
    const params = new URLSearchParams();
    if (identity) {
      params.set("country", country.trim());
      params.set("denomination", denomination.trim());
      params.set("year", year.trim());
      params.set("mint_mark", mintMark.trim());
    }
    if (certNumber.trim()) params.set("cert_number", certNumber.trim());
    for (const ref of refKey.split("\n").filter(Boolean)) params.append("ref", ref);
    if (excludeId) params.set("exclude", excludeId);
    let cancelled = false;
    const timer = window.setTimeout(() => {
      api
        .similarItems(params)
        .then((items) => {
          if (!cancelled) setFound(items);
        })
        .catch(() => {
          if (!cancelled) setFound([]);
        });
    }, 400);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [country, denomination, year, mintMark, certNumber, refKey, excludeId]);

  if (found.length === 0) return null;
  return (
    <div className="dup-warning">
      <b>Already in the collection?</b>
      <ul>
        {found.map((item) => (
          <li key={item.id}>
            <Link to={`/items/${item.id}`}>{item.label}</Link>
            {item.grade_label && ` · ${item.grade_label}`}
            {item.status !== "owned" && ` · ${item.status}`}
            {item.in_trash && " · in the trash"}
            <span className="muted"> ({item.reason})</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
