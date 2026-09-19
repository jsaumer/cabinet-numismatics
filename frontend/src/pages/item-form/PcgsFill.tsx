import { KeyboardEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api, CatalogRef, Grade } from "../../api";
import { FormState, TextField } from "./model";

// Fields a cert lookup can fill, with how the "filled …" message names them.
const CERT_FIELDS: Partial<Record<TextField, string>> = {
  country: "country",
  denomination: "denomination",
  year: "year",
  mint_mark: "mint mark",
  series: "series",
  variety: "variety",
  composition: "composition",
  weight_g: "weight",
  diameter_mm: "diameter",
  edge: "edge",
  mintage: "mintage",
  cert_service: "cert service",
  cert_number: "cert number",
};

/** The item form's "Fill from a PCGS cert" card. Fills only empty fields —
 * the grade included, when none is set — and hands the new form state and
 * any new catalogue references back through `onApply`. */
export function PcgsFill({
  form,
  refs,
  onApply,
}: {
  form: FormState;
  refs: CatalogRef[];
  onApply: (next: FormState, newRefs: CatalogRef[]) => void;
}) {
  const [configured, setConfigured] = useState<boolean | null>(null);
  const [cert, setCert] = useState("");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .getSettings()
      .then((s) => setConfigured(s.sources.some((x) => x.key === "pcgs" && x.configured)))
      .catch(() => setConfigured(false));
  }, []);

  async function fill() {
    const number = cert.replace(/\D/g, "");
    if (!number) return;
    setBusy(true);
    setError(null);
    setNote(null);
    try {
      const [found, sheldon] = await Promise.all([
        api.pcgsCert(number),
        api.listGrades("sheldon") as Promise<Grade[]>,
      ]);
      const next: FormState = { ...form };
      const filled: string[] = [];
      if (form.type !== "coin") {
        next.type = "coin";
        next.grade_id = "";
        next.designations = [];
        filled.push("type (coin)");
      }
      for (const [field, label] of Object.entries(CERT_FIELDS) as [TextField, string][]) {
        const value = found.fields[field];
        if (value == null || value === "" || String(next[field]).trim() !== "") continue;
        next[field] = String(value) as never;
        filled.push(label);
      }
      if (found.grade && next.grade_id === "") {
        const grade = sheldon.find((g) => g.rank === found.grade!.rank);
        if (grade) {
          next.grade_id = String(grade.id);
          next.strike = found.grade.strike;
          next.grade_plus = found.grade.plus;
          next.designations = found.grade.designations;
          filled.push(
            `grade (${found.grade.strike === "proof" ? "PR" : found.grade.strike === "specimen" ? "SP" : "MS"}-${found.grade.rank}${found.grade.plus ? "+" : ""}${found.grade.designations.length ? " " + found.grade.designations.join(" ") : ""})`,
          );
        }
      }
      const known = new Set(refs.map((r) => `${r.catalog.trim().toLowerCase()}|${r.ref_code.trim()}`));
      const newRefs = found.catalog_refs.filter((r) => !known.has(`${r.catalog}|${r.ref_code}`));
      if (newRefs.length) filled.push("PCGS number");
      onApply(next, newRefs);
      const pop =
        found.population != null
          ? ` PCGS has graded ${found.population.toLocaleString()} at this grade` +
            (found.pop_higher != null ? ` and ${found.pop_higher.toLocaleString()} higher.` : ".")
          : "";
      setNote(
        (filled.length
          ? `Filled ${filled.join(", ")} from cert ${found.cert}${found.name ? ` (${found.name})` : ""}.`
          : `Nothing to fill from cert ${found.cert} — those fields are already set.`) + pop,
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.preventDefault(); // don't submit the item form
      fill();
    }
  };

  return (
    <div className="card">
      <h2>Fill from a PCGS cert</h2>
      {configured === false ? (
        <p className="muted" style={{ margin: 0 }}>
          Add a PCGS API token in <Link to="/settings">Settings</Link> to fill a slabbed coin in
          from its cert number.
        </p>
      ) : (
        <>
          <div className="estimate-form" style={{ marginTop: 0 }}>
            <label className="field">
              PCGS cert number
              <input
                value={cert}
                inputMode="numeric"
                placeholder="the number on the label"
                onChange={(e) => setCert(e.target.value)}
                onKeyDown={onKey}
              />
            </label>
            <button type="button" disabled={busy || !cert.replace(/\D/g, "")} onClick={fill}>
              {busy ? "Looking up…" : "Fill in"}
            </button>
          </div>
          {error && <p className="error">{error}</p>}
          {note && <p className="muted">{note}</p>}
          <p className="muted" style={{ marginBottom: 0 }}>
            Fills the coin, its grade and designations, the cert, and the PCGS number — empty
            fields only. One request from the 1,000/day quota; pricing the item afterwards reuses
            the answer.
          </p>
        </>
      )}
    </div>
  );
}
