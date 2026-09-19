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
}

export interface ChecklistSlot {
  id: number;
  label: string;
  position: number;
  filled: boolean;
  item_id: string | null;
}

export interface ChecklistDetail {
  id: number;
  name: string;
  slots: ChecklistSlot[];
}
