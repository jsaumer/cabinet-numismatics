// Every endpoint the frontend calls, one method each.

import { json, req } from "./client";
import type { Angle, Comparable, ComparableInput, DocumentKind, Estimate, Grade, Item, ItemDetail, ItemDocument, ItemListEntry, ItemPage, ItemPayload, Photo, SalesFetchResult, SetInfo, SimilarItem, TagInfo } from "./types/items";
import type { ImportOptions, ImportPreview, ImportResult, ImportRunResult, ImportUpload, NumistaImportOptions, NumistaSearchResult, NumistaType, PcgsCert } from "./types/imports";
import type { Breakdowns, ChecklistDetail, ChecklistSlot, ChecklistSummary, CollectionStats, Gains, ItemEvent, RefreshResult, TrashList, ValueHistory } from "./types/stats";
import type { AccuracyReport, AppSettings, AppSettingsUpdate, BackupList, BackupRun, Health, MonitorOutcome, PricingCoverage, SourcesReport, StaleReport } from "./types/settings";

export const api = {
  listItems: (params: URLSearchParams) => req<ItemPage>(`/api/items?${params}`),
  getItem: (id: string) => req<ItemDetail>(`/api/items/${id}`),
  createItem: (payload: ItemPayload) => req<Item>("/api/items", json("POST", payload)),
  updateItem: (id: string, payload: Partial<ItemPayload>) =>
    req<Item>(`/api/items/${id}`, json("PATCH", payload)),
  /** Moves the item to the trash; `permanent` deletes it for good. */
  deleteItem: (id: string, permanent = false) =>
    req<void>(`/api/items/${id}${permanent ? "?permanent=true" : ""}`, { method: "DELETE" }),
  restoreItem: (id: string) => req<Item>(`/api/items/${id}/restore`, { method: "POST" }),
  listTrash: () => req<TrashList>("/api/trash"),
  trashItems: (ids: string[]) => req<{ count: number }>("/api/trash/items", json("POST", { ids })),
  restoreItems: (ids: string[]) =>
    req<{ count: number }>("/api/trash/restore", json("POST", { ids })),
  purgeItems: (ids: string[]) => req<{ count: number }>("/api/trash/purge", json("POST", { ids })),
  emptyTrash: () => req<{ count: number }>("/api/trash", { method: "DELETE" }),
  cloneItem: (id: string) => req<Item>(`/api/items/${id}/clone`, { method: "POST" }),

  uploadImport: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return req<ImportUpload>("/api/imports", { method: "POST", body: form });
  },
  previewImport: (uploadId: string, options: ImportOptions) =>
    req<ImportPreview>(`/api/imports/${uploadId}/preview`, json("POST", options)),
  runImport: (uploadId: string, options: ImportOptions) =>
    req<ImportRunResult>(`/api/imports/${uploadId}/run`, json("POST", options)),
  discardImport: (uploadId: string) =>
    req<void>(`/api/imports/${uploadId}`, { method: "DELETE" }),
  previewNumistaImport: (options: NumistaImportOptions) =>
    req<ImportPreview>("/api/imports/numista/preview", json("POST", options)),
  runNumistaImport: (options: NumistaImportOptions) =>
    req<ImportRunResult>("/api/imports/numista/run", json("POST", options)),
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
  importPhoto: (itemId: string, url: string, angle: Angle | "") =>
    req<Photo>(`/api/items/${itemId}/photos/url`, json("POST", { url, angle: angle || null })),
  replacePhotoImage: (photoId: string, image: Blob, filename: string) => {
    const form = new FormData();
    form.append("file", image, filename);
    return req<Photo>(`/api/photos/${photoId}/image`, { method: "PUT", body: form });
  },
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

  uploadDocument: (itemId: string, file: File, kind: DocumentKind) => {
    const form = new FormData();
    form.append("file", file);
    form.append("kind", kind);
    return req<ItemDocument>(`/api/items/${itemId}/documents`, { method: "POST", body: form });
  },
  updateDocument: (
    id: string,
    changes: { kind?: DocumentKind; title?: string; doc_date?: string | null; note?: string | null },
  ) => req<ItemDocument>(`/api/documents/${id}`, json("PATCH", changes)),
  linkDocument: (id: string, itemIds: string[]) =>
    req<ItemDocument>(`/api/documents/${id}/items`, json("POST", { item_ids: itemIds })),
  unlinkDocument: (itemId: string, id: string) =>
    req<void>(`/api/items/${itemId}/documents/${id}`, { method: "DELETE" }),

  addComparable: (itemId: string, sale: ComparableInput) =>
    req<Comparable>(`/api/items/${itemId}/comparables`, json("POST", sale)),
  updateComparable: (id: number, changes: Partial<ComparableInput>) =>
    req<Comparable>(`/api/comparables/${id}`, json("PATCH", changes)),
  deleteComparable: (id: number) => req<void>(`/api/comparables/${id}`, { method: "DELETE" }),
  fetchNumistaSales: (itemId: string) =>
    req<SalesFetchResult>(`/api/items/${itemId}/comparables/numista`, { method: "POST" }),

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
  numistaSearch: (q: string, category: "coin" | "banknote") =>
    req<{ count: number; results: NumistaSearchResult[] }>(
      `/api/numista/search?${new URLSearchParams({ q, category })}`,
    ),
  numistaType: (typeId: number) => req<NumistaType>(`/api/numista/types/${typeId}`),
  pcgsCert: (cert: string) => req<PcgsCert>(`/api/pcgs/cert/${encodeURIComponent(cert)}`),
  similarItems: (params: URLSearchParams) => req<SimilarItem[]>(`/api/items/similar?${params}`),
  listBackups: () => req<BackupList>("/api/backups"),
  testAlert: (target: "webhook" | "heartbeat") =>
    req<MonitorOutcome>(`/api/alerts/test?target=${target}`, { method: "POST" }),
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
