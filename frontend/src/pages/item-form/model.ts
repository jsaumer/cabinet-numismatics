// The item form's state, its lookups, and the conversion to and from the API.

import { CacSticker, CatalogRef, ItemDetail, ItemPayload, ItemStatus, ItemType, Priority, Strike } from "../../api";

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
  edge: "",
  shape: "",
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
};

export const PROBLEMS: Record<ItemType, string[]> = {
  coin: [
    "Cleaned", "Damaged", "Environmental damage", "Scratched", "Holed", "Repaired",
    "Tooled", "Altered surfaces", "Bent",
  ],
  note: ["Restoration", "Tears", "Annotations", "Stains", "Trimmed", "Pinholes"],
};

export const EDGES = ["Reeded", "Plain", "Lettered", "Security", "Interrupted reeding"];
export const SHAPES = ["Round", "Square", "Polygonal", "Scalloped", "Holed"];

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
  const allowed = new Set(DESIGNATIONS[form.type].map(([code]) => code));
  const designations = form.designations.filter((d) => allowed.has(d));
  const sold = form.status === "sold";
  const struck = coin && form.struck_calendar !== "" && form.struck_year !== "";
  return {
    type: form.type,
    status: form.status,
    country: form.country.trim(),
    denomination: form.denomination.trim(),
    // With a date as struck and no year, the server converts it.
    year: form.year === "" ? null : Number(form.year),
    year_nd: form.year_nd,
    struck_calendar: struck ? form.struck_calendar : null,
    struck_year: struck ? Number(form.struck_year) : null,
    struck_era: struck && form.struck_calendar === "japanese" ? opt(form.struck_era) : null,
    die_axis: coin ? optNum(form.die_axis) : null,
    mint_mark: opt(form.mint_mark),
    series: opt(form.series),
    variety: opt(form.variety),
    strike: form.strike,
    set_id: form.set_id === "" ? null : Number(form.set_id),
    custom_fields: Object.keys(custom).length ? custom : null,
    composition: opt(form.composition),
    weight_g: optNum(form.weight_g),
    fineness: optNum(form.fineness),
    diameter_mm: coin ? optNum(form.diameter_mm) : null,
    thickness_mm: coin ? optNum(form.thickness_mm) : null,
    edge: coin ? opt(form.edge) : null,
    shape: coin ? opt(form.shape) : null,
    mintage: optNum(form.mintage),
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
    serial_number: note ? opt(form.serial_number) : null,
    prefix_block: note ? opt(form.prefix_block) : null,
    signatures: note ? opt(form.signatures) : null,
    issuer: note ? opt(form.issuer) : null,
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
    edge: str(item.edge),
    shape: str(item.shape),
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
