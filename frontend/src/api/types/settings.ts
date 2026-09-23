// Settings, alerts, backups, pricing reports, and health.

import type { SpotAlert } from "./stack";

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
  numista_sales_enabled: boolean;
  numista_refresh_days: number | null;
  pcgs_auto_refresh: boolean;
  numista_priceable_items: number;
  pcgs_priceable_items: number;
  backup_schedule: BackupSchedule | null;
  backup_retention_days: number; // one of backup_retention_choices (daily or weekly set), or 0 = kept forever
  backup_retention_choices: { daily: number[]; weekly: number[] };
  backup_include_photos: boolean;
  trash_retention_days: number; // 0 = never emptied automatically
  // Saved URLs are secrets: only scheme://host/… comes back.
  alert_webhook_hint: string | null;
  alert_webhook_format: AlertFormat;
  heartbeat_hint: string | null;
  metrics_enabled: boolean;
  share_enabled: boolean;
  // Secrets cleared because they weren't encrypted with this deployment's
  // key, by name, until each is entered again.
  secrets_cleared: string[];
  alerts: AlertStatus[];
  alert_delivery: MonitorOutcome | null;
  heartbeat: MonitorOutcome | null;
  refresh_last_run: Record<string, RefreshRun>;
  sources: SourceStatus[];
  cached: CachedValue[];
  spot_alerts: SpotAlert[]; // met is set on read only
}

export interface AppSettingsUpdate {
  display_currency?: string;
  reestimate_days?: number;
  melt_enabled?: boolean;
  numista_enabled?: boolean;
  numista_api_key?: string;
  pcgs_enabled?: boolean;
  pcgs_api_token?: string;
  comps_enabled?: boolean;
  numista_sales_enabled?: boolean;
  value_strategy?: ValueStrategy;
  preferred_source?: string | null;
  numista_refresh_days?: number | null;
  pcgs_auto_refresh?: boolean;
  backup_schedule?: BackupSchedule | null;
  backup_retention_days?: number;
  backup_include_photos?: boolean;
  trash_retention_days?: number;
  alert_webhook_url?: string; // "" clears
  alert_webhook_format?: AlertFormat;
  heartbeat_url?: string; // "" clears
  metrics_enabled?: boolean;
  share_enabled?: boolean;
  spot_alerts?: Omit<SpotAlert, "met">[];
}

export type AlertFormat = "generic" | "ntfy" | "discord" | "slack" | "gotify";

export interface AlertStatus {
  key: string;
  label: string;
  failing: boolean;
  since: string | null; // when it started failing, or recovered
  message: string | null;
}

export interface MonitorOutcome {
  at: string;
  ok: boolean;
  detail: string;
}

export interface RefreshRun {
  at: string;
  updated: number;
  skipped: number;
  failed: number;
  error?: string | null;
  stopped?: string | null; // why the run stopped early (key or quota)
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
  backups: BackupFile[];
  key: BackupKey;
}

export interface BackupKey {
  fingerprint: string; // the public key (age1...); the key itself never leaves the container
  saved: boolean;
  supplied: boolean; // BACKUP_KEY_FILE or BACKUP_KEY rather than generated
  location: "separate" | "shared" | "not_verified" | "secret" | "environment";
  location_message: string | null;
}

export interface BackupFile {
  name: string;
  size: number;
  created_at: string;
  prerestore?: boolean; // the safety backup taken before a restore
}

export type RestoreStep =
  | "safety_backup"
  | "database"
  | "migrations"
  | "photos"
  | "documents"
  | "finishing";

export interface RestoreOutcome {
  at: string;
  ok: boolean;
  archive: string | null;
  archive_created_at: string | null;
  safety_backup: string | null;
  error: string | null;
  items: number | null;
  photos: number | null;
  documents: number | null;
  // By name only: stored secrets cleared because this deployment can't use them.
  secrets_cleared?: string[];
  // The live share links and switch were kept over the archive's (v0.32.0).
  sharing?: RestoreSharing | null;
}

export interface RestoreSharing {
  links_kept: number;
  links_dropped: number;
  archive_links: number;
  archive_enabled: boolean;
  enabled: boolean;
  differed: boolean;
  error?: string;
}

export interface RestoreStatus {
  enabled: boolean;
  state: "idle" | "running" | "done" | "failed" | null;
  step: string | null; // a RestoreStep while running
  started_at: string | null;
  last: RestoreOutcome | null;
  confirm_phrase: string | null;
}

export interface RestoreCounts {
  revision: string | null;
  items: number | null;
  photos: number | null;
  documents: number | null;
  trashed: number | null;
}

export interface RestoreInspection {
  restore_id: string;
  archive: RestoreCounts & {
    name: string;
    size: number;
    created_at: string | null;
    app_version: string | null;
    includes_photos: boolean;
    includes_documents: boolean;
  };
  current: RestoreCounts;
  will_migrate: boolean;
  replaces_files: boolean;
  secrets_note: string | null;
  credentials_note: string;
  provenance: {
    made_here: boolean;
    made_at: string | null;
    newer: number;
    older: boolean;
    record_empty: boolean;
    message: string;
  };
  confirm_phrase: string; // RESTORE, or RESTORE OLDER
  // By name only: stored secrets the archive would set, and those it holds
  // that would be cleared (not encrypted with this deployment's key).
  secrets: string[];
  secrets_cleared: string[];
}

export interface SchemaState {
  current: string | null;
  expected: string | null;
  status: "ok" | "pending" | "ahead" | "unknown";
}

export interface Health {
  status: string;
  db: string;
  version: string;
  schema: SchemaState;
  auth_schema?: SchemaState; // the sign-in chain (cabinet_auth), v0.30.0
  documents: "ok" | "not_mounted" | "unwritable" | "inside_photos";
}
