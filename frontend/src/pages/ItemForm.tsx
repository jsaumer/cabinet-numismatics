import { FormEvent, KeyboardEvent, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import {
  api,
  CacSticker,
  CatalogRef,
  Grade,
  gradeScaleFor,
  ItemPayload,
  ItemStatus,
  ItemType,
  NumistaIssue,
  NumistaSearchResult,
  SetInfo,
  Strike,
} from "../api";

const EMPTY = {
  type: "coin" as ItemType,
  status: "owned" as ItemStatus,
  country: "",
  denomination: "",
  year: "",
  mint_mark: "",
  series: "",
  variety: "",
  strike: "business" as Strike,
  set_id: "",
  composition: "",
  weight_g: "",
  fineness: "",
  diameter_mm: "",
  thickness_mm: "",
  edge: "",
  shape: "",
  mintage: "",
  grade_id: "",
  grade_plus: false,
  grade_star: false,
  designations: [] as string[],
  grade_details: "",
  cac_sticker: "",
  cert_service: "",
  cert_number: "",
  serial_number: "",
  prefix_block: "",
  signatures: "",
  issuer: "",
  replacement_note: false,
  quantity: "1",
  acquisition_date: "",
  acquisition_price: "",
  acquisition_fees: "",
  currency: "USD",
  acquired_from: "",
  storage_location: "",
  sold_date: "",
  sold_price: "",
  sold_fees: "",
  sold_to: "",
  notes: "",
  tags: "",
};

type FormState = typeof EMPTY;
type TextField = {
  [K in keyof FormState]: FormState[K] extends string ? K : never;
}[keyof FormState];
type FlagField = "grade_plus" | "grade_star" | "replacement_note";

// Designations as grading services print them, with what each means.
const DESIGNATIONS: Record<ItemType, [string, string][]> = {
  coin: [
    ["PL", "Prooflike"],
    ["DMPL", "Deep mirror prooflike"],
    ["CAM", "Cameo"],
    ["DCAM", "Deep cameo"],
    ["UCAM", "Ultra cameo (NGC)"],
    ["RD", "Red — copper"],
    ["RB", "Red-brown — copper"],
    ["BN", "Brown — copper"],
    ["FB", "Full bands — Mercury dime"],
    ["FBL", "Full bell lines — Franklin half"],
    ["FH", "Full head — Standing Liberty quarter"],
    ["FS", "Full steps — Jefferson nickel"],
    ["FT", "Full torch — Roosevelt dime"],
  ],
  note: [["EPQ", "Exceptional paper quality (PMG)"]],
};

const PROBLEMS: Record<ItemType, string[]> = {
  coin: [
    "Cleaned", "Damaged", "Environmental damage", "Scratched", "Holed", "Repaired",
    "Tooled", "Altered surfaces", "Bent",
  ],
  note: ["Restoration", "Tears", "Annotations", "Stains", "Trimmed", "Pinholes"],
};

const EDGES = ["Reeded", "Plain", "Lettered", "Security", "Interrupted reeding"];
const SHAPES = ["Round", "Square", "Polygonal", "Scalloped", "Holed"];

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
  edge: "edge",
  shape: "shape",
  issuer: "issuer",
  mintage: "mintage",
};

const yearSpan = (r: { min_year: number | null; max_year: number | null }) =>
  r.min_year == null
    ? ""
    : r.max_year == null || r.max_year === r.min_year
      ? String(r.min_year)
      : `${r.min_year}–${r.max_year}`;

const opt = (v: string) => v.trim() || null;
const optNum = (v: string) => (v === "" ? null : Number(v));

function toPayload(
  form: FormState,
  refs: CatalogRef[],
  fields: { key: string; value: string }[],
): ItemPayload {
  const custom: Record<string, string> = {};
  for (const f of fields) {
    if (f.key.trim()) custom[f.key.trim()] = f.value;
  }
  const coin = form.type === "coin";
  const note = form.type === "note";
  const allowed = new Set(DESIGNATIONS[form.type].map(([code]) => code));
  const designations = form.designations.filter((d) => allowed.has(d));
  const sold = form.status === "sold";
  return {
    type: form.type,
    status: form.status,
    country: form.country.trim(),
    denomination: form.denomination.trim(),
    year: Number(form.year),
    mint_mark: opt(form.mint_mark),
    series: opt(form.series),
    variety: opt(form.variety),
    strike: form.strike,
    set_id: form.set_id === "" ? null : Number(form.set_id),
    custom_fields: Object.keys(custom).length ? custom : null,
    composition: opt(form.composition),
    weight_g: optNum(form.weight_g),
    fineness: optNum(form.fineness),
    diameter_mm: coin ? optNum(form.diameter_mm) : null,
    thickness_mm: coin ? optNum(form.thickness_mm) : null,
    edge: coin ? opt(form.edge) : null,
    shape: coin ? opt(form.shape) : null,
    mintage: optNum(form.mintage),
    grade_id: form.grade_id === "" ? null : Number(form.grade_id),
    grade_plus: form.grade_plus,
    grade_star: form.grade_star,
    designations: designations.length ? designations : null,
    grade_details: opt(form.grade_details),
    cac_sticker: coin && form.cac_sticker ? (form.cac_sticker as CacSticker) : null,
    cert_service: opt(form.cert_service),
    cert_number: opt(form.cert_number),
    serial_number: note ? opt(form.serial_number) : null,
    prefix_block: note ? opt(form.prefix_block) : null,
    signatures: note ? opt(form.signatures) : null,
    issuer: note ? opt(form.issuer) : null,
    replacement_note: note && form.replacement_note,
    quantity: Number(form.quantity),
    acquisition_date: form.acquisition_date || null,
    acquisition_price: optNum(form.acquisition_price),
    acquisition_fees: optNum(form.acquisition_fees),
    currency: form.currency.trim().toUpperCase(),
    acquired_from: opt(form.acquired_from),
    storage_location: opt(form.storage_location),
    sold_date: sold ? form.sold_date || null : null,
    sold_price: sold ? optNum(form.sold_price) : null,
    sold_fees: sold ? optNum(form.sold_fees) : null,
    sold_to: sold ? opt(form.sold_to) : null,
    notes: opt(form.notes),
    tags: form.tags.split(",").map((t) => t.trim()).filter(Boolean),
    catalog_refs: refs.filter((r) => r.catalog.trim() && r.ref_code.trim()),
  };
}

const str = (v: string | number | null | undefined) => (v == null ? "" : String(v));

export default function ItemForm() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [form, setForm] = useState<FormState>(EMPTY);
  const [refs, setRefs] = useState<CatalogRef[]>([]);
  const [customFields, setCustomFields] = useState<{ key: string; value: string }[]>([]);
  const [grades, setGrades] = useState<Grade[]>([]);
  const [sets, setSets] = useState<SetInfo[]>([]);
  const [countries, setCountries] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [savedNote, setSavedNote] = useState<string | null>(null);
  const [numistaConfigured, setNumistaConfigured] = useState<boolean | null>(null);
  const [numistaQuery, setNumistaQuery] = useState("");
  const [numistaResults, setNumistaResults] = useState<NumistaSearchResult[] | null>(null);
  const [numistaIssues, setNumistaIssues] = useState<NumistaIssue[]>([]);
  const [numistaBusy, setNumistaBusy] = useState(false);
  const [numistaNote, setNumistaNote] = useState<string | null>(null);
  const [numistaError, setNumistaError] = useState<string | null>(null);

  useEffect(() => {
    api
      .getSettings()
      .then((s) => setNumistaConfigured(s.sources.some((x) => x.key === "numista" && x.configured)))
      .catch(() => setNumistaConfigured(false));
  }, []);

  useEffect(() => {
    api.listGrades(gradeScaleFor(form.type)).then(setGrades).catch(() => setGrades([]));
  }, [form.type]);

  async function lookUpNumista() {
    const query = numistaQuery.trim();
    if (!query) return;
    const direct = query.match(/^(?:n#?\s*)?(\d+)$/i);
    if (direct) {
      await applyNumista(Number(direct[1]));
      return;
    }
    setNumistaBusy(true);
    setNumistaError(null);
    setNumistaNote(null);
    try {
      const found = await api.numistaSearch(query, form.type === "note" ? "banknote" : "coin");
      setNumistaResults(found.results);
    } catch (e) {
      setNumistaError((e as Error).message);
    } finally {
      setNumistaBusy(false);
    }
  }

  async function applyNumista(typeId: number) {
    setNumistaBusy(true);
    setNumistaError(null);
    setNumistaNote(null);
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
        setRefs((rs) => [...rs.filter((r) => r.catalog.trim() || r.ref_code.trim()), ...newRefs]);
        filled.push(`${newRefs.length} catalog reference${newRefs.length > 1 ? "s" : ""}`);
      }
      setForm(next);
      setNumistaResults(null);
      setNumistaIssues(found.issues);
      setNumistaNote(
        filled.length
          ? `Filled ${filled.join(", ")} from ${found.title} (N#${found.type_id}).`
          : `Nothing to fill from ${found.title} (N#${found.type_id}) — those fields are already set.`,
      );
    } catch (e) {
      setNumistaError((e as Error).message);
    } finally {
      setNumistaBusy(false);
    }
  }

  function pickIssue(index: string) {
    const issue = numistaIssues[Number(index)];
    if (!issue) return;
    setForm((f) => ({
      ...f,
      year: issue.year != null ? String(issue.year) : f.year,
      mint_mark: issue.mint_letter ?? "",
      mintage: issue.mintage != null ? String(issue.mintage) : f.mintage,
    }));
    setNumistaNote(
      `Set the issue: ${[issue.year, issue.mint_letter].filter(Boolean).join(" ")}` +
        (issue.mintage != null ? `, mintage ${issue.mintage.toLocaleString()}` : "") +
        ".",
    );
  }

  const numistaKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.preventDefault(); // don't submit the item form
      lookUpNumista();
    }
  };

  useEffect(() => {
    api.listSets().then(setSets).catch(() => setSets([]));
    api
      .breakdowns()
      .then((b) => setCountries(b.by_country.map((e) => e.key)))
      .catch(() => setCountries([]));
  }, []);

  async function newSet() {
    const name = window.prompt("New set name:");
    if (!name?.trim()) return;
    try {
      const created = await api.createSet(name.trim());
      setSets((s) => [...s, created]);
      setForm((f) => ({ ...f, set_id: String(created.id) }));
    } catch (e) {
      setError((e as Error).message);
    }
  }

  useEffect(() => {
    if (!id) return;
    api
      .getItem(id)
      .then((item) => {
        setForm({
          type: item.type,
          status: item.status,
          country: item.country,
          denomination: item.denomination,
          year: String(item.year),
          mint_mark: str(item.mint_mark),
          series: str(item.series),
          variety: str(item.variety),
          strike: item.strike,
          set_id: item.set ? String(item.set.id) : "",
          composition: str(item.composition),
          weight_g: str(item.weight_g),
          fineness: str(item.fineness),
          diameter_mm: str(item.diameter_mm),
          thickness_mm: str(item.thickness_mm),
          edge: str(item.edge),
          shape: str(item.shape),
          mintage: str(item.mintage),
          grade_id: item.grade ? String(item.grade.id) : "",
          grade_plus: item.grade_plus,
          grade_star: item.grade_star,
          designations: item.designations ?? [],
          grade_details: str(item.grade_details),
          cac_sticker: str(item.cac_sticker),
          cert_service: str(item.cert_service),
          cert_number: str(item.cert_number),
          serial_number: str(item.serial_number),
          prefix_block: str(item.prefix_block),
          signatures: str(item.signatures),
          issuer: str(item.issuer),
          replacement_note: item.replacement_note,
          quantity: String(item.quantity),
          acquisition_date: str(item.acquisition_date),
          acquisition_price: str(item.acquisition_price),
          acquisition_fees: str(item.acquisition_fees),
          currency: item.currency,
          acquired_from: str(item.acquired_from),
          storage_location: str(item.storage_location),
          sold_date: str(item.sold_date),
          sold_price: str(item.sold_price),
          sold_fees: str(item.sold_fees),
          sold_to: str(item.sold_to),
          notes: str(item.notes),
          tags: item.tags.join(", "),
        });
        setRefs(item.catalog_refs);
        setCustomFields(
          Object.entries(item.custom_fields ?? {}).map(([key, value]) => ({ key, value })),
        );
      })
      .catch((e: Error) => setError(e.message));
  }, [id]);

  const set = (field: TextField) => (value: string) =>
    setForm((f) => ({ ...f, [field]: value }));

  const setRef = (index: number, field: keyof CatalogRef, value: string) =>
    setRefs((rs) => rs.map((r, i) => (i === index ? { ...r, [field]: value } : r)));

  const toggleDesignation = (code: string) =>
    setForm((f) => ({
      ...f,
      designations: f.designations.includes(code)
        ? f.designations.filter((d) => d !== code)
        : [...f.designations, code],
    }));

  async function save(addAnother: boolean) {
    setSaving(true);
    setError(null);
    setSavedNote(null);
    try {
      const payload = toPayload(form, refs, customFields);
      const saved = id ? await api.updateItem(id, payload) : await api.createItem(payload);
      if (!addAnother) {
        navigate(`/items/${saved.id}`);
        return;
      }
      // keep the fields that tend to repeat during a bulk-entry session
      setForm((f) => ({
        ...EMPTY,
        type: f.type,
        country: f.country,
        currency: f.currency,
        acquisition_date: f.acquisition_date,
        acquired_from: f.acquired_from,
        storage_location: f.storage_location,
        set_id: f.set_id,
        composition: f.composition,
        fineness: f.fineness,
        tags: f.tags,
      }));
      setRefs([]);
      setCustomFields([]);
      setSavedNote(`Added ${saved.country} ${saved.denomination}, ${saved.year}.`);
      window.scrollTo(0, 0);
      setSaving(false);
    } catch (err) {
      setError((err as Error).message);
      setSaving(false);
    }
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    save(false);
  }

  const text = (field: TextField, label: string, props: object = {}) => (
    <label className="field">
      {label}
      <input value={form[field]} onChange={(e) => set(field)(e.target.value)} {...props} />
    </label>
  );

  const flag = (field: FlagField, label: string, title?: string) => (
    <label className="slot" title={title}>
      <input
        type="checkbox"
        checked={form[field]}
        onChange={(e) => setForm((f) => ({ ...f, [field]: e.target.checked }))}
      />
      {label}
    </label>
  );

  // On the Sheldon scale a proof or specimen keeps the grade number and changes the prefix.
  const gradeCode = (g: Grade) =>
    g.scale === "sheldon" && form.strike !== "business"
      ? `${form.strike === "proof" ? "PR" : "SP"}-${g.rank}`
      : g.code;

  const isCoin = form.type === "coin";

  return (
    <>
      <div className="detail-header">
        <h1>{id ? "Edit item" : "Add item"}</h1>
      </div>
      {error && <p className="error">{error}</p>}
      {savedNote && <p className="muted">{savedNote}</p>}
      <form onSubmit={submit}>
        <div className="card">
          <h2>Fill from Numista</h2>
          {numistaConfigured === false ? (
            <p className="muted" style={{ margin: 0 }}>
              Add a Numista API key in <Link to="/settings">Settings</Link> to fill items in from
              the Numista catalogue.
            </p>
          ) : (
            <>
              <div className="estimate-form" style={{ marginTop: 0 }}>
                <label className="field">
                  Numista number or search
                  <input
                    value={numistaQuery}
                    placeholder='e.g. N#1493, or "morgan dollar"'
                    onChange={(e) => setNumistaQuery(e.target.value)}
                    onKeyDown={numistaKey}
                  />
                </label>
                <button
                  type="button"
                  disabled={numistaBusy || !numistaQuery.trim()}
                  onClick={lookUpNumista}
                >
                  {numistaBusy ? "Looking up…" : "Look up"}
                </button>
                {numistaIssues.length > 1 && (
                  <label className="field">
                    Issue
                    <select value="" onChange={(e) => pickIssue(e.target.value)}>
                      <option value="">choose year / mint…</option>
                      {numistaIssues.map((issue, i) => (
                        <option key={i} value={i}>
                          {[issue.year, issue.mint_letter].filter(Boolean).join(" ") || "undated"}
                          {issue.mintage != null ? ` — ${issue.mintage.toLocaleString()}` : ""}
                          {issue.comment ? ` (${issue.comment})` : ""}
                        </option>
                      ))}
                    </select>
                  </label>
                )}
              </div>
              {numistaError && <p className="error">{numistaError}</p>}
              {numistaNote && <p className="muted">{numistaNote}</p>}
              {numistaResults &&
                (numistaResults.length === 0 ? (
                  <p className="muted">No matches on Numista.</p>
                ) : (
                  <ul className="numista-results">
                    {numistaResults.map((r) => (
                      <li key={r.type_id}>
                        {r.thumbnail ? <img src={r.thumbnail} alt="" loading="lazy" /> : <span />}
                        <div>
                          <b>{r.title}</b>
                          <div className="muted">
                            {[r.issuer, yearSpan(r), `N#${r.type_id}`].filter(Boolean).join(" · ")}
                          </div>
                        </div>
                        <button type="button" disabled={numistaBusy}
                          onClick={() => applyNumista(r.type_id)}>
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

        <div className="card">
          <h2>Identity</h2>
          <div className="item-form">
            <label className="field">
              Type
              <select
                value={form.type}
                onChange={(e) => {
                  const type = e.target.value as ItemType;
                  // Switching type switches grading scale and designations; nothing
                  // from the other scale may survive the switch.
                  setForm((f) => ({
                    ...f,
                    type,
                    grade_id: "",
                    designations: [],
                    strike: type === "note" && f.strike === "proof" ? "business" : f.strike,
                  }));
                }}
              >
                <option value="coin">Coin</option>
                <option value="note">Note</option>
              </select>
            </label>
            {text("country", "Country *", { required: true, list: "country-options" })}
            <datalist id="country-options">
              {countries.map((c) => (
                <option key={c} value={c} />
              ))}
            </datalist>
            {text("denomination", "Denomination *", { required: true, placeholder: 'e.g. "25 cents"' })}
            {text("year", "Year *", { required: true, type: "number" })}
            {text("mint_mark", "Mint mark")}
            {text("series", "Series")}
            {text("variety", "Variety / sub-type", { placeholder: "e.g. 1955 DDO, overdate" })}
            <label className="field">
              Strike
              <select value={form.strike} onChange={(e) => set("strike")(e.target.value)}>
                <option value="business">{isCoin ? "Business strike" : "Regular issue"}</option>
                {isCoin && <option value="proof">Proof</option>}
                <option value="specimen">Specimen</option>
              </select>
            </label>
            {text("quantity", "Quantity", { type: "number", min: 1 })}
            <label className="field">
              Set / lot
              <span style={{ display: "flex", gap: "0.3rem" }}>
                <select value={form.set_id} style={{ flex: 1 }}
                  onChange={(e) => set("set_id")(e.target.value)}>
                  <option value="">none</option>
                  {sets.map((s) => (
                    <option key={s.id} value={s.id}>{s.name}</option>
                  ))}
                </select>
                <button type="button" onClick={newSet} title="Create a new set">+</button>
              </span>
            </label>
          </div>
        </div>

        <div className="card">
          <h2>Grading &amp; certification</h2>
          <div className="item-form">
            <label className="field">
              Grade ({gradeScaleFor(form.type)})
              <select value={form.grade_id} onChange={(e) => set("grade_id")(e.target.value)}>
                <option value="">ungraded</option>
                {grades.map((g) => (
                  <option key={g.id} value={g.id}>
                    {gradeCode(g)} — {g.label}
                  </option>
                ))}
              </select>
            </label>
            {text("grade_details", "Details grade (problem)", {
              list: "problem-options",
              placeholder: "blank if problem-free",
            })}
            <datalist id="problem-options">
              {PROBLEMS[form.type].map((p) => (
                <option key={p} value={p} />
              ))}
            </datalist>
            {text("cert_service", "Cert service", { placeholder: "PCGS, NGC, PMG…" })}
            {text("cert_number", "Cert number")}
            {isCoin && (
              <label className="field">
                CAC sticker
                <select value={form.cac_sticker} onChange={(e) => set("cac_sticker")(e.target.value)}>
                  <option value="">none</option>
                  <option value="green">Green</option>
                  <option value="gold">Gold</option>
                </select>
              </label>
            )}
            <div className="field full">
              Grade qualifiers
              <div className="chip-row">
                {flag("grade_plus", "Plus grade (+)")}
                {flag("grade_star", "Star (★)", "NGC or PMG star designation")}
              </div>
            </div>
            <div className="field full">
              Designations
              <div className="chip-row">
                {DESIGNATIONS[form.type].map(([code, meaning]) => (
                  <button
                    type="button"
                    key={code}
                    title={meaning}
                    className={form.designations.includes(code) ? "chip active" : "chip"}
                    onClick={() => toggleDesignation(code)}
                  >
                    {code}
                  </button>
                ))}
              </div>
            </div>
          </div>
        </div>

        <div className="card">
          <h2>{isCoin ? "Composition & physical" : "Note details"}</h2>
          <div className="item-form">
            {text("composition", "Composition", {
              placeholder: isCoin ? "e.g. 90% silver" : "e.g. paper, polymer",
            })}
            {isCoin && (
              <>
                {text("weight_g", "Weight (g)", { type: "number", step: "0.001", min: 0 })}
                {text("fineness", "Fineness", {
                  type: "number", step: "0.0001", min: 0, max: 1, placeholder: "e.g. 0.900",
                })}
                {text("diameter_mm", "Diameter (mm)", { type: "number", step: "0.01", min: 0 })}
                {text("thickness_mm", "Thickness (mm)", { type: "number", step: "0.01", min: 0 })}
                {text("edge", "Edge", { list: "edge-options" })}
                <datalist id="edge-options">
                  {EDGES.map((v) => <option key={v} value={v} />)}
                </datalist>
                {text("shape", "Shape", { list: "shape-options" })}
                <datalist id="shape-options">
                  {SHAPES.map((v) => <option key={v} value={v} />)}
                </datalist>
              </>
            )}
            {!isCoin && (
              <>
                {text("serial_number", "Serial number")}
                {text("prefix_block", "Prefix / block")}
                {text("signatures", "Signatures", { placeholder: "e.g. Coyne–Towers" })}
                {text("issuer", "Issuer", { placeholder: "issuing bank or authority" })}
              </>
            )}
            {text("mintage", isCoin ? "Mintage" : "Print run", { type: "number", min: 0, step: 1 })}
            {!isCoin && (
              <div className="field">
                &nbsp;
                {flag("replacement_note", "Replacement / star note")}
              </div>
            )}
          </div>
        </div>

        <div className="card">
          <h2>Acquisition &amp; status</h2>
          <div className="item-form">
            {text("acquisition_date", "Acquired on", { type: "date" })}
            {text("acquisition_price", "Price paid", { type: "number", step: "0.01", min: 0 })}
            {text("acquisition_fees", "Fees, shipping & tax", {
              type: "number", step: "0.01", min: 0, title: "Counted in cost basis and gains",
            })}
            {text("currency", "Currency", { maxLength: 3 })}
            {text("acquired_from", "Acquired from", { placeholder: "dealer, show, auction…" })}
            {text("storage_location", "Storage location", { placeholder: "album, slab box, safe…" })}
            <label className="field">
              Status
              <select value={form.status} onChange={(e) => set("status")(e.target.value)}>
                <option value="owned">Owned</option>
                <option value="sold">Sold</option>
                <option value="wishlist">Wishlist</option>
              </select>
            </label>
            {form.status === "sold" && (
              <>
                {text("sold_date", "Sold on", { type: "date" })}
                {text("sold_price", "Sold price", { type: "number", step: "0.01", min: 0 })}
                {text("sold_fees", "Selling fees", {
                  type: "number", step: "0.01", min: 0, title: "Commission, listing fees",
                })}
                {text("sold_to", "Sold to / venue", { placeholder: "buyer, auction house…" })}
              </>
            )}
          </div>
        </div>

        <div className="card">
          <h2>References &amp; notes</h2>
          <div className="item-form">
            {text("tags", "Tags (comma-separated)", { placeholder: "type set, silver, for sale" })}
            <div className="field full">
              Catalog references
              {refs.map((ref, i) => (
                <div className="ref-row" key={i}>
                  <input value={ref.catalog} placeholder="catalog (krause, numista…)"
                    onChange={(e) => setRef(i, "catalog", e.target.value)} />
                  <input value={ref.ref_code} placeholder="reference code"
                    onChange={(e) => setRef(i, "ref_code", e.target.value)} />
                  <button type="button" title="Remove"
                    onClick={() => setRefs((rs) => rs.filter((_, j) => j !== i))}>
                    ✕
                  </button>
                </div>
              ))}
              <div>
                <button type="button"
                  onClick={() => setRefs((rs) => [...rs, { catalog: "", ref_code: "" }])}>
                  + Add reference
                </button>
              </div>
            </div>
            <div className="field full">
              Custom fields
              {customFields.map((f, i) => (
                <div className="ref-row" key={i}>
                  <input value={f.key} placeholder="field name"
                    onChange={(e) => setCustomFields((cf) =>
                      cf.map((x, j) => (j === i ? { ...x, key: e.target.value } : x)))} />
                  <input value={f.value} placeholder="value"
                    onChange={(e) => setCustomFields((cf) =>
                      cf.map((x, j) => (j === i ? { ...x, value: e.target.value } : x)))} />
                  <button type="button" title="Remove"
                    onClick={() => setCustomFields((cf) => cf.filter((_, j) => j !== i))}>
                    ✕
                  </button>
                </div>
              ))}
              <div>
                <button type="button"
                  onClick={() => setCustomFields((cf) => [...cf, { key: "", value: "" }])}>
                  + Add field
                </button>
              </div>
            </div>
            <label className="field full">
              Notes
              <textarea rows={4} value={form.notes}
                onChange={(e) => set("notes")(e.target.value)} />
            </label>
          </div>
        </div>

        <div className="actions" style={{ marginBottom: "1.5rem" }}>
          <button className="primary" type="submit" disabled={saving}>
            {saving ? "Saving…" : id ? "Save changes" : "Add item"}
          </button>
          {!id && (
            <button type="button" disabled={saving}
              onClick={(e) => {
                const formEl = (e.target as HTMLElement).closest("form");
                if (formEl?.reportValidity()) save(true);
              }}>
              Save &amp; add another
            </button>
          )}
          <button type="button" onClick={() => navigate(-1)}>Cancel</button>
        </div>
      </form>
    </>
  );
}
