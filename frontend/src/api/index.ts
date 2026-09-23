// The API client and its types. Import from "../api" as before.

export * from "./types/items";
export * from "./types/imports";
export * from "./types/stats";
export * from "./types/settings";
export * from "./types/dashboard";
export * from "./types/stack";
export * from "./types/auth";
export { api } from "./calls";
export { ApiError, setReauthHandler, setUnauthorizedHandler } from "./client";
export type { ReqOptions } from "./client";

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

const moneyFormats = new Map<string, Intl.NumberFormat | null>();

/** An amount with its currency's symbol ($12.50, CA$12.50, €12.50). A code
 * the browser doesn't know as a currency falls back to "12.50 XYZ". */
export const money = (value: number | null | undefined, currency: string | null | undefined) => {
  if (value == null) return "–";
  const code = (currency ?? "").trim().toUpperCase();
  if (!moneyFormats.has(code)) {
    let format: Intl.NumberFormat | null = null;
    try {
      if (code) format = new Intl.NumberFormat(undefined, { style: "currency", currency: code });
    } catch {
      format = null;
    }
    moneyFormats.set(code, format);
  }
  const format = moneyFormats.get(code);
  return format
    ? format.format(value)
    : `${value.toLocaleString(undefined, { minimumFractionDigits: 2 })} ${code}`.trim();
};

// Notes grade on PMG's scale; coins and bullion (NGC slabs some rounds on
// the same numeric scale as a coin) grade on Sheldon's.
export const gradeScaleFor = (type: ItemType) => (type === "note" ? "pmg" : "sheldon");

/** "1922", "ND", or "ND (1922)": the same convention as `Item.year_label`,
 * for a catalogue issue that isn't an item yet (a Numista issue, a run pick). */
export const ndYearLabel = (issue: { nd: boolean; year: number | null }) =>
  issue.nd ? (issue.year != null ? `ND (${issue.year})` : "ND") : String(issue.year);

const BYTE_UNITS = ["B", "KB", "MB", "GB", "TB"];

/** A file size in the largest unit that keeps it above 1 (1.4 GB, 812 KB). */
export function formatBytes(bytes: number): string {
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < BYTE_UNITS.length - 1) {
    value /= 1024;
    unit++;
  }
  return `${value.toFixed(unit === 0 ? 0 : 1)} ${BYTE_UNITS[unit]}`;
}
