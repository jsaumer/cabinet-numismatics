// The trash, dashboard stats, edit history, and checklists.

import type { ItemStatus, ItemType } from "./items";

export interface TrashEntry {
  id: string;
  label: string;
  type: ItemType;
  status: ItemStatus;
  grade_label: string | null;
  series: string | null;
  thumb_key: string | null;
  deleted_at: string;
  purge_at: string | null;
}

export interface TrashList {
  retention_days: number;
  items: TrashEntry[];
}

export interface BreakdownEntry {
  key: string;
  count: number;
  cost_basis: number;
  estimated_value: number;
}

export interface Breakdowns {
  currency: string;
  by_country: BreakdownEntry[];
  by_type: BreakdownEntry[];
  by_decade: BreakdownEntry[];
  by_grade: BreakdownEntry[];
  by_tag: BreakdownEntry[];
  acquisitions_by_year: BreakdownEntry[];
}

export interface GainEntry {
  item_id: string;
  label: string;
  cost_basis: number;
  value: number;
  gain: number;
}

export interface Gains {
  currency: string;
  unrealized: GainEntry[];
  realized: GainEntry[];
}

export interface CollectionStats {
  currency: string;
  counts: Record<string, number>;
  cost_basis: number;
  estimated_value: number;
  unrealized_gain: number;
  realized_gain: number;
  estimated_items: number;
  converted_other_currency: number;
  excluded_other_currency: number;
}

export interface ValuePoint {
  date: string;
  value: number;
  estimated_items: number;
}

export interface ValueHistory {
  currency: string;
  points: ValuePoint[];
}

export interface RefreshResult {
  updated: number;
  skipped: number;
  failed: number;
}

export interface ItemEvent {
  id: number;
  at: string;
  action: string;
  changes: Record<string, [unknown, unknown]> | null;
}

export interface ChecklistSummary {
  id: number;
  name: string;
  total: number;
  filled: number;
  generated: boolean; // slots fill themselves from owned items
}

export interface ChecklistSlot {
  id: number;
  label: string;
  position: number;
  filled: boolean; // ticked by hand, or matched by an owned item
  item_id: string | null;
  year: number | null;
  mint_mark: string | null;
  matched_item_id: string | null;
  matched_label: string | null;
}

export interface ChecklistDetail {
  id: number;
  name: string;
  match_catalog: string | null;
  match_ref: string | null;
  match_country: string | null;
  match_denomination: string | null;
  total: number;
  filled: number;
  slots: ChecklistSlot[];
}

export type ChecklistGenerate =
  | { source: "numista"; type_id: number; name?: string }
  | {
      source: "range";
      country: string;
      denomination: string;
      year_from: number;
      year_to: number;
      mint_marks: string[];
      skip: string[];
      name?: string;
    };

export interface RunCreate {
  type_id: number;
  issues: { year: number | null; mint_mark: string | null; mintage: number | null }[];
  shared: {
    status: ItemStatus;
    grade_id: number | null;
    acquisition_date: string | null;
    acquisition_price: number | null;
    currency: string;
    acquired_from: string | null;
    storage_location: string | null;
    set_id: number | null;
    tags: string[];
  };
  skip_owned?: boolean;
}

export interface RunResult {
  created: number;
  skipped: number;
  item_ids: string[];
}

/** Owned notes grouped by series and signature pair. */
export interface NotesBySignature {
  groups: {
    series: string | null;
    signatures: string | null;
    count: number;
    quantity: number;
    items: { id: string; label: string; serial_number: string | null; grade_label: string | null }[];
  }[];
  total: number;
}
