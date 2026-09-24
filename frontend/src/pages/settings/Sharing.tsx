import { FormEvent, useEffect, useState } from "react";

import { api, ChecklistSummary, NewShareLink, SetInfo, ShareKind, ShareLink } from "../../api";
import { EXPOSURE_GUIDANCE_URL, EXPOSURE_WARNING } from "../../auth/exposureWarning";
import { Section, SettingRow, useSettings } from "./shared";

const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString() : "–");

const KIND_LABELS: Record<ShareKind, string> = {
  collection: "Collection",
  set: "Set",
  checklist: "Checklist",
};

/** The six show_* toggles, in the order every form and table here uses. */
const OPTIONS: {
  key: keyof Pick<
    ShareLink,
    "show_photos" | "show_grades" | "show_tags" | "show_notes" | "show_values" | "show_certs"
  >;
  label: string;
}[] = [
  { key: "show_photos", label: "Photos" },
  { key: "show_grades", label: "Grades & certification" },
  { key: "show_tags", label: "Tags" },
  { key: "show_notes", label: "Notes" },
  { key: "show_values", label: "Estimated value" },
  { key: "show_certs", label: "Certification number" },
];

/** A one-line reason for the two toggles that need more than their label,
 * shown under the checkbox list and as its hover title. */
const OPTION_HELP: Partial<Record<ToggleKey, string>> = {
  show_values: "Composition, weight, and fineness always show, so a melt value already follows without this; this toggle adds the estimated value itself. Costs and gains are never shown.",
  show_certs: "The certification number. A cert number is a lookup key into public auction records, which often show what the piece last sold for. A photo of a slab label or a stamped bar shows its number anyway.",
};

type ToggleKey = (typeof OPTIONS)[number]["key"];

function optionsFrom(link: Pick<ShareLink, ToggleKey>): Record<ToggleKey, boolean> {
  return {
    show_photos: link.show_photos,
    show_grades: link.show_grades,
    show_tags: link.show_tags,
    show_notes: link.show_notes,
    show_values: link.show_values,
    show_certs: link.show_certs,
  };
}

/** The new link's URL, shown once after it's created or regenerated, with a
 * Copy button (the same pattern as a new API token in components/account.tsx). */
function NewLinkPanel({ link, onDismiss }: { link: NewShareLink; onDismiss: () => void }) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(link.url);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }

  return (
    <div className="estimate-form" style={{ flexDirection: "column", alignItems: "stretch" }}>
      <p>
        <b>{link.name}</b> ({KIND_LABELS[link.kind]}): copy this link now, it won&apos;t be shown
        again.
      </p>
      <div className="estimate-form" style={{ marginTop: 0 }}>
        <code style={{ wordBreak: "break-all" }}>{link.url}</code>
        <button type="button" onClick={copy}>
          {copied ? "Copied" : "Copy"}
        </button>
        <button type="button" className="link-button" onClick={onDismiss}>
          Dismiss
        </button>
      </div>
    </div>
  );
}

/** The six toggles, inline: used by both the create form and a row's
 * "Options" panel. Two of them (values, cert number) carry a one-line
 * reason beyond their label, shown as a hover title and, since a title
 * alone is easy to miss, as small text underneath the list too. */
function OptionToggles({
  values,
  onChange,
  disabled,
}: {
  values: Record<ToggleKey, boolean>;
  onChange: (key: ToggleKey, checked: boolean) => void;
  disabled?: boolean;
}) {
  const notes = OPTIONS.filter((o) => OPTION_HELP[o.key]);
  return (
    <div className="estimate-form" style={{ flexDirection: "column", alignItems: "stretch", marginTop: 0 }}>
      <div className="estimate-form" style={{ marginTop: 0 }}>
        {OPTIONS.map((o) => (
          <label
            key={o.key}
            className="field"
            style={{ flexDirection: "row", alignItems: "center", gap: "0.4rem" }}
            title={OPTION_HELP[o.key]}
          >
            <input
              type="checkbox"
              checked={values[o.key]}
              disabled={disabled}
              onChange={(e) => onChange(o.key, e.target.checked)}
            />
            {o.label}
          </label>
        ))}
      </div>
      {notes.map((o) => (
        <p key={o.key} className="muted" style={{ margin: 0 }}>
          {o.label}: {OPTION_HELP[o.key]}
        </p>
      ))}
    </div>
  );
}

function CreateLinkForm({
  sets,
  checklists,
  onCreated,
  onError,
}: {
  sets: SetInfo[];
  checklists: ChecklistSummary[];
  onCreated: (link: NewShareLink) => void;
  onError: (message: string) => void;
}) {
  const [kind, setKind] = useState<ShareKind>("collection");
  const [targetId, setTargetId] = useState<string>("");
  const [name, setName] = useState("");
  const [options, setOptions] = useState<Record<ToggleKey, boolean>>({
    show_photos: true,
    show_grades: true,
    show_tags: true,
    show_notes: false,
    show_values: false,
    show_certs: false,
  });
  const [busy, setBusy] = useState(false);

  const targets = kind === "set" ? sets : kind === "checklist" ? checklists : [];

  async function submit(e: FormEvent) {
    e.preventDefault();
    onError("");
    setBusy(true);
    try {
      const link = await api.createShareLink({
        kind,
        set_id: kind === "set" ? Number(targetId) : undefined,
        checklist_id: kind === "checklist" ? Number(targetId) : undefined,
        name: name.trim(),
        ...options,
      });
      onCreated(link);
      setName("");
      setTargetId("");
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
        Kind
        <select
          value={kind}
          onChange={(e) => {
            setKind(e.target.value as ShareKind);
            setTargetId("");
          }}
        >
          <option value="collection">Collection</option>
          <option value="set">Set</option>
          <option value="checklist">Checklist</option>
        </select>
      </label>
      {kind !== "collection" && (
        <label className="field">
          {kind === "set" ? "Set" : "Checklist"}
          <select value={targetId} onChange={(e) => setTargetId(e.target.value)} required>
            <option value="" disabled>
              Choose one…
            </option>
            {targets.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
              </option>
            ))}
          </select>
        </label>
      )}
      <label className="field">
        Name
        <input value={name} onChange={(e) => setName(e.target.value)} maxLength={100} required />
      </label>
      <OptionToggles values={options} onChange={(key, checked) => setOptions((o) => ({ ...o, [key]: checked }))} />
      <div className="estimate-form" style={{ marginTop: 0 }}>
        <button
          className="primary"
          type="submit"
          disabled={busy || !name.trim() || (kind !== "collection" && !targetId)}
        >
          {busy ? "Creating…" : "Create link"}
        </button>
      </div>
    </form>
  );
}

function LinkRow({
  link,
  busy,
  setBusy,
  onChanged,
  onError,
  onCreated,
}: {
  link: ShareLink;
  busy: boolean;
  setBusy: (busy: boolean) => void;
  onChanged: () => void;
  onError: (message: string) => void;
  onCreated: (link: NewShareLink) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [options, setOptions] = useState<Record<ToggleKey, boolean>>(optionsFrom(link));

  async function rename() {
    const name = window.prompt("Rename this link:", link.name);
    if (!name || !name.trim() || name.trim() === link.name) return;
    setBusy(true);
    onError("");
    try {
      await api.updateShareLink(link.id, { name: name.trim() });
      onChanged();
    } catch (err) {
      onError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function saveOptions() {
    setBusy(true);
    onError("");
    try {
      await api.updateShareLink(link.id, options);
      setEditing(false);
      onChanged();
    } catch (err) {
      onError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function regenerate() {
    setBusy(true);
    onError("");
    try {
      const fresh = await api.regenerateShareLink(link.id);
      onCreated(fresh);
      onChanged();
    } catch (err) {
      onError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function revoke() {
    if (!window.confirm(`Revoke "${link.name}"? Anyone using it loses access at once.`)) return;
    setBusy(true);
    onError("");
    try {
      await api.revokeShareLink(link.id);
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
        <td>{link.name}</td>
        <td className="muted">
          {KIND_LABELS[link.kind]}
          {link.target_name ? `: ${link.target_name}` : ""}
        </td>
        <td className="muted">{link.opens}</td>
        <td className="muted">{when(link.last_opened_at)}</td>
        <td className="muted">{when(link.created_at)}</td>
        <td className="provenance-toggle">
          <button disabled={busy} onClick={rename}>
            Rename
          </button>{" "}
          <button
            disabled={busy}
            onClick={() => {
              setOptions(optionsFrom(link));
              setEditing((v) => !v);
            }}
          >
            Options
          </button>{" "}
          <button disabled={busy} onClick={regenerate}>
            Regenerate
          </button>{" "}
          <button className="danger" disabled={busy} onClick={revoke}>
            Revoke
          </button>
        </td>
      </tr>
      {editing && (
        <tr>
          <td colSpan={6}>
            <OptionToggles values={options} onChange={(key, checked) => setOptions((o) => ({ ...o, [key]: checked }))} />
            <div className="estimate-form" style={{ marginTop: "0.4rem" }}>
              <button className="primary" disabled={busy} onClick={saveOptions}>
                Save
              </button>
              <button disabled={busy} onClick={() => setEditing(false)}>
                Cancel
              </button>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

/** Settings → Sharing (v0.32.0): the switch, the live links, and a form to
 * make a new one. Links are listed, and can be managed, whether or not
 * sharing is currently on; only the switch decides whether they answer. */
export default function SharingSection() {
  const { settings, error, saving, apply } = useSettings();
  const [links, setLinks] = useState<ShareLink[] | null>(null);
  const [linksError, setLinksError] = useState<string | null>(null);
  const [sets, setSets] = useState<SetInfo[]>([]);
  const [checklists, setChecklists] = useState<ChecklistSummary[]>([]);
  const [linksBusy, setLinksBusy] = useState(false);
  const [created, setCreated] = useState<NewShareLink | null>(null);

  function loadLinks() {
    api
      .listShareLinks()
      .then(setLinks)
      .catch((e: Error) => setLinksError(e.message));
  }

  useEffect(loadLinks, []);
  useEffect(() => {
    api.listSets().then(setSets).catch(() => setSets([]));
    api.listChecklists().then(setChecklists).catch(() => setChecklists([]));
  }, []);

  if (error && !settings) return <p className="error">{error}</p>;
  if (!settings) return <p className="muted">Loading…</p>;

  return (
    <Section title="Sharing">
      <p className="muted" style={{ marginTop: 0 }}>
        {EXPOSURE_WARNING}{" "}
        <a href={EXPOSURE_GUIDANCE_URL} target="_blank" rel="noreferrer">
          Read the exposure guidance
        </a>
        .
      </p>
      <SettingRow
        label="Turn on sharing"
        htmlFor="share-enabled"
        help="Anyone with a link can see what it shares, without signing in. Costs, gains, storage, and documents are never shown; the estimated value only on a link that allows it."
      >
        <input
          id="share-enabled"
          type="checkbox"
          checked={settings.share_enabled}
          disabled={saving}
          onChange={(e) =>
            apply(
              { share_enabled: e.target.checked },
              e.target.checked
                ? "Sharing turned on."
                : "Sharing turned off; existing links stop answering until it's back on.",
            )
          }
        />
      </SettingRow>

      {!settings.share_enabled && (
        <p className="muted">
          Sharing is off. The links below are kept, but none of them open until it's back on.
        </p>
      )}

      {linksError && <p className="error">{linksError}</p>}
      {!links ? (
        <p className="muted">Loading links…</p>
      ) : links.length === 0 ? (
        <p className="muted">No share links yet.</p>
      ) : (
        <table className="estimates">
          <thead>
            <tr>
              <th>Name</th>
              <th>Shares</th>
              <th>Opens</th>
              <th>Last opened</th>
              <th>Created</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {links.map((link) => (
              <LinkRow
                key={link.id}
                link={link}
                busy={linksBusy}
                setBusy={setLinksBusy}
                onChanged={loadLinks}
                onError={setLinksError}
                onCreated={setCreated}
              />
            ))}
          </tbody>
        </table>
      )}

      {created && <NewLinkPanel link={created} onDismiss={() => setCreated(null)} />}

      <h3>New link</h3>
      <CreateLinkForm
        sets={sets}
        checklists={checklists}
        onCreated={(link) => {
          setCreated(link);
          loadLinks();
        }}
        onError={setLinksError}
      />
    </Section>
  );
}
