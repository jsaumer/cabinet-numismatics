import { FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api, ChecklistDetail, ChecklistSummary } from "../api";

export default function Checklists() {
  const [lists, setLists] = useState<ChecklistSummary[]>([]);
  const [open, setOpen] = useState<ChecklistDetail | null>(null);
  const [missingOnly, setMissingOnly] = useState(false);
  const [name, setName] = useState("");
  const [slotText, setSlotText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [range, setRange] = useState({
    country: "",
    denomination: "",
    year_from: "",
    year_to: "",
    mint_marks: "",
    skip: "",
  });
  const [typeId, setTypeId] = useState("");

  const reload = () => api.listChecklists().then(setLists).catch((e: Error) => setError(e.message));

  useEffect(() => {
    reload();
  }, []);

  async function run(make: () => Promise<ChecklistDetail>, reset: () => void) {
    setCreating(true);
    setError(null);
    try {
      const created = await make();
      reset();
      setOpen(created);
      reload();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setCreating(false);
    }
  }

  function create(e: FormEvent) {
    e.preventDefault();
    const slots = slotText.split("\n").map((s) => s.trim()).filter(Boolean);
    run(() => api.createChecklist(name.trim(), slots), () => {
      setName("");
      setSlotText("");
    });
  }

  function generateRange(e: FormEvent) {
    e.preventDefault();
    const list = (text: string) => text.split(",").map((s) => s.trim());
    // "" is the no-mint-mark slot; "P, D, S" leaves it out, ", D, S" keeps it.
    const mints = range.mint_marks.trim() === "" ? [""] : list(range.mint_marks);
    run(
      () =>
        api.generateChecklist({
          source: "range",
          country: range.country.trim(),
          denomination: range.denomination.trim(),
          year_from: Number(range.year_from),
          year_to: Number(range.year_to),
          mint_marks: mints,
          skip: list(range.skip).filter(Boolean),
        }),
      () => setRange((r) => ({ ...r, year_from: "", year_to: "", skip: "" })),
    );
  }

  function generateType(e: FormEvent) {
    e.preventDefault();
    const id = Number(typeId.replace(/\D/g, ""));
    if (!id) return;
    run(() => api.generateChecklist({ source: "numista", type_id: id }), () => setTypeId(""));
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

  const rangeField = (key: keyof typeof range) => ({
    value: range[key],
    onChange: (e: { target: { value: string } }) =>
      setRange((r) => ({ ...r, [key]: e.target.value })),
  });

  return (
    <>
      <div className="detail-header">
        <h1>Checklists</h1>
        <div className="spacer" />
        <Link className="button" to="/items/run">Add a run</Link>
      </div>
      {error && <p className="error">{error}</p>}

      {lists.length === 0 && (
        <div className="empty">
          No checklists yet — generate one below from a date range or a Numista type, and it fills
          itself from the coins you own.
        </div>
      )}

      {lists.map((list) => (
        <div className="card" key={list.id}>
          <div className="detail-header" style={{ marginBottom: "0.5rem" }}>
            <h2 style={{ margin: 0 }}>{list.name}</h2>
            <span className="muted">
              {list.filled} / {list.total}
              {list.total > 0 && ` · ${Math.round((list.filled / list.total) * 100)}%`}
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
            <>
              <p className="muted" style={{ marginTop: 0 }}>
                {open.match_ref
                  ? `Fills itself from owned items carrying ${open.match_catalog} ${open.match_ref}, by year and mint mark.`
                  : open.match_country
                    ? `Fills itself from owned ${open.match_country} ${open.match_denomination} items, by year and mint mark.`
                    : "Ticked by hand."}{" "}
                <label className="slot" style={{ display: "inline-flex" }}>
                  <input type="checkbox" checked={missingOnly}
                    onChange={(e) => setMissingOnly(e.target.checked)} />
                  needed to complete only ({open.total - open.filled})
                </label>
              </p>
              <div className="slot-grid">
                {open.slots
                  .filter((slot) => !missingOnly || !slot.filled)
                  .map((slot) => (
                    <label className={`slot${slot.filled ? " filled" : ""}`} key={slot.id}
                      title={slot.matched_label ?? undefined}>
                      <input
                        type="checkbox"
                        checked={slot.filled}
                        disabled={slot.matched_item_id !== null}
                        onChange={(e) => toggle(slot.id, e.target.checked)}
                      />
                      {slot.matched_item_id ? (
                        <Link to={`/items/${slot.matched_item_id}`}>{slot.label}</Link>
                      ) : slot.filled ? (
                        <s>{slot.label}</s>
                      ) : (
                        slot.label
                      )}
                    </label>
                  ))}
              </div>
            </>
          )}
        </div>
      ))}

      <div className="card">
        <h2>Generate from a date range</h2>
        <form onSubmit={generateRange}>
          <div className="item-form">
            <label className="field">
              Country
              <input required placeholder="United States" {...rangeField("country")} />
            </label>
            <label className="field">
              Denomination
              <input required placeholder="25 cents — as your items spell it"
                {...rangeField("denomination")} />
            </label>
            <label className="field">
              First year
              <input required type="number" {...rangeField("year_from")} />
            </label>
            <label className="field">
              Last year
              <input required type="number" {...rangeField("year_to")} />
            </label>
            <label className="field">
              Mint marks (comma-separated)
              <input placeholder='", D, S" — a leading comma keeps the no-mint-mark slot'
                {...rangeField("mint_marks")} />
            </label>
            <label className="field">
              Leave out (comma-separated)
              <input placeholder="1933, 1934-S" {...rangeField("skip")} />
            </label>
          </div>
          <p className="muted">
            One slot per year and mint mark. A slot fills when you own an item of that country,
            denomination, year, and mint mark — spelled the same way.
          </p>
          <div className="actions">
            <button className="primary" type="submit" disabled={creating}>Generate</button>
          </div>
        </form>
      </div>

      <div className="card">
        <h2>Generate from a Numista type</h2>
        <form onSubmit={generateType} className="estimate-form" style={{ marginTop: 0 }}>
          <label className="field">
            Numista number
            <input required value={typeId} placeholder="N#1493"
              onChange={(e) => setTypeId(e.target.value)} />
          </label>
          <button type="submit" disabled={creating || !typeId.trim()}>Generate</button>
        </form>
        <p className="muted" style={{ marginBottom: 0 }}>
          One slot per issue Numista lists; filled by owned items carrying that Numista number
          (items added with “Fill from Numista” or “Add a run” do). Needs a Numista API key.
        </p>
      </div>

      <div className="card">
        <h2>Write one by hand</h2>
        <form onSubmit={create}>
          <div className="item-form">
            <label className="field">
              Name
              <input required value={name} placeholder="e.g. Type set"
                onChange={(e) => setName(e.target.value)} />
            </label>
            <label className="field full">
              Slots (one per line)
              <textarea required rows={4} value={slotText}
                placeholder={"Half cent\nLarge cent\n…"}
                onChange={(e) => setSlotText(e.target.value)} />
            </label>
          </div>
          <div className="actions" style={{ marginTop: "0.75rem" }}>
            <button type="submit" disabled={creating}>
              {creating ? "Creating…" : "Create checklist"}
            </button>
          </div>
        </form>
      </div>
    </>
  );
}
