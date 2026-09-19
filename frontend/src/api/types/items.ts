// Items, photos, estimates, sales, documents, and the item payload.

export type ItemType = "coin" | "note";
export type ItemStatus = "owned" | "sold" | "wishlist";
export type Angle = "obverse" | "reverse" | "edge" | "other";
export type Strike = "business" | "proof" | "specimen";
export type CacSticker = "green" | "gold";

export interface Grade {
  id: number;
  scale: string;
  code: string;
  label: string;
  rank: number;
}

export interface CatalogRef {
  catalog: string;
  ref_code: string;
}

export interface TagInfo {
  name: string;
  count: number;
}

export interface SetInfo {
  id: number;
  name: string;
  notes: string | null;
  item_count?: number;
}

export interface Item {
  id: string;
  type: ItemType;
  status: ItemStatus;
  country: string;
  denomination: string;
  year: number;
  mint_mark: string | null;
  series: string | null;
  variety: string | null;
  composition: string | null;
  weight_g: number | null;
  fineness: number | null;
  grade: Grade | null;
  grade_label: string | null;
  strike: Strike;
  grade_plus: boolean;
  grade_star: boolean;
  designations: string[] | null;
  grade_details: string | null;
  cac_sticker: CacSticker | null;
  diameter_mm: number | null;
  thickness_mm: number | null;
  edge: string | null;
  shape: string | null;
  mintage: number | null;
  serial_number: string | null;
  prefix_block: string | null;
  signatures: string | null;
  issuer: string | null;
  replacement_note: boolean;
  acquisition_fees: number | null;
  cost_basis: number | null;
  sold_fees: number | null;
  sold_to: string | null;
  sale_proceeds: number | null;
  set: SetInfo | null;
  custom_fields: Record<string, string> | null;
  cert_service: string | null;
  cert_number: string | null;
  quantity: number;
  acquisition_date: string | null;
  acquisition_price: number | null;
  currency: string;
  acquired_from: string | null;
  storage_location: string | null;
  sold_date: string | null;
  sold_price: number | null;
  notes: string | null;
  tags: string[];
  catalog_refs: CatalogRef[];
  created_at: string;
  updated_at: string;
  deleted_at: string | null; // in the trash since
}

export interface ItemListEntry extends Item {
  primary_photo_key: string | null;
  primary_thumb_key: string | null;
  latest_value: number | null;
  latest_value_currency: string | null;
  latest_value_source: string | null;
}

/** An item that looks like one about to be added, and why. */
export interface SimilarItem {
  id: string;
  label: string;
  grade_label: string | null;
  status: ItemStatus;
  in_trash: boolean;
  reason: string;
}

export interface Photo {
  id: string;
  item_id: string;
  file_key: string;
  thumb_key: string | null;
  angle: Angle | null;
  is_primary: boolean;
  position: number;
  width: number | null;
  height: number | null;
  uploaded_at: string;
}

export interface Estimate {
  id: string;
  item_id: string;
  source: string;
  estimated_value: number;
  currency: string;
  confidence: number | null;
  sample_size: number | null;
  details: Record<string, unknown> | null;
  fetched_at: string;
}

/** One sale in an item's sales log — what the comps estimate is built from. */
export interface ComparableInput {
  sold_on: string;
  venue: string;
  title?: string | null;
  lot?: string | null;
  url?: string | null;
  grade?: string | null;
  price: number; // per piece
  currency: string;
  premium_included?: boolean | null; // null = unknown
  fees?: number | null; // buyer's premium or shipping on top of the price
  included?: boolean;
  note?: string | null;
}

export interface Comparable extends ComparableInput {
  id: number;
  item_id: string;
  title: string | null;
  lot: string | null;
  url: string | null;
  grade: string | null;
  grade_bucket: string | null;
  premium_included: boolean | null;
  fees: number | null;
  included: boolean;
  note: string | null;
  source: string; // manual | numista
  created_at: string;
}

export interface SalesFetchResult {
  found: number;
  added: number;
  already_logged: number;
  issue_id: number | null;
}

export type DocumentKind =
  | "receipt"
  | "invoice"
  | "certificate"
  | "grading_label"
  | "appraisal"
  | "correspondence"
  | "other";

export interface ItemDocument {
  id: string;
  kind: DocumentKind;
  title: string;
  doc_date: string | null;
  note: string | null;
  filename: string;
  content_type: string;
  size: number;
  pages: number | null;
  has_thumb: boolean;
  items: { id: string; label: string }[];
  created_at: string;
}

export interface ItemDetail extends Item {
  photos: Photo[];
  estimates: Estimate[];
  comparables: Comparable[];
  documents: ItemDocument[];
}

export interface ItemPage {
  items: ItemListEntry[];
  total: number;
  limit: number;
  offset: number;
}

export interface ItemPayload {
  type: ItemType;
  strike: Strike;
  diameter_mm: number | null;
  thickness_mm: number | null;
  edge: string | null;
  shape: string | null;
  mintage: number | null;
  grade_plus: boolean;
  grade_star: boolean;
  designations: string[] | null;
  grade_details: string | null;
  cac_sticker: CacSticker | null;
  serial_number: string | null;
  prefix_block: string | null;
  signatures: string | null;
  issuer: string | null;
  replacement_note: boolean;
  acquisition_fees: number | null;
  sold_fees: number | null;
  sold_to: string | null;
  status: ItemStatus;
  country: string;
  denomination: string;
  year: number;
  mint_mark: string | null;
  series: string | null;
  variety: string | null;
  composition: string | null;
  weight_g: number | null;
  fineness: number | null;
  grade_id: number | null;
  set_id: number | null;
  custom_fields: Record<string, string> | null;
  cert_service: string | null;
  cert_number: string | null;
  quantity: number;
  acquisition_date: string | null;
  acquisition_price: number | null;
  currency: string;
  acquired_from: string | null;
  storage_location: string | null;
  sold_date: string | null;
  sold_price: number | null;
  notes: string | null;
  tags: string[];
  catalog_refs: CatalogRef[];
}
