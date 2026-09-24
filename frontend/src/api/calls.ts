// Every endpoint the frontend calls, one method each.

import { json, req, ReqOptions } from "./client";
import type { Angle, CalendarReference, Comparable, ComparableInput, ConvertedDate, DocumentKind, Estimate, Grade, Item, ItemDetail, ItemDocument, ItemListEntry, ItemPage, ItemPayload, Photo, SalesFetchResult, SerialTrait, SetInfo, SimilarItem, TagInfo } from "./types/items";
import type { ImportOptions, ImportPreview, ImportRunResult, ImportUpload, NumistaImportOptions, NumistaSearchResult, NumistaType, PcgsCert } from "./types/imports";
import type { Breakdowns, ChecklistDetail, ChecklistGenerate, ChecklistSlot, ChecklistSummary, DataHealth, RunCreate, RunResult, CollectionStats, Gains, ItemEvent, NotesBySignature, QualityStats, RefreshResult, Showcase, TrashList, ValueHistory, ValueSpread } from "./types/stats";
import type { DashboardLayout, DashboardWidget } from "./types/dashboard";
import type { AccuracyReport, AppSettings, AppSettingsUpdate, BackupKey, BackupList, BackupRun, Health, MonitorOutcome, PricingCoverage, RestoreInspection, RestoreStatus, SourcesReport, StaleReport } from "./types/settings";
import type { HistoricSpot, StackBackfillResult, StackReport } from "./types/stack";
import type { ApiToken, AuditEntry, AuthSession, AuthState, DryRunResult, IdentitySummary, LoginResult, LogoutResult, Me, NewApiToken, PasswordChangeResult, ProviderBody, ProviderPatch, SavedProvider, SigninConfig, SigninConfigPatch, TokenScope } from "./types/auth";
import type { NewShareLink, ShareChecklistView, ShareItem, ShareItemsPage, ShareLink, ShareLinkCreate, ShareLinkPatch, ShareManifest } from "./types/share";

export const api = {
  // Sign-in, the account, sessions, tokens, and the audit log (v0.30.0).
  // `state`, `setup`, and `login` are `raw`: they answer 401/403 as
  // ordinary form errors, never the global sign-out redirect or reauth
  // dialog (see client.ts and auth/AuthContext.tsx).
  authState: () => req<AuthState>("/api/auth/state", undefined, { raw: true }),
  setup: (payload: { code: string; username: string; password: string }) =>
    req<Me>("/api/auth/setup", json("POST", payload), { raw: true }),
  login: (payload: { username: string; password: string }) =>
    req<LoginResult>("/api/auth/login", json("POST", payload), { raw: true }),
  logout: () => req<LogoutResult>("/api/auth/logout", { method: "POST" }),
  me: (opts?: ReqOptions) => req<Me>("/api/auth/me", undefined, opts),
  confirmPassword: (password: string) =>
    req<void>("/api/auth/confirm", json("POST", { password }), { raw: true }),
  changePassword: (payload: { current_password: string; new_password: string }) =>
    req<PasswordChangeResult>("/api/auth/password", json("POST", payload)),
  changeUsername: (payload: { current_password: string; username: string }) =>
    req<void>("/api/auth/username", json("POST", payload)),
  listSessions: () => req<AuthSession[]>("/api/auth/sessions"),
  endSession: (id: string) => req<void>(`/api/auth/sessions/${id}`, { method: "DELETE" }),
  endAllSessions: () => req<void>("/api/auth/sessions", { method: "DELETE" }),
  listTokens: () => req<ApiToken[]>("/api/auth/tokens"),
  createToken: (payload: { name: string; scope: TokenScope; days: number | null }) =>
    req<NewApiToken>("/api/auth/tokens", json("POST", payload)),
  revokeToken: (id: string) => req<void>(`/api/auth/tokens/${id}`, { method: "DELETE" }),
  auditLog: (params: { before?: number; limit?: number } = {}) => {
    const q = new URLSearchParams();
    if (params.before != null) q.set("before", String(params.before));
    q.set("limit", String(params.limit ?? 50));
    return req<AuditEntry[]>(`/api/auth/audit?${q}`);
  },

  // Single sign-on (v0.33.0): providers, linked identities, and the
  // trusted-header mode, all under Settings -> Sign-in.
  signinConfig: () => req<SigninConfig>("/api/auth/signin-config"),
  putSigninConfig: (payload: SigninConfigPatch) =>
    req<SigninConfig>("/api/auth/signin-config", json("PUT", payload)),
  addProvider: (payload: ProviderBody) =>
    req<DryRunResult | SavedProvider>("/api/auth/providers", json("POST", payload)),
  changeProvider: (id: number, payload: ProviderPatch) =>
    req<SavedProvider>(`/api/auth/providers/${id}`, json("PATCH", payload)),
  deleteProvider: (id: number) => req<void>(`/api/auth/providers/${id}`, { method: "DELETE" }),
  unlinkIdentity: (id: number) => req<void>(`/api/auth/identities/${id}`, { method: "DELETE" }),
  linkTrustedHeader: () =>
    req<IdentitySummary>("/api/auth/identities/trusted_header", { method: "POST" }),
  /** No JSON body needed; an empty object is accepted. Raw: a 403/404/502
   * here is shown on the sign-in page itself, not treated as "signed out". */
  trustedSignIn: () =>
    req<{ username: string }>("/api/auth/trusted", json("POST", {}), { raw: true }),

  /** GET /api/auth/oidc/start?provider=...&next=...[&intent=...]: a plain
   * navigation target, never fetched (the route sets a cookie and 302s). */
  oidcStartUrl: (providerId: number, next: string, intent?: "login" | "link" | "confirm") => {
    const q = new URLSearchParams({ provider: String(providerId), next });
    if (intent) q.set("intent", intent);
    return `/api/auth/oidc/start?${q}`;
  },

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

  listGrades: (scale?: string) =>
    req<Grade[]>(`/api/grades${scale ? `?scale=${scale}` : ""}`),
  serialTraits: () => req<SerialTrait[]>("/api/reference/serial-traits"),
  calendars: () => req<CalendarReference>("/api/reference/calendars"),
  convertDate: (calendar: string, year: number, era?: string) =>
    req<ConvertedDate>(
      `/api/reference/convert-date?${new URLSearchParams({
        calendar,
        year: String(year),
        ...(era ? { era } : {}),
      })}`,
    ),
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

  deleteEstimate: (itemId: string, estimateId: string) =>
    req<void>(`/api/items/${itemId}/estimates/${estimateId}`, { method: "DELETE" }),
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
    req<Estimate>(`/api/items/${itemId}/estimates/auto?source=${source}`, { method: "POST" }),

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
  /** Every breakdown, optionally scoped to one tag or set. */
  breakdowns: (scope?: { tag?: string | null; set_id?: number | null }) => {
    const params = new URLSearchParams();
    if (scope?.tag) params.set("tag", scope.tag);
    if (scope?.set_id != null) params.set("set_id", String(scope.set_id));
    const query = params.toString();
    return req<Breakdowns>(`/api/stats/breakdowns${query ? `?${query}` : ""}`);
  },
  gains: () => req<Gains>("/api/stats/gains"),
  valueHistory: (months = 24) => req<ValueHistory>(`/api/stats/value-history?months=${months}`),
  notesBySignature: () => req<NotesBySignature>("/api/stats/notes-by-signature"),
  quality: () => req<QualityStats>("/api/stats/quality"),
  valueSpread: () => req<ValueSpread>("/api/stats/value-spread"),
  dataHealth: () => req<DataHealth>("/api/stats/data-health"),
  showcase: () => req<Showcase>("/api/stats/showcase"),
  // Only "melt" can be refreshed by hand for now; the server refuses the rest.
  refreshEstimates: (source: "melt") =>
    req<RefreshResult>(`/api/estimates/refresh?source=${source}`, { method: "POST" }),

  itemHistory: (id: string) => req<ItemEvent[]>(`/api/items/${id}/history`),

  dashboardLayout: () => req<DashboardLayout>("/api/dashboard/layout"),
  saveDashboardLayout: (widgets: DashboardWidget[]) =>
    req<DashboardLayout>("/api/dashboard/layout", json("PUT", { widgets })),
  /** Forgets the saved layout: the default comes back. */
  resetDashboardLayout: () =>
    req<DashboardLayout>("/api/dashboard/layout", { method: "DELETE" }),

  listChecklists: () => req<ChecklistSummary[]>("/api/checklists"),
  createChecklist: (name: string, slots: string[]) =>
    req<ChecklistDetail>("/api/checklists", json("POST", { name, slots })),
  getChecklist: (id: number) => req<ChecklistDetail>(`/api/checklists/${id}`),
  generateChecklist: (payload: ChecklistGenerate) =>
    req<ChecklistDetail>("/api/checklists/generate", json("POST", payload)),
  addRun: (payload: RunCreate) => req<RunResult>("/api/items/run", json("POST", payload)),
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
  numistaSearch: (q: string, category: "coin" | "banknote" | "exonumia") =>
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
  markBackupKeySaved: () => req<BackupKey>("/api/backups/key/saved", { method: "POST" }),
  deleteBackup: (name: string) =>
    req<{ deleted: string }>(`/api/backups/${encodeURIComponent(name)}`, { method: "DELETE" }),

  restoreStatus: () => req<RestoreStatus>("/api/restore/status"),
  inspectRestoreFile: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return req<RestoreInspection>("/api/restore/inspect", { method: "POST", body: form });
  },
  inspectRestoreArchive: (name: string) =>
    req<RestoreInspection>(`/api/restore/inspect?name=${encodeURIComponent(name)}`, {
      method: "POST",
    }),
  runRestore: (restoreId: string, confirm: string) =>
    req<{ state: string }>(
      `/api/restore/${encodeURIComponent(restoreId)}/run`,
      json("POST", { confirm }),
    ),
  discardRestore: (restoreId: string) =>
    req<void>(`/api/restore/${encodeURIComponent(restoreId)}`, { method: "DELETE" }),

  getStack: (scope?: { currency?: string; tag?: string | null; set_id?: number | null }) => {
    const params = new URLSearchParams();
    if (scope?.currency) params.set("currency", scope.currency);
    if (scope?.tag) params.set("tag", scope.tag);
    if (scope?.set_id != null) params.set("set_id", String(scope.set_id));
    const query = params.toString();
    return req<StackReport>(`/api/stack${query ? `?${query}` : ""}`);
  },
  backfillStack: () => req<StackBackfillResult>("/api/stack/backfill", { method: "POST" }),
  historicSpot: (metal: string, date: string, currency: string) =>
    req<HistoricSpot>(
      `/api/reference/historic-spot?${new URLSearchParams({ metal, date, currency })}`,
    ),

  pricingCoverage: () => req<PricingCoverage>("/api/pricing/coverage"),
  pricingStale: (days: number) => req<StaleReport>(`/api/pricing/stale?days=${days}`),
  pricingSources: () => req<SourcesReport>("/api/pricing/sources"),
  pricingAccuracy: () => req<AccuracyReport>("/api/pricing/accuracy"),

  // Share links (v0.32.0): managing them is admin, through req() as usual
  // (the fresh ones open the password dialog by themselves). Opening a link
  // is public and outside the sign-in gate, so those calls are raw: a 404
  // there means "not a valid link," not "signed out."
  listShareLinks: () => req<ShareLink[]>("/api/share-links"),
  createShareLink: (payload: ShareLinkCreate) =>
    req<NewShareLink>("/api/share-links", json("POST", payload)),
  updateShareLink: (id: string, patch: ShareLinkPatch) =>
    req<ShareLink>(`/api/share-links/${id}`, json("PATCH", patch)),
  regenerateShareLink: (id: string) =>
    req<NewShareLink>(`/api/share-links/${id}/regenerate`, { method: "POST" }),
  revokeShareLink: (id: string) => req<void>(`/api/share-links/${id}`, { method: "DELETE" }),

  shareManifest: (token: string) =>
    req<ShareManifest>(`/api/share/${encodeURIComponent(token)}`, undefined, { raw: true }),
  shareItems: (token: string, offset: number, limit = 100) =>
    req<ShareItemsPage>(
      `/api/share/${encodeURIComponent(token)}/items?${new URLSearchParams({
        offset: String(offset),
        limit: String(limit),
      })}`,
      undefined,
      { raw: true },
    ),
  shareItem: (token: string, itemId: string) =>
    req<ShareItem>(
      `/api/share/${encodeURIComponent(token)}/items/${encodeURIComponent(itemId)}`,
      undefined,
      { raw: true },
    ),
  shareChecklist: (token: string) =>
    req<ShareChecklistView>(`/api/share/${encodeURIComponent(token)}/checklist`, undefined, {
      raw: true,
    }),

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
