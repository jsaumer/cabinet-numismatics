// The bullion stack: fine ounces, melt value, cost, and premium by metal,
// plus the historic-spot lookup used to fill an item's purchase-day spot.

export type Metal = "gold" | "silver" | "platinum" | "palladium";

// Grams per troy ounce, for converting a stored fine_oz back to grams for
// display; mirrors the backend's pricing.TROY_OUNCE_G.
export const TROY_OUNCE_G = 31.1034768;

export const METAL_LABELS: Record<Metal, string> = {
  gold: "Gold",
  silver: "Silver",
  platinum: "Platinum",
  palladium: "Palladium",
};

export type SpotAtPurchaseSource = "manual" | "auto";

export interface StackMetalRow {
  metal: Metal;
  items: number;
  pieces: number;
  fine_oz: number;
  fine_g: number;
  spot_per_oz: number | null;
  spot_fetched_at: string | null;
  spot_stale: boolean;
  melt_value: number | null;
  cost_basis: number | null;
  costed_oz: number;
  cost_per_oz: number | null;
  gain: number | null;
  gain_pct: number | null;
  premium_paid_pct: number | null;
  premium_known_oz: number;
}

export interface StackItemRow {
  item_id: string;
  label: string;
  metal: Metal;
  quantity: number;
  fine_oz: number;
  cost_basis: number | null;
  cost_per_oz: number | null;
  spot_at_purchase: number | null;
  spot_at_purchase_source: SpotAtPurchaseSource | null;
  premium_paid_pct: number | null;
  melt_value: number | null;
  gain: number | null;
  currency: string;
  converted: boolean;
}

export interface StackTotals {
  melt_value: number;
  cost_basis: number;
  gain: number;
  fine_oz_by_metal: Record<string, number>;
}

// A precious-metal piece left out of the stack for want of a weight or a
// fineness (P11, v0.31.0).
export interface StackSkippedItem {
  item_id: string;
  label: string;
  missing: "weight" | "fineness" | "weight and fineness";
}

export interface StackReport {
  currency: string;
  metals: StackMetalRow[];
  totals: StackTotals;
  items: StackItemRow[];
  missing_spot: number;
  skipped: number;
  skipped_items: StackSkippedItem[];
  excluded_other_currency: number;
  history_start: string;
}

export interface StackBackfillResult {
  filled: number;
  failed: number;
  remaining: number;
}

export interface HistoricSpot {
  metal: Metal;
  date: string;
  currency: string;
  per_oz: number;
  source: string;
}

export type SpotDirection = "above" | "below";

export interface SpotAlert {
  metal: Metal;
  direction: SpotDirection;
  price: number;
  currency: string;
  met?: boolean | null; // set on read only
}
