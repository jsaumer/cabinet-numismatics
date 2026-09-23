import { KeyboardEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api, CatalogRef, ItemType, ndYearLabel, NumistaIssue, NumistaSearchResult } from "../../api";
import { FormState, TextField } from "./model";

// Fields a Numista lookup can fill, with how the "filled …" message names them.
const NUMISTA_FIELDS: Partial<Record<TextField, string>> = {
  country: "country",
  denomination: "denomination",
  year: "year",
  series: "series",
  composition: "composition",
  weight_g: "weight",
  fineness: "fineness",
  diameter_mm: "diameter",
  thickness_mm: "thickness",
  width_mm: "width",
  height_mm: "height",
  edge: "edge",
  shape: "shape",
  printer: "printer",
  watermark: "watermark",
  demonetized_on: "demonetised on",
  issuer: "issuer",
  mintage: "mintage",
};

const yearSpan = (r: { min_year: number | null; max_year: number | null }) =>
  r.min_year == null
    ? ""
    : r.max_year == null || r.max_year === r.min_year
      ? String(r.min_year)
      : `${r.min_year}–${r.max_year}`;

/** The item form's "Fill from Numista" card. Fills only empty fields and
 * hands the new form state, plus any catalogue references the form doesn't
 * have yet, back through `onApply`. */
export function NumistaFill({
  form,
  refs,
  onApply,
}: {
  form: FormState;
  refs: CatalogRef[];
  onApply: (next: FormState, newRefs: CatalogRef[]) => void;
}) {
  const [configured, setConfigured] = useState<boolean | null>(null);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<NumistaSearchResult[] | null>(null);
  const [issues, setIssues] = useState<NumistaIssue[]>([]);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .getSettings()
      .then((s) => setConfigured(s.sources.some((x) => x.key === "numista" && x.configured)))
      .catch(() => setConfigured(false));
  }, []);

  async function lookUp() {
    const q = query.trim();
    if (!q) return;
    const direct = q.match(/^(?:n#?\s*)?(\d+)$/i);
    if (direct) {
      await apply(Number(direct[1]));
      return;
    }
    setBusy(true);
    setError(null);
    setNote(null);
    try {
      const found = await api.numistaSearch(q, form.type === "note" ? "banknote" : "coin");
      setResults(found.results);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function apply(typeId: number) {
    setBusy(true);
    setError(null);
    setNote(null);
    try {
      const found = await api.numistaType(typeId);
      const next: FormState = { ...form };
      const filled: string[] = [];
      if (found.fields.type && found.fields.type !== form.type) {
        next.type = found.fields.type as ItemType;
        next.grade_id = "";
        next.designations = [];
        if (next.type === "note" && next.strike === "proof") next.strike = "business";
        filled.push(`type (${next.type})`);
      }
      for (const [field, label] of Object.entries(NUMISTA_FIELDS) as [TextField, string][]) {
        const value = found.fields[field];
        if (value == null || value === "" || String(next[field]).trim() !== "") continue;
        next[field] = String(value) as never;
        filled.push(label);
      }
      // Every issue of the type is undated, and the piece isn't marked ND yet.
      if (found.fields.year_nd === true && !next.year_nd) {
        next.year_nd = true;
        filled.push("ND");
      }
      // An issue matching a year already entered supplies its mint mark and mintage.
      const year = Number(next.year);
      const issue = found.issues.find(
        (i) =>
          i.year === year &&
          (!next.mint_mark || (i.mint_letter ?? "").toLowerCase() === next.mint_mark.toLowerCase()),
      );
      if (issue?.mintage != null && next.mintage === "") {
        next.mintage = String(issue.mintage);
        filled.push("mintage");
      }
      const known = new Set(refs.map((r) => `${r.catalog.trim().toLowerCase()}|${r.ref_code.trim()}`));
      const newRefs = found.catalog_refs.filter((r) => !known.has(`${r.catalog}|${r.ref_code}`));
      if (newRefs.length) {
        filled.push(`${newRefs.length} catalog reference${newRefs.length > 1 ? "s" : ""}`);
      }
      onApply(next, newRefs);
      setResults(null);
      setIssues(found.issues);
      setNote(
        filled.length
          ? `Filled ${filled.join(", ")} from ${found.title} (N#${found.type_id}).`
          : `Nothing to fill from ${found.title} (N#${found.type_id}): those fields are already set.`,
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  function pickIssue(index: string) {
    const issue = issues[Number(index)];
    if (!issue) return;
    onApply(
      {
        ...form,
        year: issue.year != null ? String(issue.year) : issue.nd ? "" : form.year,
        year_nd: issue.nd,
        mint_mark: issue.mint_letter ?? "",
        mintage: issue.mintage != null ? String(issue.mintage) : form.mintage,
      },
      [],
    );
    setNote(
      `Set the issue: ${[ndYearLabel(issue), issue.mint_letter].filter(Boolean).join(" ")}` +
        (issue.mintage != null ? `, mintage ${issue.mintage.toLocaleString()}` : "") +
        ".",
    );
  }

  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.preventDefault(); // don't submit the item form
      lookUp();
    }
  };

  return (
    <div className="card">
      <h2>Fill from Numista</h2>
      {configured === false ? (
        <p className="muted" style={{ margin: 0 }}>
          Add a Numista API key in <Link to="/settings/pricing">Settings</Link> to fill items in from
          the Numista catalogue.
        </p>
      ) : (
        <>
          <div className="estimate-form" style={{ marginTop: 0 }}>
            <label className="field">
              Numista number or search
              <input
                value={query}
                placeholder='e.g. N#1493, or "morgan dollar"'
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={onKey}
              />
            </label>
            <button type="button" disabled={busy || !query.trim()} onClick={lookUp}>
              {busy ? "Looking up…" : "Look up"}
            </button>
            {issues.length > 1 && (
              <label className="field">
                Issue
                <select value="" onChange={(e) => pickIssue(e.target.value)}>
                  <option value="">choose year / mint…</option>
                  {issues.map((issue, i) => (
                    <option key={i} value={i}>
                      {[ndYearLabel(issue), issue.mint_letter].filter(Boolean).join(" ")}
                      {issue.reference ? ` · ${issue.reference}` : ""}
                      {issue.mintage != null ? ` · ${issue.mintage.toLocaleString()} minted` : ""}
                      {issue.comment ? ` (${issue.comment})` : ""}
                    </option>
                  ))}
                </select>
              </label>
            )}
          </div>
          {error && <p className="error">{error}</p>}
          {note && <p className="muted">{note}</p>}
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
                        {[r.issuer, yearSpan(r), `N#${r.type_id}`].filter(Boolean).join(" · ")}
                      </div>
                    </div>
                    <button type="button" disabled={busy} onClick={() => apply(r.type_id)}>
                      Use
                    </button>
                  </li>
                ))}
              </ul>
            ))}
          <p className="muted" style={{ marginBottom: 0 }}>
            Fills only fields that are still empty, and adds the catalogue references. Each
            lookup uses Numista requests from your quota; results are cached for 30 days.
          </p>
        </>
      )}
    </div>
  );
}
