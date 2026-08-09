export type ItemType = "coin" | "note";
export type Angle = "obverse" | "reverse" | "edge" | "other";

export interface Item {
  id: string;
  type: ItemType;
  country: string;
  denomination: string;
  year: number;
  mint_mark: string | null;
  series: string | null;
  quantity: number;
  acquisition_date: string | null;
  acquisition_price: number | null;
  currency: string;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface ItemListEntry extends Item {
  primary_photo_key: string | null;
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
  country: string;
  denomination: string;
  year: number;
  mint_mark: string | null;
  series: string | null;
  quantity: number;
  acquisition_date: string | null;
  acquisition_price: number | null;
  currency: string;
  notes: string | null;
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

  uploadPhoto: (itemId: string, file: File, angle: Angle | "") => {
    const form = new FormData();
    form.append("file", file);
    if (angle) form.append("angle", angle);
    return req<Photo>(`/api/items/${itemId}/photos`, { method: "POST", body: form });
  },
  updatePhoto: (photoId: string, payload: { angle?: Angle; is_primary?: boolean }) =>
    req<Photo>(`/api/photos/${photoId}`, json("PATCH", payload)),
  deletePhoto: (photoId: string) => req<void>(`/api/photos/${photoId}`, { method: "DELETE" }),

  addEstimate: (itemId: string, payload: { estimated_value: number; currency: string; source: string }) =>
    req<Estimate>(`/api/items/${itemId}/estimates`, json("POST", payload)),
};

export const photoUrl = (key: string) => `/photos/${key}`;

export const money = (value: number | null | undefined, currency: string | null | undefined) =>
  value == null ? "—" : `${value.toLocaleString(undefined, { minimumFractionDigits: 2 })} ${currency ?? ""}`.trim();
