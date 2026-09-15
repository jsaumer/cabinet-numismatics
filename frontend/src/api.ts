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
}

export interface ItemListEntry extends Item {
  primary_photo_key: string | null;
  primary_thumb_key: string | null;
  latest_value: number | null;
  latest_value_currency: string | null;
  latest_value_source: string | null;
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

export interface ItemDetail extends Item {
  photos: Photo[];
  estimates: Estimate[];
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

export interface ImportResult {
  created: number;
  skipped: number;
  errors: { row: number; error: string }[];
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

export interface SourceStatus {
  key: string;
  name: string;
  enabled: boolean;
  configured: boolean;
  available: boolean;
  secret_hint: string | null;
  note: string | null;
}

export interface CachedValue {
  label: string;
  value: string;
  source: string;
  fetched_at: string;
}

export type ValueStrategy = "latest" | "preferred_source" | "average";

export interface AppSettings {
  display_currency: string;
  reestimate_days: number;
  reestimate_days_overridden: boolean;
  value_strategy: ValueStrategy;
  preferred_source: string | null;
  numista_refresh_days: number | null;
  pcgs_auto_refresh: boolean;
  numista_priceable_items: number;
  pcgs_priceable_items: number;
  backup_schedule: BackupSchedule | null;
  backup_keep: number;
  backup_include_photos: boolean;
  sources: SourceStatus[];
  cached: CachedValue[];
}

export interface AppSettingsUpdate {
  display_currency?: string;
  reestimate_days?: number;
  melt_enabled?: boolean;
  numista_enabled?: boolean;
  numista_api_key?: string;
  pcgs_enabled?: boolean;
  pcgs_api_token?: string;
  value_strategy?: ValueStrategy;
  preferred_source?: string | null;
  numista_refresh_days?: number | null;
  pcgs_auto_refresh?: boolean;
  backup_schedule?: BackupSchedule | null;
  backup_keep?: number;
  backup_include_photos?: boolean;
}

export type BackupSchedule = "daily" | "weekly";

export type CoverageStatus = "priced" | "not_applicable" | "failed" | "not_tried" | "disabled";

export interface SourceCoverage {
  source: string;
  status: CoverageStatus;
  reason: string | null;
  estimated_at: string | null;
  attempted_at: string | null;
}

export interface PricingCoverage {
  owned_items: number;
  estimated_items: number;
  manual_only_items: number;
  sources: {
    source: string;
    enabled: boolean;
    priced: number;
    not_applicable: number;
    failed: number;
    not_tried: number;
  }[];
  items: { item_id: string; label: string; has_estimate: boolean; sources: SourceCoverage[] }[];
}

export interface StaleReport {
  days: number;
  checked: number;
  stale: {
    item_id: string;
    label: string;
    source: string;
    source_label: string;
    estimated_value: number;
    currency: string;
    fetched_at: string;
    age_days: number;
    upstream_stale: boolean;
    in_totals: boolean;
  }[];
}

export interface SourcesReport {
  currency: string;
  strategy: string;
  preferred_source: string | null;
  sources: {
    source: string;
    items: number;
    total_value: number;
    avg_confidence: number | null;
    median_age_days: number | null;
    in_totals: number;
  }[];
  averaged_items: number;
  disagreements: {
    item_id: string;
    label: string;
    values: Record<string, number>;
    spread_pct: number;
  }[];
  excluded_other_currency: number;
}

export interface AccuracyEstimate {
  source: string;
  value: number;
  error_pct: number;
  estimated_at: string | null;
}

export interface AccuracyReport {
  currency: string;
  sold_items: number;
  compared_items: number;
  summary: {
    source: string;
    sales: number;
    median_abs_error_pct: number;
    mean_error_pct: number;
    within_20_pct: number;
  }[];
  items: {
    item_id: string;
    label: string;
    sold_date: string | null;
    sold_price: number;
    blended: AccuracyEstimate | null;
    by_source: AccuracyEstimate[];
  }[];
  excluded_other_currency: number;
}

export interface BackupRun {
  at: string;
  ok: boolean;
  file?: string;
  size?: number;
  includes_photos?: boolean;
  pruned?: string[];
  error?: string;
}

export interface BackupList {
  directory: string;
  free_bytes: number | null;
  last_run: BackupRun | null;
  backups: { name: string; size: number; created_at: string }[];
}

export interface Health {
  status: string;
  db: string;
  version: string;
  schema: {
    current: string | null;
    expected: string | null;
    status: "ok" | "pending" | "ahead" | "unknown";
  };
}

async function req<T>(url: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(url, init);
  if (!resp.ok) {
    let detail: string | undefined;
    try {
      const body = await resp.json();
      if (typeof body.detail === "string") {
        detail = body.detail;
      } else if (Array.isArray(body.detail)) {
        // FastAPI validation errors: [{loc: ["body", "field", ...], msg}, …]
        detail = body.detail
          .map((e: { loc?: (string | number)[]; msg?: string }) => {
            const field = (e.loc ?? []).filter((p) => p !== "body").join(".");
            return field ? `${field}: ${e.msg}` : e.msg;
          })
          .join("; ");
      }
    } catch {
      /* non-JSON error body */
    }
    throw new Error(detail || `HTTP ${resp.status}`);
  }
  if (resp.status === 204) return undefined as T;
  return resp.json() as Promise<T>;
}

const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const api = {
  listItems: (params: URLSearchParams) => req<ItemPage>(`/api/items?${params}`),
  getItem: (id: string) => req<ItemDetail>(`/api/items/${id}`),
  createItem: (payload: ItemPayload) => req<Item>("/api/items", json("POST", payload)),
  updateItem: (id: string, payload: Partial<ItemPayload>) =>
    req<Item>(`/api/items/${id}`, json("PATCH", payload)),
  deleteItem: (id: string) => req<void>(`/api/items/${id}`, { method: "DELETE" }),
  cloneItem: (id: string) => req<Item>(`/api/items/${id}/clone`, { method: "POST" }),

  importCsv: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return req<ImportResult>("/api/items/import", { method: "POST", body: form });
  },

  listGrades: (scale?: string) =>
    req<Grade[]>(`/api/grades${scale ? `?scale=${scale}` : ""}`),
  listTags: () => req<TagInfo[]>("/api/tags"),
  listSets: () => req<SetInfo[]>("/api/sets"),
  createSet: (name: string) => req<SetInfo>("/api/sets", json("POST", { name })),

  bulkUpdate: (payload: {
    ids: string[];
    set?: Partial<ItemPayload>;
    add_tags?: string[];
    remove_tags?: string[];
  }) => req<{ updated: number }>("/api/items/bulk", json("POST", payload)),

  uploadPhoto: (itemId: string, file: File, angle: Angle | "") => {
    const form = new FormData();
    form.append("file", file);
    if (angle) form.append("angle", angle);
    return req<Photo>(`/api/items/${itemId}/photos`, { method: "POST", body: form });
  },
  updatePhoto: (photoId: string, payload: { angle?: Angle; is_primary?: boolean }) =>
    req<Photo>(`/api/photos/${photoId}`, json("PATCH", payload)),
  deletePhoto: (photoId: string) => req<void>(`/api/photos/${photoId}`, { method: "DELETE" }),
  reorderPhotos: (itemId: string, order: string[]) =>
    req<Photo[]>(`/api/items/${itemId}/photos/order`, json("POST", { order })),

  addEstimate: (
    itemId: string,
    payload: {
      estimated_value: number;
      currency: string;
      source: string;
      confidence: number | null;
      note: string | null;
    },
  ) => req<Estimate>(`/api/items/${itemId}/estimates`, json("POST", payload)),
  autoEstimate: (itemId: string, source = "melt") =>
    req<Estimate>(`/api/items/${itemId}/estimate?source=${source}`, { method: "POST" }),

  collectionStats: () => req<CollectionStats>("/api/stats/collection"),
  breakdowns: () => req<Breakdowns>("/api/stats/breakdowns"),
  gains: () => req<Gains>("/api/stats/gains"),
  valueHistory: (months = 24) => req<ValueHistory>(`/api/stats/value-history?months=${months}`),
  refreshMelt: () => req<RefreshResult>("/api/estimates/refresh-melt", { method: "POST" }),

  itemHistory: (id: string) => req<ItemEvent[]>(`/api/items/${id}/history`),

  listChecklists: () => req<ChecklistSummary[]>("/api/checklists"),
  createChecklist: (name: string, slots: string[]) =>
    req<ChecklistDetail>("/api/checklists", json("POST", { name, slots })),
  getChecklist: (id: number) => req<ChecklistDetail>(`/api/checklists/${id}`),
  updateSlot: (checklistId: number, slotId: number, filled: boolean) =>
    req<ChecklistSlot>(
      `/api/checklists/${checklistId}/slots/${slotId}`,
      json("PATCH", { filled }),
    ),
  deleteChecklist: (id: number) => req<void>(`/api/checklists/${id}`, { method: "DELETE" }),

  health: () => req<Health>("/api/health"),
  getSettings: () => req<AppSettings>("/api/settings"),
  updateSettings: (payload: AppSettingsUpdate) =>
    req<AppSettings>("/api/settings", json("PUT", payload)),
  listBackups: () => req<BackupList>("/api/backups"),
  runBackup: () => req<BackupRun>("/api/backups", { method: "POST" }),

  pricingCoverage: () => req<PricingCoverage>("/api/pricing/coverage"),
  pricingStale: (days: number) => req<StaleReport>(`/api/pricing/stale?days=${days}`),
  pricingSources: () => req<SourcesReport>("/api/pricing/sources"),
  pricingAccuracy: () => req<AccuracyReport>("/api/pricing/accuracy"),

  async allItems(): Promise<ItemListEntry[]> {
    const items: ItemListEntry[] = [];
    let offset = 0;
    for (;;) {
      const page = await api.listItems(
        new URLSearchParams({ limit: "500", offset: String(offset), sort: "country" }),
      );
      items.push(...page.items);
      offset += page.items.length;
      if (offset >= page.total || page.items.length === 0) return items;
    }
  },
};

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
