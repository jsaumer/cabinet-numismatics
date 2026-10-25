import { FormEvent, KeyboardEvent, useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import {
  api,
  CatalogRef,
  Grade,
  gradeScaleFor,
  ItemType,
  money,
  ndYearLabel,
  NumistaIssue,
  NumistaSearchResult,
} from "../api";
import { DuplicateWarning } from "../components/duplicates";
import { TYPE_INFO } from "../components/item-types";
import { EMPTY, FormState, toPayload } from "./item-form/model";
import { fillFromNumista, issueFields } from "./item-form/NumistaFill";
import { fillFromCert } from "./item-form/PcgsFill";

/** What one box can be: a Numista type number, a PCGS cert, or a name. */
type Lookup =
  | { kind: "numista"; id: number }
  | { kind: "cert"; cert: string }
  | { kind: "search"; q: string };

/** "N# 1489", "n1489", or up to six digits is a Numista type; seven or more
 * digits (dashes allowed) is a PCGS cert; anything else is a name to search. */
export function readLookup(input: string): Lookup | null {
  const q = input.trim();
  if (!q) return null;
  const numista = q.match(/^n#?\s*(\d+)$/i);
  if (numista) return { kind: "numista", id: Number(numista[1]) };
  const digits = q.replace(/-/g, "");
  if (/^\d+$/.test(digits)) {
    return digits.length >= 7 ? { kind: "cert", cert: digits } : { kind: "numista", id: Number(digits) };
  }
  return { kind: "search", q };
}

const CATEGORY: Record<ItemType, "coin" | "banknote" | "exonumia"> = {
  coin: "coin",
  note: "banknote",
  bullion: "exonumia",
};

/** Kept from one piece to the next: how and where a batch was bought. */
const SHARED: (keyof FormState)[] = [
  "type",
  "currency",
  "acquisition_date",
  "acquired_from",
  "storage_location",
  "tags",
];

interface Added {
  id: string;
  label: string;
  grade: string | null;
}

export default function QuickAdd() {
  const navigate = useNavigate();
  const [form, setForm] = useState<FormState>({ ...EMPTY });
  const [refs, setRefs] = useState<CatalogRef[]>([]);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<NumistaSearchResult[] | null>(null);
  const [issues, setIssues] = useState<NumistaIssue[]>([]);
  const [source, setSource] = useState<string | null>(null);
  const [filled, setFilled] = useState<string[]>([]);
  const [grades, setGrades] = useState<Grade[]>([]);
  const [keys, setKeys] = useState<{ numista: boolean; pcgs: boolean } | null>(null);
  const [busy, setBusy] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [added, setAdded] = useState<Added[]>([]);
  const [lookupKey, setLookupKey] = useState(0);

  useEffect(() => {
    api
      .getSettings()
      .then((s) =>
        setKeys({
          numista: s.sources.some((x) => x.key === "numista" && x.configured),
          pcgs: s.sources.some((x) => x.key === "pcgs" && x.configured),
        }),
      )
      .catch(() => setKeys({ numista: false, pcgs: false }));
  }, []);

  useEffect(() => {
    api.listGrades(gradeScaleFor(form.type)).then(setGrades).catch(() => setGrades([]));
  }, [form.type]);

  const set = (field: keyof FormState) => (value: string) =>
    setForm((f) => ({ ...f, [field]: value }));

  function addRefs(newRefs: CatalogRef[]) {
    if (newRefs.length) setRefs((rs) => [...rs, ...newRefs]);
  }

  async function lookUp() {
    const lookup = readLookup(query);
    if (!lookup) return;
    setError(null);
    setResults(null);
    if (lookup.kind !== "cert" && keys && !keys.numista) {
      setError("Looking up by name or Numista number needs a Numista key in Settings, Pricing.");
      return;
    }
    if (lookup.kind === "cert" && keys && !keys.pcgs) {
      setError("Looking up a PCGS cert needs a PCGS token in Settings, Pricing.");
      return;
    }
    setBusy(true);
    try {
      if (lookup.kind === "search") {
        const found = await api.numistaSearch(lookup.q, CATEGORY[form.type]);
        setResults(found.results);
        if (found.results.length === 0) setError(`Numista has nothing called "${lookup.q}" here.`);
      } else if (lookup.kind === "numista") {
        await applyType(lookup.id);
      } else {
        const [found, sheldon] = await Promise.all([api.pcgsCert(lookup.cert), api.listGrades("sheldon")]);
        const result = fillFromCert(form, refs, found, sheldon);
        setForm(result.next);
        addRefs(result.newRefs);
        setFilled(result.filled);
        setIssues([]);
        setSource(`PCGS cert ${found.cert}${found.name ? `, ${found.name}` : ""}`);
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function applyType(typeId: number) {
    const found = await api.numistaType(typeId);
    const result = fillFromNumista(form, refs, found);
    setForm(result.next);
    addRefs(result.newRefs);
    setFilled(result.filled);
    setIssues(found.issues);
    setResults(null);
    setSource(`${found.title} (N# ${found.type_id})`);
  }

  async function pickResult(typeId: number) {
    setBusy(true);
    setError(null);
    try {
      await applyType(typeId);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  function pickIssue(issue: NumistaIssue) {
    setForm((f) => issueFields(f, issue));
  }

  function reset(keep: FormState) {
    const next: FormState = { ...EMPTY };
    for (const key of SHARED) (next as Record<string, unknown>)[key] = keep[key];
    setForm(next);
    setRefs([]);
    setQuery("");
    setResults(null);
    setIssues([]);
    setSource(null);
    setFilled([]);
    setLookupKey((k) => k + 1); // remounts the box, which focuses it
  }

  async function save(after: "another" | "open" | "edit") {
    setError(null);
    if (!form.country.trim() || !form.denomination.trim()) {
      setError("A piece needs at least a country and a denomination. Look it up, or type them in.");
      return;
    }
    setSaving(true);
    try {
      const saved = await api.createItem(toPayload(form, refs, []));
      if (after === "open") navigate(`/collection/${saved.id}`);
      else if (after === "edit") navigate(`/items/${saved.id}/edit`);
      else {
        setAdded((list) => [
          { id: saved.id, label: titleOf(form), grade: grades.find((g) => String(g.id) === form.grade_id)?.code ?? null },
          ...list,
        ]);
        reset(form);
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    void save("another");
  }

  const kept = useMemo(
    () =>
      [
        form.acquisition_date && form.acquisition_date,
        form.acquired_from && `from ${form.acquired_from}`,
        form.storage_location && `in ${form.storage_location}`,
        form.tags && `tagged ${form.tags}`,
      ].filter(Boolean) as string[],
    [form.acquisition_date, form.acquired_from, form.storage_location, form.tags],
  );

  const onBoxKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.preventDefault();
      void lookUp();
    }
  };

  return (
    <div className="quick-add">
      <div className="qa-main">
        <div className="detail-header">
          <h1>Add a piece</h1>
          <div className="spacer" />
          <Link to="/items/run" title="One item per date and mint of a type">Add a run</Link>
          <Link to="/items/new" title="Every field, on one form">Full form</Link>
        </div>

        <div className="qa-lookup">
          <div className="qa-types" role="radiogroup" aria-label="What it is">
            {(["coin", "note", "bullion"] as ItemType[]).map((t) => (
              <button
                key={t}
                type="button"
                role="radio"
                aria-checked={form.type === t}
                className={form.type === t ? "active" : undefined}
                onClick={() => setForm((f) => ({ ...f, type: t, grade_id: "" }))}
              >
                {TYPE_INFO[t].one}
              </button>
            ))}
          </div>
          <div className="qa-box">
            <input
              key={lookupKey}
              autoFocus
              id="qa-lookup"
              aria-label="Look up a piece"
              aria-describedby="qa-lookup-hint"
              placeholder="1932 washington quarter"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={onBoxKey}
            />
            <button type="button" className="primary" disabled={busy || !query.trim()} onClick={lookUp}>
              {busy ? "Looking…" : "Look up"}
            </button>
          </div>
          <p id="qa-lookup-hint" className="muted qa-hint">
            A name searches Numista; a Numista number (N# 1489) or a PCGS cert number fills the piece
            straight away.
            {keys && !keys.numista && !keys.pcgs && (
              <>
                {" "}No lookup key is set up yet, so type the piece in below, or add a key in{" "}
                <Link to="/settings/pricing">Settings, Pricing</Link>.
              </>
            )}
          </p>
        </div>

        {results && results.length > 0 && (
          <ul className="qa-results" aria-label="Numista matches">
            {results.slice(0, 8).map((r) => (
              <li key={r.type_id}>
                <button type="button" onClick={() => pickResult(r.type_id)} disabled={busy}>
                  <span className="t">{r.title}</span>
                  <span className="s">
                    {[
                      r.object_type,
                      r.issuer,
                      r.min_year != null
                        ? `${r.min_year}${r.max_year && r.max_year !== r.min_year ? `–${r.max_year}` : ""}`
                        : null,
                      `N# ${r.type_id}`,
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}

        {source && (
          <div className="qa-source">
            <p>
              <b>{source}</b>
            </p>
            {filled.length > 0 && (
              <p className="qa-filled">
                <span className="muted">Filled:</span>
                {filled.map((f) => (
                  <span className="chip" key={f}>{f}</span>
                ))}
              </p>
            )}
            {issues.length > 1 && (
              <div className="qa-issues">
                <span className="muted">Issue{issues.some((i) => i.owned) ? " (owned ones struck through)" : ""}:</span>
                {issues.slice(0, 60).map((issue, index) => {
                  const label = [ndYearLabel(issue), issue.mint_letter].filter(Boolean).join(" ");
                  const on =
                    form.year === (issue.year != null ? String(issue.year) : "") &&
                    form.mint_mark === (issue.mint_letter ?? "") &&
                    form.year_nd === issue.nd;
                  return (
                    <button
                      type="button"
                      key={index}
                      className={`issue${on ? " on" : ""}${issue.owned ? " owned" : ""}`}
                      aria-pressed={on}
                      title={issue.comment ?? (issue.mintage != null ? `mintage ${issue.mintage.toLocaleString()}` : undefined)}
                      onClick={() => pickIssue(issue)}
                    >
                      {label || "ND"}
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        )}

        <form className="qa-form" onSubmit={submit}>
          <fieldset className="plain-fieldset">
            <legend className="qa-legend">The piece</legend>
            <div className="qa-grid">
              <label className="field">
                Country
                <input value={form.country} onChange={(e) => set("country")(e.target.value)} />
              </label>
              <label className="field">
                {form.type === "bullion" ? "Product name" : "Denomination"}
                <input value={form.denomination} onChange={(e) => set("denomination")(e.target.value)} />
              </label>
              <label className="field">
                Year
                <input inputMode="numeric" value={form.year} onChange={(e) => set("year")(e.target.value)} />
              </label>
              {form.type === "coin" && (
                <label className="field">
                  Mint mark
                  <input value={form.mint_mark} onChange={(e) => set("mint_mark")(e.target.value)} />
                </label>
              )}
            </div>
          </fieldset>

          <fieldset className="plain-fieldset">
            <legend className="qa-legend">Yours</legend>
            <div className="qa-grid">
              {form.type !== "bullion" && (
                <label className="field">
                  Grade
                  <select value={form.grade_id} onChange={(e) => set("grade_id")(e.target.value)}>
                    <option value="">Ungraded</option>
                    {grades.map((g) => (
                      <option key={g.id} value={g.id}>
                        {g.code} ({g.label})
                      </option>
                    ))}
                  </select>
                </label>
              )}
              <label className="field">
                Paid
                <span className="qa-money">
                  <input
                    type="number"
                    step="0.01"
                    min={0}
                    inputMode="decimal"
                    value={form.acquisition_price}
                    onChange={(e) => set("acquisition_price")(e.target.value)}
                  />
                  <input
                    aria-label="Currency"
                    className="qa-currency"
                    maxLength={3}
                    value={form.currency}
                    onChange={(e) => set("currency")(e.target.value.toUpperCase())}
                  />
                </span>
              </label>
              <label className="field">
                Quantity
                <input type="number" min={1} step={1} value={form.quantity}
                  onChange={(e) => set("quantity")(e.target.value)} />
              </label>
              <label className="field">
                Bought on
                <input type="date" value={form.acquisition_date}
                  onChange={(e) => set("acquisition_date")(e.target.value)} />
              </label>
              <label className="field">
                From
                <input value={form.acquired_from} placeholder="coin show"
                  onChange={(e) => set("acquired_from")(e.target.value)} />
              </label>
              <label className="field">
                Storage
                <input value={form.storage_location} placeholder="Safe"
                  onChange={(e) => set("storage_location")(e.target.value)} />
              </label>
              <label className="field">
                Tags
                <input value={form.tags} placeholder="silver, key date"
                  onChange={(e) => set("tags")(e.target.value)} />
              </label>
            </div>
          </fieldset>

          <DuplicateWarning
            country={form.country}
            denomination={form.denomination}
            year={form.year}
            yearNd={form.year_nd}
            mintMark={form.mint_mark}
            certNumber={form.cert_number}
            refs={refs}
          />

          {error && <p className="error" role="alert">{error}</p>}

          <div className="qa-actions">
            <button type="submit" className="primary" disabled={saving}>
              {saving ? "Saving…" : "Save and add another"}
            </button>
            <button type="button" disabled={saving} onClick={() => save("open")}>Save</button>
            <button type="button" disabled={saving} onClick={() => save("edit")}>
              Save and fill in everything
            </button>
            {form.acquisition_price && (
              <span className="muted">
                {money(Number(form.acquisition_price), form.currency)}
                {Number(form.quantity) > 1 ? ` for ${form.quantity}` : ""}
              </span>
            )}
          </div>
          {kept.length > 0 && (
            <p className="muted qa-hint">Kept for the next piece: {kept.join(", ")}.</p>
          )}
        </form>
      </div>

      <aside className="qa-session" aria-label="Added this visit">
        <h2>Added this visit</h2>
        {added.length === 0 ? (
          <p className="muted">Each piece you save lands here, and the form stays ready for the next.</p>
        ) : (
          <ul>
            {added.map((a) => (
              <li key={a.id}>
                <Link to={`/collection/${a.id}`}>{a.label}</Link>
                {a.grade && <span className="grade">{a.grade}</span>}
              </li>
            ))}
          </ul>
        )}
      </aside>
    </div>
  );
}

function titleOf(form: FormState): string {
  if (form.type === "bullion") return [form.issuer || form.country, form.denomination].filter(Boolean).join(" ");
  const year = form.year_nd ? (form.year ? `ND (${form.year})` : "ND") : form.year;
  return [`${year}${form.mint_mark ? `-${form.mint_mark}` : ""}`, form.denomination, form.country]
    .filter((p) => p && p.trim())
    .join(" ");
}
