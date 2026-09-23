// The item form's state, its lookups, and the conversion to and from the API.

import {
  CacSticker,
  CatalogRef,
  ItemDetail,
  ItemPayload,
  ItemStatus,
  ItemType,
  Metal,
  Priority,
  Strike,
  TROY_OUNCE_G,
} from "../../api";

export const EMPTY = {
  type: "coin" as ItemType,
  status: "owned" as ItemStatus,
  country: "",
  denomination: "",
  year: "",
  year_nd: false, // the piece carries no date; year, if given, is attributed
  struck_calendar: "", // blank = Gregorian, the Year field alone
  struck_year: "",
  struck_era: "",
  die_axis: "",
  mint_mark: "",
  series: "",
  variety: "",
  strike: "business" as Strike,
  set_id: "",
  composition: "",
  weight_g: "",
  fineness: "",
  diameter_mm: "",
  thickness_mm: "",
  width_mm: "",
  height_mm: "",
  edge: "",
  shape: "",
  printer: "",
  watermark: "",
  demonetized_on: "",
  mintage: "",
  grade_id: "",
  grade_plus: false,
  grade_star: false,
  designations: [] as string[],
  grade_details: "",
  cac_sticker: "",
  cert_service: "",
  cert_number: "",
  pcgs_population: "",
  pcgs_pop_higher: "",
  serial_number: "",
  prefix_block: "",
  signatures: "",
  issuer: "",
  replacement_note: false,
  charter_number: "",
  bank_city: "",
  bank_state: "",
  plate_position: "",
  target_price: "",
  priority: "",
  quantity: "1",
  acquisition_date: "",
  acquisition_price: "",
  acquisition_fees: "",
  spot_at_purchase: "",
  currency: "USD",
  acquired_from: "",
  storage_location: "",
  sold_date: "",
  sold_price: "",
  sold_fees: "",
  sold_to: "",
  notes: "",
  tags: "",
};

export type FormState = typeof EMPTY;
export type TextField = {
  [K in keyof FormState]: FormState[K] extends string ? K : never;
}[keyof FormState];
export type FlagField = "grade_plus" | "grade_star" | "replacement_note" | "year_nd";
export type CustomField = { key: string; value: string };

// Designations as grading services print them, with what each means.
export const DESIGNATIONS: Record<ItemType, [string, string][]> = {
  coin: [
    ["PL", "Prooflike"],
    ["DMPL", "Deep mirror prooflike"],
    ["CAM", "Cameo"],
    ["DCAM", "Deep cameo"],
    ["UCAM", "Ultra cameo (NGC)"],
    ["RD", "Red (copper)"],
    ["RB", "Red-brown (copper)"],
    ["BN", "Brown (copper)"],
    ["FB", "Full bands (Mercury dime)"],
    ["FBL", "Full bell lines (Franklin half)"],
    ["FH", "Full head (Standing Liberty quarter)"],
    ["FS", "Full steps (Jefferson nickel)"],
    ["FT", "Full torch (Roosevelt dime)"],
  ],
  note: [["EPQ", "Exceptional paper quality (PMG)"]],
  bullion: [], // no designations: the form hides the whole block for bullion
};

export const PROBLEMS: Record<ItemType, string[]> = {
  coin: [
    "Cleaned", "Damaged", "Environmental damage", "Scratched", "Holed", "Repaired",
    "Tooled", "Altered surfaces", "Bent",
  ],
  note: ["Restoration", "Tears", "Annotations", "Stains", "Trimmed", "Pinholes"],
  bullion: ["Scratched", "Corroded", "Tarnished", "Damaged"],
};

export const EDGES = ["Reeded", "Plain", "Lettered", "Security", "Interrupted reeding"];
export const SHAPES = ["Round", "Square", "Polygonal", "Scalloped", "Holed"];

// Historic spot only covers purchases from this date; mirrors the backend's
// stack.HISTORY_START.
export const HISTORY_START = "2024-03-02";

// Mirrors the backend's pricing.detect_metal (the authority; keep the two in
// step): whole words only, the named alloys nickel silver, German silver,
// and Nordic gold are not precious, a metal followed by plated or washed is
// a coating and gilt is a gold surface on the metal before it (clad is not
// stripped), and with two metals left the one with the larger attached
// percentage wins, else the first named.
const ALLOYS_NOT_PRECIOUS = ["nickel silver", "german silver", "nordic gold"];
const SURFACE_RE =
  /\b(?:gold|silver|platinum|palladium)[\s-]*(?:plated|plate|plating|washed|wash)\b|\b(?:gilt|gilded)\b/g;
const METAL_RE =
  /(?:(\d{1,3}(?:\.\d+)?)\s*%\s*(?:of\s+)?)?\b(gold|silver|platinum|palladium)\b(?:\s*\(?\s*(\d{1,3}(?:\.\d+)?)\s*%)?/g;

export function detectMetal(composition: string): Metal | null {
  let text = composition.toLowerCase();
  for (const alloy of ALLOYS_NOT_PRECIOUS) text = text.split(alloy).join(" ");
  text = text.replace(SURFACE_RE, " ");
  const found: { metal: Metal; share: number | null }[] = [];
  for (const m of text.matchAll(METAL_RE)) {
    const percent = m[1] ?? m[3];
    const share = percent && Number(percent) > 0 && Number(percent) <= 100 ? Number(percent) : null;
    found.push({ metal: m[2] as Metal, share });
  }
  if (found.length === 0) return null;
  const withShare = found.filter((f) => f.share !== null);
  if (withShare.length > 0) {
    return withShare.reduce((best, f) => (f.share! > best.share! ? f : best)).metal;
  }
  return found[0].metal;
}

/** A new bullion piece defaults to .999 fine (four-nines a click away); an
 * already-filled fineness, from Numista or the owner, is left alone. */
export function presetBullionFineness(f: FormState): FormState {
  return f.fineness === "" ? { ...f, fineness: "0.999" } : f;
}

/** The product name a bullion piece suggests from its weight, metal, and
 * shape: "1 oz silver bar", "10 g gold bar", "1 oz silver round". Ounces are
 * shown for a whole or half number of troy ounces, grams otherwise. */
export function suggestDenomination(weightG: number, metal: Metal, shape: string): string {
  const oz = weightG / TROY_OUNCE_G;
  // Grams are stored to four places (31.1035 for an ounce), so a stored
  // weight is a hair off the exact ounce: allow a couple of thousandths.
  const wholeOrHalfOz = Math.abs(oz * 2 - Math.round(oz * 2)) < 0.004;
  const amount = wholeOrHalfOz ? oz : weightG;
  const rounded = Math.round(amount * 10000) / 10000;
  const kind = shape === "Round" ? "round" : "bar";
  return `${rounded} ${wholeOrHalfOz ? "oz" : "g"} ${metal} ${kind}`;
}

/** Whether a date falls inside the historic-spot lookup's coverage: on or
 * after 2 March 2024, and before today (today uses current spot instead). */
export function inHistoricCoverage(dateStr: string): boolean {
  if (!dateStr) return false;
  const today = new Date().toISOString().slice(0, 10);
  return dateStr >= HISTORY_START && dateStr < today;
}

const opt = (v: string) => v.trim() || null;
const optNum = (v: string) => (v === "" ? null : Number(v));
const str = (v: string | number | null | undefined) => (v == null ? "" : String(v));

export function toPayload(form: FormState, refs: CatalogRef[], fields: CustomField[]): ItemPayload {
  const custom: Record<string, string> = {};
  for (const f of fields) {
    if (f.key.trim()) custom[f.key.trim()] = f.value;
  }
  const coin = form.type === "coin";
  const note = form.type === "note";
  const bullion = form.type === "bullion";
  const allowed = new Set(DESIGNATIONS[form.type].map(([code]) => code));
  const designations = form.designations.filter((d) => allowed.has(d));
  const sold = form.status === "sold";
  const struck = coin && form.struck_calendar !== "" && form.struck_year !== "";
  return {
    type: form.type,
    status: form.status,
    country: form.country.trim(),
    denomination: form.denomination.trim(),
    // With a date as struck and no year, the server converts it. A bar with
    // no year is neither dated nor ND (the year-or-ND rule doesn't apply).
    year: form.year === "" ? null : Number(form.year),
    year_nd: bullion ? false : form.year_nd,
    struck_calendar: struck ? form.struck_calendar : null,
    struck_year: struck ? Number(form.struck_year) : null,
    struck_era: struck && form.struck_calendar === "japanese" ? opt(form.struck_era) : null,
    die_axis: coin ? optNum(form.die_axis) : null,
    mint_mark: bullion ? null : opt(form.mint_mark),
    series: opt(form.series),
    variety: bullion ? null : opt(form.variety),
    strike: form.strike,
    set_id: form.set_id === "" ? null : Number(form.set_id),
    custom_fields: Object.keys(custom).length ? custom : null,
    composition: opt(form.composition),
    weight_g: optNum(form.weight_g),
    fineness: optNum(form.fineness),
    diameter_mm: coin ? optNum(form.diameter_mm) : null,
    thickness_mm: coin || bullion ? optNum(form.thickness_mm) : null,
    // Size, printer, and watermark are edited on a note but kept on anything
    // that already carries them (an import may give a coin its size); a
    // bar's size (not round) uses the same width/height fields.
    width_mm: optNum(form.width_mm),
    height_mm: optNum(form.height_mm),
    edge: coin ? opt(form.edge) : null,
    shape: coin || bullion ? opt(form.shape) : null,
    printer: opt(form.printer),
    watermark: opt(form.watermark),
    demonetized_on: bullion ? null : form.demonetized_on || null,
    mintage: bullion ? null : optNum(form.mintage),
    grade_id: form.grade_id === "" ? null : Number(form.grade_id),
    grade_plus: form.grade_plus,
    grade_star: form.grade_star,
    designations: designations.length ? designations : null,
    grade_details: opt(form.grade_details),
    cac_sticker: coin && form.cac_sticker ? (form.cac_sticker as CacSticker) : null,
    cert_service: opt(form.cert_service),
    cert_number: opt(form.cert_number),
    pcgs_population: coin ? optNum(form.pcgs_population) : null,
    pcgs_pop_higher: coin ? optNum(form.pcgs_pop_higher) : null,
    serial_number: note || bullion ? opt(form.serial_number) : null,
    prefix_block: note ? opt(form.prefix_block) : null,
    signatures: note ? opt(form.signatures) : null,
    issuer: note || bullion ? opt(form.issuer) : null,
    replacement_note: note && form.replacement_note,
    charter_number: note ? opt(form.charter_number) : null,
    bank_city: note ? opt(form.bank_city) : null,
    bank_state: note ? opt(form.bank_state) : null,
    plate_position: note ? opt(form.plate_position) : null,
    // Offered for a wishlist item, kept on any: the API allows them anywhere.
    target_price: optNum(form.target_price),
    priority: form.priority === "" ? null : (Number(form.priority) as Priority),
    quantity: Number(form.quantity),
    acquisition_date: form.acquisition_date || null,
    acquisition_price: optNum(form.acquisition_price),
    acquisition_fees: optNum(form.acquisition_fees),
    spot_at_purchase: optNum(form.spot_at_purchase),
    currency: form.currency.trim().toUpperCase(),
    acquired_from: opt(form.acquired_from),
    storage_location: opt(form.storage_location),
    sold_date: sold ? form.sold_date || null : null,
    sold_price: sold ? optNum(form.sold_price) : null,
    sold_fees: sold ? optNum(form.sold_fees) : null,
    sold_to: sold ? opt(form.sold_to) : null,
    notes: opt(form.notes),
    tags: form.tags.split(",").map((t) => t.trim()).filter(Boolean),
    catalog_refs: refs.filter((r) => r.catalog.trim() && r.ref_code.trim()),
  };
}

/** An existing item as form state, for editing. */
export function fromItem(item: ItemDetail): FormState {
  return {
    type: item.type,
    status: item.status,
    country: item.country,
    denomination: item.denomination,
    year: str(item.year),
    year_nd: item.year_nd,
    struck_calendar: str(item.struck_calendar),
    struck_year: str(item.struck_year),
    struck_era: str(item.struck_era),
    die_axis: str(item.die_axis),
    mint_mark: str(item.mint_mark),
    series: str(item.series),
    variety: str(item.variety),
    strike: item.strike,
    set_id: item.set ? String(item.set.id) : "",
    composition: str(item.composition),
    weight_g: str(item.weight_g),
    fineness: str(item.fineness),
    diameter_mm: str(item.diameter_mm),
    thickness_mm: str(item.thickness_mm),
    width_mm: str(item.width_mm),
    height_mm: str(item.height_mm),
    edge: str(item.edge),
    shape: str(item.shape),
    printer: str(item.printer),
    watermark: str(item.watermark),
    demonetized_on: str(item.demonetized_on),
    mintage: str(item.mintage),
    grade_id: item.grade ? String(item.grade.id) : "",
    grade_plus: item.grade_plus,
    grade_star: item.grade_star,
    designations: item.designations ?? [],
    grade_details: str(item.grade_details),
    cac_sticker: str(item.cac_sticker),
    cert_service: str(item.cert_service),
    cert_number: str(item.cert_number),
    pcgs_population: str(item.pcgs_population),
    pcgs_pop_higher: str(item.pcgs_pop_higher),
    serial_number: str(item.serial_number),
    prefix_block: str(item.prefix_block),
    signatures: str(item.signatures),
    issuer: str(item.issuer),
    replacement_note: item.replacement_note,
    charter_number: str(item.charter_number),
    bank_city: str(item.bank_city),
    bank_state: str(item.bank_state),
    plate_position: str(item.plate_position),
    target_price: str(item.target_price),
    priority: str(item.priority),
    quantity: String(item.quantity),
    acquisition_date: str(item.acquisition_date),
    acquisition_price: str(item.acquisition_price),
    acquisition_fees: str(item.acquisition_fees),
    spot_at_purchase: str(item.spot_at_purchase),
    currency: item.currency,
    acquired_from: str(item.acquired_from),
    storage_location: str(item.storage_location),
    sold_date: str(item.sold_date),
    sold_price: str(item.sold_price),
    sold_fees: str(item.sold_fees),
    sold_to: str(item.sold_to),
    notes: str(item.notes),
    tags: item.tags.join(", "),
  };
}
