import { FormEvent, useEffect, useState } from "react";

import { api, ChecklistDetail, ChecklistSummary } from "../api";

export default function Checklists() {
  const [lists, setLists] = useState<ChecklistSummary[]>([]);
  const [open, setOpen] = useState<ChecklistDetail | null>(null);
  const [name, setName] = useState("");
  const [slotText, setSlotText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  const reload = () => api.listChecklists().then(setLists).catch((e: Error) => setError(e.message));

  useEffect(() => {
    reload();
  }, []);

  async function create(e: FormEvent) {
    e.preventDefault();
    setCreating(true);
    setError(null);
    try {
      const slots = slotText.split("\n").map((s) => s.trim()).filter(Boolean);
      const created = await api.createChecklist(name.trim(), slots);
      setName("");
      setSlotText("");
      setOpen(created);
      reload();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setCreating(false);
    }
  }

  async function toggle(slotId: number, filled: boolean) {
    if (!open) return;
    try {
      await api.updateSlot(open.id, slotId, filled);
      setOpen(await api.getChecklist(open.id));
      reload();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function remove(id: number) {
    if (!window.confirm("Delete this checklist?")) return;
    try {
      await api.deleteChecklist(id);
      if (open?.id === id) setOpen(null);
      reload();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <>
      <div className="detail-header">
        <h1>Checklists</h1>
      </div>
      {error && <p className="error">{error}</p>}

      {lists.length === 0 && (
        <div className="empty">
          No checklists yet — define a target set below (e.g. a date/mint run) and track
          completeness against it.
        </div>
      )}

      {lists.map((list) => (
        <div className="card" key={list.id}>
          <div className="detail-header" style={{ marginBottom: "0.5rem" }}>
            <h2 style={{ margin: 0 }}>{list.name}</h2>
            <span className="muted">
              {list.filled} / {list.total}
            </span>
            <div className="progress" title={`${list.filled} of ${list.total}`}>
              <span style={{ width: `${list.total ? (list.filled / list.total) * 100 : 0}%` }} />
            </div>
            <button
              onClick={() =>
                open?.id === list.id
                  ? setOpen(null)
                  : api.getChecklist(list.id).then(setOpen).catch((e: Error) => setError(e.message))
              }
            >
              {open?.id === list.id ? "Collapse" : "Open"}
            </button>
            <button className="danger" onClick={() => remove(list.id)}>Delete</button>
          </div>
          {open?.id === list.id && (
            <div className="slot-grid">
              {open.slots.map((slot) => (
                <label className={`slot${slot.filled ? " filled" : ""}`} key={slot.id}>
                  <input
                    type="checkbox"
                    checked={slot.filled}
                    onChange={(e) => toggle(slot.id, e.target.checked)}
                  />
                  {slot.filled ? <s>{slot.label}</s> : slot.label}
                </label>
              ))}
            </div>
          )}
        </div>
      ))}

      <div className="card">
        <h2>New checklist</h2>
        <form onSubmit={create}>
          <div className="item-form">
            <label className="field">
              Name
              <input required value={name} placeholder="e.g. Washington quarters 1932–1964"
                onChange={(e) => setName(e.target.value)} />
            </label>
            <label className="field full">
              Slots (one per line)
              <textarea required rows={6} value={slotText}
                placeholder={"1932\n1932-D\n1932-S\n1934\n…"}
                onChange={(e) => setSlotText(e.target.value)} />
            </label>
          </div>
          <div className="actions" style={{ marginTop: "0.75rem" }}>
            <button className="primary" type="submit" disabled={creating}>
              {creating ? "Creating…" : "Create checklist"}
            </button>
          </div>
        </form>
      </div>
    </>
  );
}
