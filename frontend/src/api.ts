export type ItemType = "coin" | "note";
export type ItemStatus = "owned" | "sold" | "wishlist";
export type Angle = "obverse" | "reverse" | "edge" | "other";

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

async function req<T>(url: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(url, init);
  if (!resp.ok) {
    let detail: string | undefined;
    try {
      const body = await resp.json();
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      /* non-JSON error body */
    }
    throw new Error(detail ?? `HTTP ${resp.status}`);
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
    payload: { estimated_value: number; currency: string; source: string; confidence: number | null },
  ) => req<Estimate>(`/api/items/${itemId}/estimates`, json("POST", payload)),
  autoEstimate: (itemId: string) =>
    req<Estimate>(`/api/items/${itemId}/estimate`, { method: "POST" }),

  collectionStats: () => req<CollectionStats>("/api/stats/collection"),
  breakdowns: () => req<Breakdowns>("/api/stats/breakdowns"),
  gains: () => req<Gains>("/api/stats/gains"),
  valueHistory: (months = 24) => req<ValueHistory>(`/api/stats/value-history?months=${months}`),
  refreshMelt: () => req<RefreshResult>("/api/estimates/refresh-melt", { method: "POST" }),

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

export const photoUrl = (key: string) => `/photos/${key}`;

export const money = (value: number | null | undefined, currency: string | null | undefined) =>
  value == null
    ? "—"
    : `${value.toLocaleString(undefined, { minimumFractionDigits: 2 })} ${currency ?? ""}`.trim();

export const gradeScaleFor = (type: ItemType) => (type === "coin" ? "sheldon" : "pmg");
