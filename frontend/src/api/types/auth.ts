// Sign-in, the account, sessions, tokens, and the audit log (v0.30.0).

export interface AuthState {
  setup_required: boolean;
}

export interface Me {
  username: string;
  role: string;
  via: "session" | "token";
  scope: string | null;
  confirmed_until: string | null; // the recent-password window, or null
}

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
