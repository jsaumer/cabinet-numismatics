// The API client and its types. Import from "../api" as before.

export * from "./types/items";
export * from "./types/imports";
export * from "./types/stats";
export * from "./types/settings";
export { api } from "./calls";

import type { ItemType } from "./types/items";

/** Where to check a slab's certification. PCGS opens the certificate itself;
 * NGC and PMG open their lookup page, which also asks for the grade. */
export function certLookupUrl(service: string | null, cert: string | null): string | null {
  if (!service || !cert?.trim()) return null;
  switch (service.trim().toUpperCase()) {
    case "PCGS":
      return `https://www.pcgs.com/cert/${encodeURIComponent(cert.trim())}`;
    case "NGC":
      return "https://www.ngccoin.com/certlookup/";
    case "PMG":
      return "https://www.pmgnotes.com/certlookup/";
    default:
      return null;
  }
}

export const photoUrl = (key: string) => `/photos/${key}`;

export const money = (value: number | null | undefined, currency: string | null | undefined) =>
  value == null
    ? "—"
    : `${value.toLocaleString(undefined, { minimumFractionDigits: 2 })} ${currency ?? ""}`.trim();

export const gradeScaleFor = (type: ItemType) => (type === "coin" ? "sheldon" : "pmg");
