import { FormEvent, useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import {
  api,
  DryRunResult,
  IdentitySummary,
  ProviderPreset,
  SavedProvider,
  SigninConfig,
  SigninProvider,
} from "../../api";
import { ensureFresh } from "../../auth/FreshLink";
import { EXPOSURE_GUIDANCE_URL, EXPOSURE_WARNING } from "../../auth/exposureWarning";
import { ssoErrorMessage } from "../../auth/ssoErrors";
import { EyeIcon, EyeOffIcon } from "../../components/icons";
import { Section, SettingRow, SavedTick, useSavedTick } from "./shared";

const PRESET_LABELS: Record<ProviderPreset, string> = {
  google: "Google",
  microsoft: "Microsoft",
  github: "GitHub",
  custom: "Custom OpenID Connect",
};

function isSaved(result: DryRunResult | SavedProvider): result is SavedProvider {
  return "id" in result;
}

/** The exposure notice, shared word for word with Settings -> Sharing. */
function ExposureNotice() {
  return (
    <p className="muted" style={{ marginTop: 0 }}>
      {EXPOSURE_WARNING}{" "}
      <a href={EXPOSURE_GUIDANCE_URL} target="_blank" rel="noreferrer">
        Read the exposure guidance
      </a>
      .
    </p>
  );
}

/** A masked client-secret field, the same eye-toggle pattern as the backup
 * key in Settings -> Backups: it never shows a stored secret (the API is
 * write-only), only what's about to be typed in. */
function SecretField({
  value,
  onChange,
  placeholder,
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
}) {
  const [visible, setVisible] = useState(false);
  return (
    <div className="key-field">
      <input
        type={visible ? "text" : "password"}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        autoComplete="off"
      />
      <button
        type="button"
        className="link-button"
        aria-label={visible ? "Hide client secret" : "Show client secret"}
        onClick={() => setVisible((v) => !v)}
      >
        {visible ? <EyeOffIcon /> : <EyeIcon />}
      </button>
    </div>
  );
}

function CallbackUrls({ urls }: { urls: string[] }) {
  const [copied, setCopied] = useState<string | null>(null);
  async function copy(url: string) {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(url);
    } catch {
      setCopied(null);
    }
  }
  return (
    <div className="estimate-form" style={{ flexDirection: "column", alignItems: "stretch", marginTop: "0.5rem" }}>
      {urls.map((url) => (
        <div key={url} className="estimate-form" style={{ marginTop: 0 }}>
          <code style={{ wordBreak: "break-all" }}>{url}</code>
          <button type="button" onClick={() => copy(url)}>
            {copied === url ? "Copied" : "Copy"}
          </button>
        </div>
      ))}
      <p className="muted" style={{ margin: 0 }}>
        Register this exact URL as the redirect URI at the provider (GitHub: the authorization
        callback URL, one per app).
      </p>
    </div>
  );
}

function AddProviderForm({
  presets,
  onAdded,
  onError,
}: {
  presets: SigninConfig["presets"];
  onAdded: (row: SavedProvider) => void;
  onError: (message: string) => void;
}) {
  const [preset, setPreset] = useState<ProviderPreset>("google");
  const [displayName, setDisplayName] = useState(PRESET_LABELS.google);
  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");
  const [issuer, setIssuer] = useState("");
  const [tenant, setTenant] = useState("");
  const [scopes, setScopes] = useState("");
  const [logoutAtProvider, setLogoutAtProvider] = useState(false);
  const [enabled, setEnabled] = useState(false);
  const [busy, setBusy] = useState(false);
  const [testResult, setTestResult] = useState<DryRunResult | null>(null);

  const info = presets.find((p) => p.name === preset);

  function choosePreset(next: ProviderPreset) {
    setPreset(next);
    // The preset's label is only a suggestion: a name the owner typed
    // ("Authentik") survives a preset change; the suggestion follows it.
    if (displayName.trim() === "" || displayName === PRESET_LABELS[preset]) {
      setDisplayName(PRESET_LABELS[next]);
    }
    setScopes(presets.find((p) => p.name === next)?.scopes ?? "");
    setTestResult(null);
  }

  function body() {
    return {
      preset,
      display_name: displayName.trim(),
      client_id: clientId.trim(),
      client_secret: clientSecret || undefined,
      issuer: info?.needs_issuer ? issuer.trim() : undefined,
      tenant: info?.needs_tenant ? tenant.trim() : undefined,
      scopes: scopes.trim() || undefined,
      logout_at_provider: logoutAtProvider,
      enabled,
    };
  }

  async function test() {
    onError("");
    setTestResult(null);
    setBusy(true);
    try {
      const result = await api.addProvider({ ...body(), dry_run: true });
      setTestResult(result as DryRunResult);
    } catch (err) {
      onError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    onError("");
    setBusy(true);
    try {
      const result = await api.addProvider(body());
      if (isSaved(result)) {
        onAdded(result);
        setClientId("");
        setClientSecret("");
        setIssuer("");
        setTenant("");
        setTestResult(null);
      }
    } catch (err) {
      onError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form
      onSubmit={submit}
      className="estimate-form"
      style={{ flexDirection: "column", alignItems: "stretch", maxWidth: "28rem" }}
    >
      <label className="field">
        Preset
        <select value={preset} onChange={(e) => choosePreset(e.target.value as ProviderPreset)}>
          {presets.map((p) => (
            <option key={p.name} value={p.name}>
              {PRESET_LABELS[p.name]}
            </option>
          ))}
        </select>
      </label>
      {info?.needs_tenant && (
        <label className="field">
          Tenant id
          <input value={tenant} onChange={(e) => setTenant(e.target.value)} required />
        </label>
      )}
      {info?.needs_issuer && (
        <label className="field">
          Issuer URL
          <input
            value={issuer}
            onChange={(e) => setIssuer(e.target.value)}
            placeholder="https://…"
            required
          />
        </label>
      )}
      <label className="field">
        Display name
        <input value={displayName} onChange={(e) => setDisplayName(e.target.value)} required />
      </label>
      <label className="field">
        Client id
        <input value={clientId} onChange={(e) => setClientId(e.target.value)} required />
      </label>
      <label className="field">
        Client secret
        <SecretField value={clientSecret} onChange={setClientSecret} />
      </label>
      <label className="field">
        Scopes
        <input value={scopes} onChange={(e) => setScopes(e.target.value)} />
      </label>
      <label className="field" style={{ flexDirection: "row", alignItems: "center", gap: "0.4rem" }}>
        <input
          type="checkbox"
          checked={logoutAtProvider}
          onChange={(e) => setLogoutAtProvider(e.target.checked)}
        />
        Sign out at the provider too
      </label>
      <label className="field" style={{ flexDirection: "row", alignItems: "center", gap: "0.4rem" }}>
        <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
        Enable now
      </label>
      {testResult && (
        <p className={testResult.ok ? "muted" : "error"} style={{ margin: 0 }}>
          {testResult.ok
            ? `Discovery answered for ${testResult.issuer}. Can re-authenticate for confirm: ${
                testResult.confirm ? "yes" : "no"
              }.`
            : `Discovery failed: ${testResult.error}`}
        </p>
      )}
      <div className="estimate-form" style={{ marginTop: 0 }}>
        <button className="primary" type="submit" disabled={busy || !clientId.trim() || !displayName.trim()}>
          {busy ? "Adding…" : "Add provider"}
        </button>
        {preset !== "github" && (
          <button type="button" onClick={test} disabled={busy || !clientId.trim()}>
            Test
          </button>
        )}
      </div>
    </form>
  );
}

function EditProviderForm({
  provider,
  onSaved,
  onCancel,
  onError,
}: {
  provider: SigninProvider;
  onSaved: (row: SavedProvider) => void;
  onCancel: () => void;
  onError: (message: string) => void;
}) {
  const [displayName, setDisplayName] = useState(provider.display_name);
  const [clientId, setClientId] = useState(provider.client_id);
  const [clientSecret, setClientSecret] = useState("");
  const [scopes, setScopes] = useState(provider.scopes ?? "");
  const [logoutAtProvider, setLogoutAtProvider] = useState(provider.logout_at_provider);
  const [busy, setBusy] = useState(false);

  async function save() {
    onError("");
    setBusy(true);
    try {
      const row = await api.changeProvider(provider.id, {
        display_name: displayName.trim(),
        client_id: clientId.trim(),
        client_secret: clientSecret || undefined,
        scopes: scopes.trim() || undefined,
        logout_at_provider: logoutAtProvider,
      });
      onSaved(row);
    } catch (err) {
      onError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="estimate-form" style={{ flexDirection: "column", alignItems: "stretch", maxWidth: "28rem" }}>
      {provider.linked ? (
        <p className="muted" style={{ margin: 0 }}>
          Issuer and client id can't change while an identity is linked ({provider.issuer}). Remove
          and re-add the provider instead.
        </p>
      ) : (
        <p className="muted" style={{ margin: 0 }}>
          Issuer: {provider.issuer}
        </p>
      )}
      <label className="field">
        Display name
        <input value={displayName} onChange={(e) => setDisplayName(e.target.value)} required />
      </label>
      <label className="field">
        Client id
        <input
          value={clientId}
          onChange={(e) => setClientId(e.target.value)}
          disabled={provider.linked}
          required
        />
      </label>
      <label className="field">
        New client secret
        <SecretField value={clientSecret} onChange={setClientSecret} placeholder="Leave blank to keep it" />
      </label>
      <label className="field">
        Scopes
        <input value={scopes} onChange={(e) => setScopes(e.target.value)} />
      </label>
      <label className="field" style={{ flexDirection: "row", alignItems: "center", gap: "0.4rem" }}>
        <input
          type="checkbox"
          checked={logoutAtProvider}
          onChange={(e) => setLogoutAtProvider(e.target.checked)}
        />
        Sign out at the provider too
      </label>
      <div className="estimate-form" style={{ marginTop: 0 }}>
        <button className="primary" disabled={busy} onClick={save}>
          Save
        </button>
        <button type="button" disabled={busy} onClick={onCancel}>
          Cancel
        </button>
      </div>
    </div>
  );
}

function ProviderRow({
  provider,
  onChanged,
  onError,
}: {
  provider: SigninProvider;
  onChanged: () => void;
  onError: (message: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);

  async function toggleEnabled() {
    setBusy(true);
    onError("");
    try {
      await api.changeProvider(provider.id, { enabled: !provider.enabled });
      onChanged();
    } catch (err) {
      onError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (
      !window.confirm(
        `Remove "${provider.display_name}"? Its linked identity and any sessions that came ` +
          "through it go with it.",
      )
    )
      return;
    setBusy(true);
    onError("");
    try {
      await api.deleteProvider(provider.id);
      onChanged();
    } catch (err) {
      onError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <tr>
        <td>
          {provider.display_name}
          <div className="muted provider-detail">{PRESET_LABELS[provider.preset]}</div>
          {provider.issuer && <div className="muted provider-detail">{provider.issuer}</div>}
          {provider.client_id && (
            <div className="muted provider-detail">Client id {provider.client_id}</div>
          )}
        </td>
        <td>{provider.enabled ? "On" : "Off"}</td>
        <td>
          {provider.linked ? "Linked" : "–"}
          {provider.credentials_failing && (
            <span className="badge status-sold" style={{ marginLeft: "0.3rem" }}>
              credentials rejected
            </span>
          )}
        </td>
        <td className="provenance-toggle provider-actions">
          <button disabled={busy} onClick={toggleEnabled}>
            {provider.enabled ? "Disable" : "Enable"}
          </button>{" "}
          <button disabled={busy} onClick={() => setEditing((v) => !v)}>
            Edit
          </button>{" "}
          <button className="danger" disabled={busy} onClick={remove}>
            Remove
          </button>
        </td>
      </tr>
      {editing && (
        <tr>
          <td colSpan={4}>
            <EditProviderForm
              provider={provider}
              onSaved={() => {
                setEditing(false);
                onChanged();
              }}
              onCancel={() => setEditing(false)}
              onError={onError}
            />
          </td>
        </tr>
      )}
    </>
  );
}

function IdentitiesCard({
  config,
  onChanged,
  onError,
}: {
  config: SigninConfig;
  onChanged: () => void;
  onError: (message: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [linkingHeader, setLinkingHeader] = useState(false);

  async function unlink(identity: IdentitySummary) {
    if (!window.confirm(`Unlink this identity? Its sessions end.`)) return;
    setBusy(true);
    onError("");
    try {
      await api.unlinkIdentity(identity.id);
      onChanged();
    } catch (err) {
      onError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function linkProvider(id: number) {
    onError("");
    try {
      await ensureFresh();
    } catch {
      return;
    }
    window.location.assign(api.oidcStartUrl(id, "/settings/signin", "link"));
  }

  async function linkTrustedHeader() {
    setLinkingHeader(true);
    onError("");
    try {
      await ensureFresh();
      await api.linkTrustedHeader();
      onChanged();
    } catch (err) {
      onError((err as Error).message);
    } finally {
      setLinkingHeader(false);
    }
  }

  const unlinkedProviders = config.providers.filter(
    (p) => p.enabled && !config.identities.some((i) => i.kind === "provider" && i.provider_id === p.id),
  );

  return (
    <>
      <h3>Linked identities</h3>
      {config.identities.length === 0 ? (
        <p className="muted">Nothing linked yet.</p>
      ) : (
        <div className="table-scroll">
          <table className="estimates">
            <thead>
              <tr>
                <th>Identity</th>
                <th>Subject</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {config.identities.map((identity) => (
                <tr key={identity.id}>
                  <td>
                    {identity.kind === "provider" ? (identity.provider ?? "Provider") : "Trusted header"}
                    {identity.display && <div className="muted provider-detail">{identity.display}</div>}
                    <div className="muted provider-detail">{identity.issuer}</div>
                  </td>
                  <td className="muted provider-detail">{identity.subject}</td>
                  <td className="provenance-toggle provider-actions">
                    <button disabled={busy} onClick={() => unlink(identity)}>
                      Unlink
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {unlinkedProviders.length > 0 && (
        <div className="estimate-form" style={{ marginTop: "0.5rem" }}>
          {unlinkedProviders.map((p) => (
            <button key={p.id} type="button" onClick={() => linkProvider(p.id)}>
              {`Link ${p.display_name}`}
            </button>
          ))}
        </div>
      )}
      {config.trusted_header.configured && config.trusted_header.enabled && (
        <div className="estimate-form" style={{ marginTop: "0.5rem", flexDirection: "column", alignItems: "stretch" }}>
          <p className="muted" style={{ margin: 0 }}>
            Trusted header: {config.trusted_header.header_name ?? "–"}, issuer{" "}
            {config.trusted_header.issuer ?? "–"}
          </p>
          {config.trusted_header.link_ready ? (
            <div className="estimate-form" style={{ marginTop: 0 }}>
              <button type="button" disabled={linkingHeader} onClick={linkTrustedHeader}>
                {linkingHeader ? "Linking…" : "Link the identity this proxy asserts"}
              </button>
            </div>
          ) : (
            <p className="muted" style={{ margin: 0 }}>
              This request carried no assertion: open Cabinet through the gateway to link it.
            </p>
          )}
        </div>
      )}
    </>
  );
}

function SwitchesCard({
  config,
  onChanged,
  onError,
}: {
  config: SigninConfig;
  onChanged: (config: SigninConfig) => void;
  onError: (message: string) => void;
}) {
  const [alertsTick, triggerAlertsTick] = useSavedTick();
  const [headerTick, triggerHeaderTick] = useSavedTick();
  const [saving, setSaving] = useState(false);

  async function apply(payload: { password_sign_in_alerts?: boolean; trusted_header_enabled?: boolean }, tick: () => void) {
    setSaving(true);
    onError("");
    try {
      const updated = await api.putSigninConfig(payload);
      onChanged(updated);
      tick();
    } catch (err) {
      onError((err as Error).message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <h3>Switches</h3>
      <SettingRow
        label="Alert on every password sign-in"
        htmlFor="sso-password-alerts"
        help="Switched on when the first provider was enabled; the password is the recovery credential."
      >
        <span style={{ display: "inline-flex", alignItems: "center", gap: "0.4rem" }}>
          <input
            id="sso-password-alerts"
            type="checkbox"
            checked={config.password_sign_in_alerts}
            disabled={saving}
            onChange={(e) =>
              apply({ password_sign_in_alerts: e.target.checked }, triggerAlertsTick)
            }
          />
          <SavedTick shown={alertsTick} />
        </span>
      </SettingRow>
      {config.trusted_header.configured ? (
        <SettingRow
          label="Trusted-header sign-in"
          htmlFor="sso-trusted-header"
          help="Turning this off ends every session that signed in through the proxy, this one included if it did. disable-sso in the container turns it off too; only this switch turns it back on."
        >
          <span style={{ display: "inline-flex", alignItems: "center", gap: "0.4rem" }}>
            <input
              id="sso-trusted-header"
              type="checkbox"
              checked={config.trusted_header.enabled}
              disabled={saving}
              onChange={(e) => apply({ trusted_header_enabled: e.target.checked }, triggerHeaderTick)}
            />
            <SavedTick shown={headerTick} />
          </span>
        </SettingRow>
      ) : (
        <p className="muted">
          Not configured: set the four <code>TRUSTED_ASSERTION_*</code> variables
          (docs/deployment.md).
        </p>
      )}
      <p className="muted" style={{ marginBottom: 0 }}>
        Provider ids and secrets are not in backups: keep them in your password manager beside the
        backup key.
      </p>
    </>
  );
}

/** Settings -> Sign-in (v0.33.0): providers, linked identities, and the
 * trusted-header mode (SPEC_0330 section 10). */
export default function SigninSection() {
  const [config, setConfig] = useState<SigninConfig | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [params] = useSearchParams();
  const navigate = useNavigate();

  function reload() {
    api
      .signinConfig()
      .then(setConfig)
      .catch((e: Error) => setError(e.message));
  }

  useEffect(reload, []);

  useEffect(() => {
    const linked = params.get("linked");
    const code = params.get("error");
    if (!linked && !code) return;
    setNote(linked ? "Linked." : null);
    setError(code ? ssoErrorMessage(code) : null);
    const next = new URLSearchParams(params);
    next.delete("linked");
    next.delete("error");
    navigate({ pathname: "/settings/signin", search: next.toString() }, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (error && !config) return <p className="error">{error}</p>;
  if (!config) return <p className="muted">Loading…</p>;

  return (
    <Section title="Sign-in">
      <ExposureNotice />
      {error && <p className="error">{error}</p>}
      {note && <p className="muted">{note}</p>}

      <h3>Sign-in providers</h3>
      {config.providers.length === 0 ? (
        <p className="muted">No sign-in providers configured yet.</p>
      ) : (
        <div className="table-scroll">
          <table className="estimates">
            <thead>
              <tr>
                <th>Provider</th>
                <th>Enabled</th>
                <th>Linked</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {config.providers.map((p) => (
                <ProviderRow key={p.id} provider={p} onChanged={reload} onError={setError} />
              ))}
            </tbody>
          </table>
        </div>
      )}

      <h3>Add a provider</h3>
      <AddProviderForm
        presets={config.presets}
        onAdded={() => {
          setNote("Provider added.");
          reload();
        }}
        onError={setError}
      />
      <CallbackUrls urls={config.callback_urls} />

      <IdentitiesCard config={config} onChanged={reload} onError={setError} />

      <SwitchesCard config={config} onChanged={setConfig} onError={setError} />

      <p className="muted" style={{ fontSize: "0.85rem" }}>
        The password stays the recovery credential and always works, on any session.
      </p>
    </Section>
  );
}
