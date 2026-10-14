import { FocusEvent, KeyboardEvent, ReactNode, useEffect, useRef, useState } from "react";

import { api, Grade, gradeScaleFor, ItemPayload, ItemType } from "../api";

/** What editing one fact in place changes, and how. */
export interface EditSpec {
  field: keyof ItemPayload;
  kind: "text" | "number" | "integer" | "date" | "grade";
  /** The stored value, not the formatted one shown. */
  raw: string | number | null | undefined;
  /** For a number: decimals allowed ("0.01"), and a unit shown beside it. */
  step?: string;
  unit?: string;
}

export type SaveFact = (patch: Partial<ItemPayload>) => Promise<void>;

/** Grade rows per scale, fetched once a session. */
const gradeCache = new Map<string, Promise<Grade[]>>();
function gradesFor(type: ItemType): Promise<Grade[]> {
  const scale = gradeScaleFor(type);
  let found = gradeCache.get(scale);
  if (!found) {
    found = api.listGrades(scale).catch(() => {
      gradeCache.delete(scale);
      return [];
    });
    gradeCache.set(scale, found);
  }
  return found;
}

/** A fact's value that turns into a field on click. Enter or leaving the
 * field saves (an unchanged value saves nothing), Escape puts it back. */
export function EditableValue({
  label,
  shown,
  spec,
  itemType,
  onSave,
}: {
  label: string;
  shown: ReactNode;
  spec: EditSpec;
  itemType: ItemType;
  onSave: SaveFact;
}) {
  const initial = spec.raw == null ? "" : String(spec.raw);
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [grades, setGrades] = useState<Grade[] | null>(null);
  const [saved, setSaved] = useState(false);
  const done = useRef(false);

  useEffect(() => {
    if (!editing) setText(initial);
  }, [initial, editing]);

  useEffect(() => {
    if (editing) done.current = false;
  }, [editing]);

  useEffect(() => {
    if (editing && spec.kind === "grade" && grades === null) {
      gradesFor(itemType).then(setGrades);
    }
  }, [editing, spec.kind, grades, itemType]);

  useEffect(() => {
    if (!saved) return;
    const timer = setTimeout(() => setSaved(false), 1800);
    return () => clearTimeout(timer);
  }, [saved]);

  function parse(): { ok: true; value: string | number | null } | { ok: false; message: string } {
    const t = text.trim();
    if (t === "") return { ok: true, value: null };
    if (spec.kind === "number" || spec.kind === "integer" || spec.kind === "grade") {
      const n = Number(t);
      if (!Number.isFinite(n) || (spec.kind !== "number" && !Number.isInteger(n))) {
        return { ok: false, message: spec.kind === "number" ? "Enter a number." : "Enter a whole number." };
      }
      return { ok: true, value: n };
    }
    return { ok: true, value: t };
  }

  async function commit() {
    if (done.current) return;
    const parsed = parse();
    if (!parsed.ok) {
      setError(parsed.message);
      return;
    }
    done.current = true;
    if (String(parsed.value ?? "") === initial) {
      setEditing(false);
      setError(null);
      return;
    }
    setBusy(true);
    try {
      await onSave({ [spec.field]: parsed.value } as Partial<ItemPayload>);
      setEditing(false);
      setError(null);
      setSaved(true);
    } catch (err) {
      done.current = false;
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  function cancel() {
    done.current = true;
    setText(initial);
    setError(null);
    setEditing(false);
  }

  function onKey(e: KeyboardEvent) {
    if (e.key === "Enter") {
      e.preventDefault();
      void commit();
    } else if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      cancel();
    }
  }

  if (!editing) {
    return (
      <>
        <button
          type="button"
          className="fact-edit"
          title={`Change ${label.toLowerCase()}`}
          aria-label={`${label}: change`}
          onClick={() => setEditing(true)}
        >
          {shown}
        </button>
        {saved && <span className="saved-tick" role="status">Saved</span>}
      </>
    );
  }

  const common = {
    autoFocus: true,
    id: `edit-${String(spec.field)}`,
    "aria-label": label,
    disabled: busy,
    onKeyDown: onKey,
    onBlur: () => void commit(),
  };

  return (
    <span className="fact-editing">
      {spec.kind === "grade" ? (
        <select {...common} value={text} onChange={(e) => setText(e.target.value)}>
          <option value="">Ungraded</option>
          {(grades ?? []).map((g) => (
            <option key={g.id} value={g.id}>
              {g.code} ({g.label})
            </option>
          ))}
        </select>
      ) : (
        <input
          {...common}
          type={spec.kind === "date" ? "date" : spec.kind === "text" ? "text" : "number"}
          step={spec.kind === "integer" ? "1" : spec.step}
          inputMode={spec.kind === "number" ? "decimal" : spec.kind === "integer" ? "numeric" : undefined}
          value={text}
          onFocus={(e: FocusEvent<HTMLInputElement>) => e.currentTarget.select()}
          onChange={(e) => setText(e.target.value)}
        />
      )}
      {spec.unit && <span className="muted">{spec.unit}</span>}
      <span className="fact-hint muted" aria-hidden="true">
        {busy ? "Saving…" : "Enter to save · Esc"}
      </span>
      {error && (
        <span className="error fact-error" role="alert">
          {error}
        </span>
      )}
    </span>
  );
}
