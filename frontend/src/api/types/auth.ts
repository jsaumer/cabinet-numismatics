// Sign-in, the account, sessions, tokens, and the audit log (v0.30.0).
// Single sign-on (v0.33.0, SPEC_0330) added `methods` on AuthState, four
// fields on Me, LogoutResult, and the sign-in provider types below.

export interface AuthStateProvider {
  id: number;
  name: string;
  preset: "google" | "microsoft" | "github" | "custom";
}

export interface AuthState {
  setup_required: boolean;
  methods: {
    password: true;
    providers: AuthStateProvider[];
    trusted_header: { available: true } | null;
  };
}

export type AuthMethod = "password" | "oidc" | "trusted_header";

export interface Me {
  username: string;
  role: string;
  via: "session" | "token";
  scope: string | null;
  confirmed_until: string | null; // the recent-password window, or null
  auth_method: AuthMethod | null; // null for a token
  provider_id: number | null; // the provider an oidc session signed in through
  confirm_methods: ("password" | "provider")[];
  // Once after a single sign-on, then null (R2-10): the password sign-in's
  // own answer carries the same figures in LoginResult instead.
  failed_since_previous: number | null;
  previous_sign_in_at: string | null;
}

/** POST /api/auth/logout: 204 (void) normally, or, for an oidc session with
 * "sign out there too" on, 200 {redirect} for the browser to follow. */
export type LogoutResult = { redirect: string } | undefined;

export interface LoginResult {
  username: string;
  previous_sign_in_at: string | null;
  failed_since_previous: number;
}

export interface AuthSession {
  id: string;
  created_at: string;
  last_seen_at: string;
  address: string | null;
  user_agent: string | null;
  current: boolean;
}

export type TokenScope = "read" | "write" | "metrics";

export interface ApiToken {
  id: string;
  name: string;
  scope: TokenScope;
  created_at: string;
  last_used_at: string | null;
  expires_at: string | null; // null: a metrics token that never expires
}

/** What POST /api/auth/tokens answers: the token itself, shown once. */
export interface NewApiToken extends ApiToken {
  token: string;
}

export interface RevokedTokenSummary {
  id: string;
  name: string;
  scope: TokenScope;
}

export interface PasswordChangeResult {
  revoked_tokens: RevokedTokenSummary[];
}

export type AuditAction =
  | "setup"
  | "sign_in"
  | "sign_in_failed"
  | "sign_out"
  | "reauth"
  | "password_changed"
  | "username_changed"
  | "password_reset"
  | "sessions_revoked_all"
  | "tokens_revoked_all"
  | "session_revoked"
  | "token_created"
  | "token_revoked"
  | "backup_downloaded"
  | "export_downloaded"
  | "restore_started"
  | "restore_finished"
  | "secrets_cleared"
  | string;

export interface AuditEntry {
  id: number;
  at: string;
  actor_kind: "session" | "token" | "anonymous" | "cli" | "system";
  actor_label: string;
  action: AuditAction;
  target: string | null;
  detail: Record<string, unknown> | null;
  address: string | null;
  user_agent: string | null;
}

// --- single sign-on configuration (v0.33.0, Settings -> Sign-in) --------------------

export type ProviderPreset = "google" | "microsoft" | "github" | "custom";
export type ProviderKind = "oidc" | "oauth2_profile";

export interface SigninProvider {
  id: number;
  preset: ProviderPreset;
  kind: ProviderKind;
  display_name: string;
  enabled: boolean;
  issuer: string;
  client_id: string;
  scopes: string | null;
  logout_at_provider: boolean;
  has_secret: boolean;
  credentials_failing: boolean;
  linked: boolean;
}

export interface IdentitySummary {
  id: number;
  kind: "provider" | "trusted_header";
  provider_id: number | null;
  provider: string | null; // the provider's display name, "provider" identities only
  issuer: string;
  subject: string;
  display: string | null;
}

export interface SigninPreset {
  name: ProviderPreset;
  kind: ProviderKind;
  issuer: string | null; // null for microsoft (needs a tenant) and custom
  needs_tenant: boolean;
  needs_issuer: boolean;
  scopes: string | null;
}

export interface SigninConfig {
  providers: SigninProvider[];
  identities: IdentitySummary[];
  trusted_header: {
    configured: boolean;
    enabled: boolean;
    header_name: string | null;
    issuer: string | null;
    link_ready: boolean; // the assertion is present on this very request
  };
  password_sign_in_alerts: boolean;
  presets: SigninPreset[];
  callback_urls: string[];
}

export interface SigninConfigPatch {
  password_sign_in_alerts?: boolean;
  trusted_header_enabled?: boolean;
}

export interface ProviderBody {
  preset: ProviderPreset;
  display_name: string;
  client_id: string;
  client_secret?: string;
  issuer?: string; // custom only
  tenant?: string; // microsoft only
  scopes?: string;
  logout_at_provider?: boolean;
  enabled?: boolean;
  dry_run?: boolean;
}

export interface ProviderPatch {
  preset?: ProviderPreset;
  display_name?: string;
  client_id?: string;
  client_secret?: string;
  issuer?: string;
  tenant?: string;
  scopes?: string;
  logout_at_provider?: boolean;
  enabled?: boolean;
}

/** POST /api/auth/providers with dry_run: true fetches discovery only. */
export type DryRunResult =
  | { ok: true; issuer: string; claims_supported_auth_time: boolean; prompt_login: boolean }
  | { ok: false; issuer: string; error: string };

/** A saved provider (POST/PATCH), with the callback URLs to register at
 * the provider's console. */
export type SavedProvider = SigninProvider & { callback_urls: string[] };
