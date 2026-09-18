import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api, photoUrl, TrashList } from "../api";

const when = (iso: string) => new Date(iso).toLocaleDateString();

function untilPurge(iso: string): string {
  const days = Math.ceil((new Date(iso).getTime() - Date.now()) / 86_400_000);
  if (days <= 0) return "deleted for good within the hour";
  return `deleted for good in ${days} day${days === 1 ? "" : "s"}`;
}

/** Items deleted from the collection, waiting to be restored or deleted for
 * good. Emptied automatically after the retention set in Settings. */
export default function Trash() {
  const [trash, setTrash] = useState<TrashList | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  const load = () =>
    api
      .listTrash()
      .then((t) => {
        setTrash(t);
        setSelected((prev) => new Set([...prev].filter((id) => t.items.some((i) => i.id === id))));
      })
      .catch((e: Error) => setError(e.message));

  useEffect(() => {
    load();
  }, []);

  async function act(fn: () => Promise<{ count: number }>, message: (n: number) => string) {
    setBusy(true);
    setError(null);
    setNote(null);
    try {
      const { count } = await fn();
      setNote(message(count));
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const plural = (n: number) => `${n} item${n === 1 ? "" : "s"}`;
  const restore = (ids: string[]) =>
    act(() => api.restoreItems(ids), (n) => `Restored ${plural(n)} to the collection.`);
  const purge = (ids: string[]) => {
    if (!window.confirm(`Delete ${plural(ids.length)} for good? Photos, values, and history go too; this can't be undone.`)) return;
    act(() => api.purgeItems(ids), (n) => `Deleted ${plural(n)} for good.`);
  };
  const empty = () => {
    if (!trash || !window.confirm(`Empty the trash? ${plural(trash.items.length)} will be deleted for good; this can't be undone.`)) return;
    act(() => api.emptyTrash(), (n) => `Emptied the trash (${plural(n)}).`);
  };

  if (!trash) return error ? <p className="error">{error}</p> : <p className="muted">Loading…</p>;
  const ids = [...selected];
  const allSelected = trash.items.length > 0 && selected.size === trash.items.length;

  return (
    <>
      <div className="detail-header">
        <h1>Trash</h1>
        <div className="spacer" />
        <Link className="button" to="/collection">Back to the collection</Link>
        <button className="danger" disabled={busy || trash.items.length === 0} onClick={empty}>
          Empty trash
        </button>
      </div>
      <p className="muted" style={{ marginTop: 0 }}>
        Deleted items wait here with their photos, documents, values, and history, and restore
        exactly as they were.{" "}
        {trash.retention_days
          ? `They're deleted for good after ${trash.retention_days} days`
          : "They stay until you delete them — automatic emptying is off"}{" "}
        (<Link to="/settings">Settings</Link>).
      </p>
      {error && <p className="error">{error}</p>}
      {note && <p className="gain">{note}</p>}

      {trash.items.length === 0 ? (
        <div className="empty">The trash is empty.</div>
      ) : (
        <>
          {selected.size > 0 && (
            <div className="toolbar advanced">
              <span style={{ alignSelf: "center" }}><b>{selected.size}</b> selected</span>
              <button className="primary" disabled={busy} onClick={() => restore(ids)}>Restore</button>
              <button className="danger" disabled={busy} onClick={() => purge(ids)}>Delete for good</button>
              <button onClick={() => setSelected(new Set())}>Clear</button>
            </div>
          )}
          <table className="items">
            <thead>
              <tr>
                <th>
                  <input type="checkbox" checked={allSelected} aria-label="Select all"
                    onChange={() =>
                      setSelected(allSelected ? new Set() : new Set(trash.items.map((i) => i.id)))
                    } />
                </th>
                <th></th>
                <th>Item</th>
                <th>Grade</th>
                <th>Deleted</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {trash.items.map((item) => (
                <tr key={item.id}>
                  <td>
                    <input type="checkbox" checked={selected.has(item.id)}
                      onChange={() =>
                        setSelected((prev) => {
                          const next = new Set(prev);
                          if (next.has(item.id)) next.delete(item.id);
                          else next.add(item.id);
                          return next;
                        })
                      } />
                  </td>
                  <td>
                    {item.thumb_key ? (
                      <img className="thumb" src={photoUrl(item.thumb_key)} alt="" />
                    ) : (
                      <div className="thumb placeholder">◎</div>
                    )}
                  </td>
                  <td>
                    <Link to={`/items/${item.id}`}>{item.label}</Link>
                    {item.series && <span className="muted"> · {item.series}</span>}{" "}
                    <span className={`badge ${item.type}`}>{item.type}</span>
                  </td>
                  <td>{item.grade_label ?? "—"}</td>
                  <td>
                    {when(item.deleted_at)}
                    {item.purge_at && <div className="muted sale-title">{untilPurge(item.purge_at)}</div>}
                  </td>
                  <td className="provenance-toggle">
                    <button type="button" className="link-button" disabled={busy}
                      onClick={() => restore([item.id])}>
                      restore
                    </button>{" "}
                    <button type="button" className="link-button" disabled={busy}
                      onClick={() => purge([item.id])}>
                      delete for good
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </>
  );
}
