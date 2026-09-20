import { FormEvent, useState } from "react";
import { Link } from "react-router-dom";

import { FileButton } from "./controls";
import { UploadIcon } from "./icons";
import { api, DocumentKind, ItemDetail, ItemDocument, ItemListEntry } from "../api";

export const DOCUMENT_KINDS: { key: DocumentKind; label: string }[] = [
  { key: "receipt", label: "Receipt" },
  { key: "invoice", label: "Invoice" },
  { key: "certificate", label: "Certificate of authenticity" },
  { key: "grading_label", label: "Grading label / insert" },
  { key: "appraisal", label: "Appraisal" },
  { key: "correspondence", label: "Correspondence" },
  { key: "other", label: "Other" },
];
const kindLabel = (kind: DocumentKind) => DOCUMENT_KINDS.find((k) => k.key === kind)?.label ?? kind;

const ACCEPT = "application/pdf,image/jpeg,image/png,image/webp";
const fileUrl = (doc: ItemDocument, download = false) =>
  `/api/documents/${doc.id}/file${download ? "?download=true" : ""}`;
const formatSize = (n: number) =>
  n >= 1024 * 1024 ? `${(n / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`;

interface Edit {
  kind: DocumentKind;
  title: string;
  doc_date: string;
  note: string;
}

/** Receipts, certificates, invoices… attached to the item. A document can be
 * shared with other items (one invoice for a lot); removing it here leaves it
 * on the others, and the file goes with its last item. */
export function DocumentsCard({ item, onChanged }: { item: ItemDetail; onChanged: () => void }) {
  const [kind, setKind] = useState<DocumentKind>("receipt");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);
  const [edit, setEdit] = useState<Edit | null>(null);
  const [sharing, setSharing] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [matches, setMatches] = useState<ItemListEntry[] | null>(null);

  async function run(label: string, fn: () => Promise<string | void>) {
    setBusy(label);
    setError(null);
    setNote(null);
    try {
      const message = await fn();
      if (message) setNote(message);
      onChanged();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(null);
    }
  }

  function upload(files: File[]) {
    if (files.length === 0) return;
    run("upload", async () => {
      let added = 0;
      try {
        for (const file of files) {
          await api.uploadDocument(item.id, file, kind);
          added++;
        }
      } finally {
        if (added) onChanged(); // earlier files may have landed before an error
      }
      return `Attached ${added} document${added === 1 ? "" : "s"}.`;
    });
  }

  function startEdit(doc: ItemDocument) {
    setEditing(doc.id);
    setEdit({ kind: doc.kind, title: doc.title, doc_date: doc.doc_date ?? "", note: doc.note ?? "" });
  }

  function saveEdit(e: FormEvent) {
    e.preventDefault();
    if (!editing || !edit) return;
    run("edit", async () => {
      await api.updateDocument(editing, {
        kind: edit.kind,
        title: edit.title.trim(),
        doc_date: edit.doc_date || null,
        note: edit.note.trim() || null,
      });
      setEditing(null);
      return "Document updated.";
    });
  }

  async function search(e: FormEvent) {
    e.preventDefault();
    const params = new URLSearchParams({ q: query.trim(), limit: "20" });
    try {
      const page = await api.listItems(params);
      setMatches(page.items.filter((i) => i.id !== item.id));
    } catch (err) {
      setError((err as Error).message);
    }
  }

  function share(doc: ItemDocument, target: ItemListEntry) {
    run("share", async () => {
      await api.linkDocument(doc.id, [target.id]);
      return `Also attached to ${target.country} ${target.denomination} ${target.year_label}.`;
    });
  }

  function remove(doc: ItemDocument) {
    const others = doc.items.filter((i) => i.id !== item.id);
    const question = others.length
      ? `Remove "${doc.title}" from this item? It stays on ${others.length} other item${others.length === 1 ? "" : "s"}.`
      : `Remove "${doc.title}"? It's on no other item, so the file is deleted.`;
    if (!window.confirm(question)) return;
    run("remove", () => api.unlinkDocument(item.id, doc.id).then(() => "Document removed."));
  }

  return (
    <div
      className={`card photo-drop${dragging ? " dragging" : ""}`}
      onDragOver={(e) => {
        if (e.dataTransfer.types.includes("Files")) {
          e.preventDefault();
          setDragging(true);
        }
      }}
      onDragLeave={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setDragging(false);
      }}
      onDrop={(e) => {
        e.preventDefault();
        setDragging(false);
        upload(Array.from(e.dataTransfer.files));
      }}
    >
      <h2>Documents</h2>
      {error && <p className="error">{error}</p>}
      {note && <p className="gain">{note}</p>}
      {item.documents.length === 0 && (
        <p className="muted">
          No documents yet. Attach receipts, certificates of authenticity, invoices, or grading
          labels (PDF, JPEG, PNG, WebP, up to 25 MB). Drop them here or pick them below.
        </p>
      )}

      <div className="document-list">
        {item.documents.map((doc) => {
          const others = doc.items.filter((i) => i.id !== item.id);
          return (
            <div key={doc.id} className="document-row">
              <a className="document-thumb" href={fileUrl(doc)} target="_blank" rel="noreferrer"
                title="Open">
                {doc.has_thumb ? (
                  <img src={`/api/documents/${doc.id}/thumb`} alt="" loading="lazy" />
                ) : (
                  <span>{doc.content_type === "application/pdf" ? "PDF" : "FILE"}</span>
                )}
              </a>
              <div className="document-body">
                {editing === doc.id && edit ? (
                  <form className="estimate-form" style={{ marginTop: 0 }} onSubmit={saveEdit}>
                    <label className="field">
                      Kind
                      <select value={edit.kind}
                        onChange={(e) => setEdit({ ...edit, kind: e.target.value as DocumentKind })}>
                        {DOCUMENT_KINDS.map((k) => <option key={k.key} value={k.key}>{k.label}</option>)}
                      </select>
                    </label>
                    <label className="field">
                      Title
                      <input required maxLength={200} value={edit.title}
                        onChange={(e) => setEdit({ ...edit, title: e.target.value })} />
                    </label>
                    <label className="field">
                      Date
                      <input type="date" value={edit.doc_date}
                        onChange={(e) => setEdit({ ...edit, doc_date: e.target.value })} />
                    </label>
                    <label className="field">
                      Note
                      <input maxLength={2000} value={edit.note}
                        onChange={(e) => setEdit({ ...edit, note: e.target.value })} />
                    </label>
                    <button className="primary" type="submit" disabled={busy !== null}>Save</button>
                    <button type="button" onClick={() => setEditing(null)}>Cancel</button>
                  </form>
                ) : (
                  <>
                    <div>
                      <a href={fileUrl(doc)} target="_blank" rel="noreferrer"><b>{doc.title}</b></a>{" "}
                      <span className="chip">{kindLabel(doc.kind)}</span>
                    </div>
                    <div className="muted document-meta">
                      {doc.doc_date && <>{doc.doc_date} · </>}
                      {doc.content_type === "application/pdf"
                        ? `PDF${doc.pages ? `, ${doc.pages} page${doc.pages === 1 ? "" : "s"}` : " (password-protected)"}`
                        : doc.content_type.replace("image/", "").toUpperCase()}
                      {" · "}
                      {formatSize(doc.size)}
                    </div>
                    {doc.note && <div className="document-meta">{doc.note}</div>}
                    {others.length > 0 && (
                      <div className="muted document-meta">
                        Also on:{" "}
                        {others.map((other, index) => (
                          <span key={other.id}>
                            {index > 0 && ", "}
                            <Link to={`/items/${other.id}`}>{other.label}</Link>
                          </span>
                        ))}
                      </div>
                    )}
                    <div className="document-actions">
                      <a href={fileUrl(doc, true)}>download</a>
                      <button type="button" className="link-button" onClick={() => startEdit(doc)}>
                        edit
                      </button>
                      <button type="button" className="link-button"
                        onClick={() => {
                          setSharing(sharing === doc.id ? null : doc.id);
                          setMatches(null);
                          setQuery("");
                        }}>
                        attach to other items…
                      </button>
                      <button type="button" className="link-button" disabled={busy !== null}
                        onClick={() => remove(doc)}>
                        remove
                      </button>
                    </div>
                    {sharing === doc.id && (
                      <div className="document-share">
                        <form className="estimate-form" style={{ marginTop: "0.3rem" }} onSubmit={search}>
                          <label className="field">
                            Find items
                            <input value={query} placeholder="country, series, year…"
                              onChange={(e) => setQuery(e.target.value)} />
                          </label>
                          <button type="submit">Search</button>
                        </form>
                        {matches && matches.length === 0 && <p className="muted">No other items match.</p>}
                        {matches && matches.length > 0 && (
                          <ul className="document-matches">
                            {matches.map((m) => {
                              const linked = doc.items.some((i) => i.id === m.id);
                              return (
                                <li key={m.id}>
                                  {m.country} {m.denomination} {m.year_label}
                                  {m.mint_mark ? ` "${m.mint_mark}"` : ""}
                                  {m.series && <span className="muted"> · {m.series}</span>}{" "}
                                  {linked ? (
                                    <span className="muted">(attached)</span>
                                  ) : (
                                    <button type="button" className="link-button"
                                      disabled={busy !== null} onClick={() => share(doc, m)}>
                                      attach
                                    </button>
                                  )}
                                </li>
                              );
                            })}
                          </ul>
                        )}
                      </div>
                    )}
                  </>
                )}
              </div>
            </div>
          );
        })}
      </div>

      <div className="estimate-form">
        <label className="field">
          Kind
          <select value={kind} onChange={(e) => setKind(e.target.value as DocumentKind)}>
            {DOCUMENT_KINDS.map((k) => <option key={k.key} value={k.key}>{k.label}</option>)}
          </select>
        </label>
        <FileButton multiple accept={ACCEPT} disabled={busy !== null} onFiles={upload}>
          <UploadIcon /> {busy === "upload" ? "Uploading…" : "Attach files"}
        </FileButton>
      </div>
      <p className="muted" style={{ marginBottom: 0 }}>
        Documents open in your browser's own viewer. They're kept apart from photos and served
        only through Cabinet, and included in backups.
      </p>
    </div>
  );
}
