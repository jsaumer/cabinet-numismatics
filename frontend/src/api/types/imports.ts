// Numista catalogue lookups and imports from other tools.

import type { CatalogRef, ItemStatus, ItemType } from "./items";

export interface NumistaSearchResult {
  type_id: number;
  title: string;
  category: string | null;
  issuer: string | null;
  min_year: number | null;
  max_year: number | null;
  thumbnail: string | null;
}

export interface NumistaIssue {
  year: number | null;
  mint_letter: string | null;
  mintage: number | null;
  comment: string | null;
  owned: boolean; // an owned item carries this type, year, and mint mark
}

export interface NumistaType {
  type_id: number;
  title: string;
  url: string | null;
  category: string | null;
  fields: Record<string, string | number | null>;
  catalog_refs: CatalogRef[];
  issues: NumistaIssue[];
}

export interface PcgsGrade {
  rank: number; // Sheldon number
  strike: "business" | "proof" | "specimen";
  plus: boolean;
  designations: string[];
}

export interface PcgsCert {
  cert: string;
  pcgs_number: string | null;
  name: string | null;
  fields: Record<string, string | number>; // item fields, keyed like the payload
  grade: PcgsGrade | null;
  catalog_refs: CatalogRef[];
  population: number | null;
  pop_higher: number | null;
  price_guide_value: number | null;
  coinfacts_url: string | null;
}

export interface ImportResult {
  created: number;
  skipped: number;
  errors: { row: number; error: string }[];
}

export type ImportFormat = "spreadsheet" | "cabinet" | "numista_file" | "opennumismat";

export interface ImportUpload {
  upload_id: string;
  filename: string;
  size: number;
  format: ImportFormat;
}

export interface ImportDefaults {
  type: ItemType;
  status: ItemStatus;
  currency: string;
  country: string | null;
}

export interface ImportOptions {
  format?: ImportFormat | null;
  mapping?: Record<string, string> | null;
  skip_rows?: number | null;
  defaults?: ImportDefaults;
}

export interface NumistaImportOptions {
  catalogue_details: boolean;
  fetch_photos: boolean;
}

export interface ImportPreviewRow {
  row: number;
  status: "new" | "duplicate" | "error";
  label: string;
  grade: string | null;
  status_value: string | null;
  type: string | null;
  quantity: number | null;
  price: number | null;
  currency: string | null;
  photos: number;
  messages: string[];
  error: string | null;
}

export interface ImportPreview {
  format: string;
  filename: string | null;
  total: number;
  new: number;
  duplicates: number;
  errors: number;
  warnings: number;
  photos: number;
  rows: ImportPreviewRow[];
  headers: string[] | null;
  header_row: number | null;
  mapping: Record<string, string> | null;
  fields: { key: string; label: string }[] | null;
  types: number | null;
  types_to_fetch: number | null;
  fetched_at: string | null;
}

export interface ImportRunResult {
  created: number;
  skipped: number;
  errors: { row: number; error: string }[];
  photos_added: number;
  photos_failed: number;
}
