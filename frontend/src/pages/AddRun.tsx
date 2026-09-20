import { FormEvent, KeyboardEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api, Grade, gradeScaleFor, NumistaSearchResult, NumistaType, SetInfo } from "../api";

const issueKey = (i: { year: number | null; mint_letter: string | null }) =>
  `${i.year}|${(i.mint_letter ?? "").trim().toLowerCase()}`;

/** Add a run: pick a Numista type, tick its issues, and get one item per
 * date and mint mark: a fifty-coin run in one form instead of fifty. */
export default function AddRun() {
  const [configured, setConfigured] = useState<boolean | null>(null);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<NumistaSearchResult[] | null>(null);
  const [found, setFound] = useState<NumistaType | null>(null);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [grades, setGrades] = useState<Grade[]>([]);
  const [sets, setSets] = useState<SetInfo[]>([]);
  const [shared, setShared] = useState({
    status: "owned",
    grade_id: "",
    acquisition_date: "",
    acquisition_price: "",
    currency: "USD",
    acquired_from: "",
    storage_location: "",
    set_id: "",
    tags: "",
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<React.ReactNode>(null);

  useEffect(() => {
    api
      .getSettings()
      .then((s) => setConfigured(s.sources.some((x) => x.key === "numista" && x.configured)))
      .catch(() => setConfigured(false));
    api.listSets().then(setSets).catch(() => setSets([]));
  }, []);

  const itemType = found?.fields.type === "note" ? "note" : "coin";
  useEffect(() => {
    api.listGrades(gradeScaleFor(itemType)).then(setGrades).catch(() => setGrades([]));
  }, [itemType]);

  // Dated issues only, one per year and mint mark.
  const issues = (found?.issues ?? []).filter(
    (issue, index, all) =>
      issue.year != null && all.findIndex((other) => issueKey(other) === issueKey(issue)) === index,
  );

  async function load(typeId: number) {
    setBusy(true);
    setError(null);
    setNote(null);
    try {
      const type = await api.numistaType(typeId);
      setFound(type);
      setResults(null);
      setPicked(new Set());
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function lookUp() {
    const q = query.trim();
    if (!q) return;
    const direct = q.match(/^(?:n#?\s*)?(\d+)$/i);
    if (direct) return load(Number(direct[1]));
    setBusy(true);
    setError(null);
    try {
      setResults((await api.numistaSearch(q, "coin")).results);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.preventDefault();
      lookUp();
    }
  };

  const toggle = (key: string) =>
    setPicked((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  const field = (name: keyof typeof shared) => ({
    value: shared[name],
    onChange: (e: { target: { value: string } }) =>
      setShared((s) => ({ ...s, [name]: e.target.value })),
  });

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!found || picked.size === 0) return;
    setBusy(true);
    setError(null);
    setNote(null);
    try {
      const chosen = issues.filter((i) => picked.has(issueKey(i)));
      const result = await api.addRun({
        type_id: found.type_id,
        issues: chosen.map((i) => ({
          year: i.year!,
          mint_mark: i.mint_letter,
          mintage: i.mintage,
        })),
        shared: {
          status: shared.status as "owned" | "sold" | "wishlist",
          grade_id: shared.grade_id === "" ? null : Number(shared.grade_id),
          acquisition_date: shared.acquisition_date || null,
          acquisition_price: shared.acquisition_price === "" ? null : Number(shared.acquisition_price),
          currency: shared.currency.trim().toUpperCase() || "USD",
          acquired_from: shared.acquired_from.trim() || null,
          storage_location: shared.storage_location.trim() || null,
          set_id: shared.set_id === "" ? null : Number(shared.set_id),
          tags: shared.tags.split(",").map((t) => t.trim()).filter(Boolean),
        },
      });
      setNote(
        <>
          Added {result.created} item{result.created === 1 ? "" : "s"}
          {result.skipped > 0 && `, skipped ${result.skipped} already owned`}.{" "}
          <Link to={`/collection?q=${encodeURIComponent(`N#${found.type_id}`)}`}>See them</Link>.
        </>,
      );
      await load(found.type_id); // refresh the owned flags
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function makeChecklist() {
    if (!found) return;
    setBusy(true);
    setError(null);
    try {
      const made = await api.generateChecklist({ source: "numista", type_id: found.type_id });
      setNote(
        <>
          Created the checklist “{made.name}”: {made.filled} of {made.total} filled.{" "}
          <Link to="/checklists">Open checklists</Link>.
        </>,
      );
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const free = issues.filter((i) => !i.owned);

  return (
    <>
      <div className="detail-header">
        <h1>Add a run</h1>
        <div className="spacer" />
        <Link className="button" to="/collection">Back to the collection</Link>
      </div>
      {error && <p className="error">{error}</p>}
      {note && <p className="gain">{note}</p>}

      <div className="card">
        <h2>1 · The type</h2>
        {configured === false ? (
          <p className="muted" style={{ margin: 0 }}>
            Adding a run reads a type's dates and mints from Numista. Add a Numista API key in{" "}
            <Link to="/settings">Settings</Link> first.
          </p>
        ) : (
          <>
            <div className="estimate-form" style={{ marginTop: 0 }}>
              <label className="field">
                Numista number or search
                <input value={query} placeholder='e.g. N#1493, or "washington quarter"'
                  onChange={(e) => setQuery(e.target.value)} onKeyDown={onKey} />
              </label>
              <button type="button" disabled={busy || !query.trim()} onClick={lookUp}>
                {busy ? "Looking up…" : "Look up"}
              </button>
            </div>
            {results &&
              (results.length === 0 ? (
                <p className="muted">No matches on Numista.</p>
              ) : (
                <ul className="numista-results">
                  {results.map((r) => (
                    <li key={r.type_id}>
                      {r.thumbnail ? <img src={r.thumbnail} alt="" loading="lazy" /> : <span />}
                      <div>
                        <b>{r.title}</b>
                        <div className="muted">
                          {[r.issuer, r.min_year, `N#${r.type_id}`].filter(Boolean).join(" · ")}
                        </div>
                      </div>
                      <button type="button" disabled={busy} onClick={() => load(r.type_id)}>
                        Use
                      </button>
                    </li>
                  ))}
                </ul>
              ))}
            {found && (
              <p style={{ marginBottom: 0 }}>
                <b>{found.title}</b>{" "}
                <span className="muted">
                  N#{found.type_id} · {String(found.fields.country ?? "")}{" "}
                  {String(found.fields.denomination ?? "")}
                  {found.fields.composition ? ` · ${found.fields.composition}` : ""}
                </span>
              </p>
            )}
          </>
        )}
      </div>

      {found && (
        <form onSubmit={submit}>
          <div className="card">
            <h2>2 · The dates and mints you have</h2>
            {issues.length === 0 ? (
              <p className="muted">Numista lists no dated issues for this type.</p>
            ) : (
              <>
                <div className="estimate-form" style={{ marginTop: 0 }}>
                  <button type="button"
                    onClick={() => setPicked(new Set(free.map(issueKey)))}>
                    Select all {free.length}
                  </button>
                  <button type="button" onClick={() => setPicked(new Set())}>Clear</button>
                  <span className="muted" style={{ alignSelf: "center" }}>
                    {picked.size} selected
                    {issues.length > free.length && ` · ${issues.length - free.length} already owned`}
                  </span>
                </div>
                <div className="slot-grid">
                  {issues.map((issue) => {
                    const key = issueKey(issue);
                    return (
                      <label key={key}
                        className={`slot${issue.owned ? " filled" : ""}`}
                        title={[
                          issue.mintage != null ? `mintage ${issue.mintage.toLocaleString()}` : null,
                          issue.comment,
                          issue.owned ? "already owned" : null,
                        ].filter(Boolean).join(" · ")}>
                        <input type="checkbox" checked={picked.has(key)} disabled={issue.owned}
                          onChange={() => toggle(key)} />
                        {issue.year}
                        {issue.mint_letter ? `-${issue.mint_letter}` : ""}
                        {issue.owned && <span className="muted"> ✓</span>}
                      </label>
                    );
                  })}
                </div>
              </>
            )}
          </div>

          <div className="card">
            <h2>3 · What they have in common</h2>
            <div className="item-form">
              <label className="field">
                Status
                <select {...field("status")}>
                  <option value="owned">Owned</option>
                  <option value="wishlist">Wishlist</option>
                </select>
              </label>
              <label className="field">
                Grade (each)
                <select {...field("grade_id")}>
                  <option value="">ungraded (set later)</option>
                  {grades.map((g) => (
                    <option key={g.id} value={g.id}>{g.code}: {g.label}</option>
                  ))}
                </select>
              </label>
              <label className="field">
                Acquired on
                <input type="date" {...field("acquisition_date")} />
              </label>
              <label className="field">
                Price paid (each)
                <input type="number" step="0.01" min="0" {...field("acquisition_price")} />
              </label>
              <label className="field">
                Currency
                <input maxLength={3} {...field("currency")} />
              </label>
              <label className="field">
                Acquired from
                <input placeholder="dealer, show, roll…" {...field("acquired_from")} />
              </label>
              <label className="field">
                Storage location
                <input placeholder="album, box…" {...field("storage_location")} />
              </label>
              <label className="field">
                Set / lot
                <select {...field("set_id")}>
                  <option value="">none</option>
                  {sets.map((s) => (
                    <option key={s.id} value={s.id}>{s.name}</option>
                  ))}
                </select>
              </label>
              <label className="field">
                Tags (comma-separated)
                <input placeholder="e.g. album run" {...field("tags")} />
              </label>
            </div>
            <p className="muted">
              Each item gets the type's country, denomination, composition, weight, and catalogue
              references, plus its own year, mint mark, and mintage. Grades and prices that differ
              can be fixed afterwards, one item or several at a time from the collection.
            </p>
            <div className="actions">
              <button className="primary" type="submit" disabled={busy || picked.size === 0}>
                {busy ? "Adding…" : `Add ${picked.size} item${picked.size === 1 ? "" : "s"}`}
              </button>
              <button type="button" disabled={busy || issues.length === 0} onClick={makeChecklist}
                title="A checklist with one slot per issue, filled automatically by what you own">
                Make a checklist of this type
              </button>
            </div>
          </div>
        </form>
      )}
    </>
  );
}
