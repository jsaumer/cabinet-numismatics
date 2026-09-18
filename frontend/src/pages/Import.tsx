import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import {
  api,
  ImportDefaults,
  ImportFormat,
  ImportOptions,
  ImportPreview,
  ImportResult,
  ImportRunResult,
  ImportUpload,
  money,
} from "../api";

type Source = "numista" | "file" | "cabinet";

const SOURCES: { key: Source; title: string; text: string }[] = [
  {
    key: "numista",
    title: "My Numista collection",
    text: "Straight from your Numista account, with the API key saved in Settings.",
  },
  {
    key: "file",
    title: "A file from another tool",
    text:
      "Numista's export (CSV/XLSX), an OpenNumismat collection (.db), or any spreadsheet — " +
      "uCoin, CoinSnap, Colnect, your own sheet.",
  },
  {
    key: "cabinet",
    title: "A Cabinet export",
    text: "The CSV from Collection → CSV, e.g. from another Cabinet.",
  },
];

const FORMAT_NAMES: Record<ImportFormat, string> = {
  numista_file: "Numista export",
  opennumismat: "OpenNumismat collection",
  spreadsheet: "Spreadsheet (match its columns)",
};

const STATUS_LABELS = { new: "new", duplicate: "already imported", error: "won't import" };

const formatBytes = (n: number) =>
  n > 1024 * 1024 ? `${(n / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`;

export default function Import() {
  const [source, setSource] = useState<Source>("numista");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [result, setResult] = useState<ImportRunResult | null>(null);
  const [csvResult, setCsvResult] = useState<ImportResult | null>(null);
  const [numistaKey, setNumistaKey] = useState<boolean | null>(null);
  const [displayCurrency, setDisplayCurrency] = useState("USD");

  // Numista account
  const [details, setDetails] = useState(true);
  const [pictures, setPictures] = useState(false);

  // Files
  const [upload, setUpload] = useState<ImportUpload | null>(null);
  const [format, setFormat] = useState<ImportFormat>("spreadsheet");
  const [mapping, setMapping] = useState<Record<string, string> | null>(null);
  const [skipRows, setSkipRows] = useState<number | null>(null);
  const [defaults, setDefaults] = useState<ImportDefaults>({
    type: "coin",
    status: "owned",
    currency: "USD",
    country: null,
  });

  useEffect(() => {
    api
      .getSettings()
      .then((s) => {
        setNumistaKey(s.sources.some((x) => x.key === "numista" && x.configured));
        setDisplayCurrency(s.display_currency);
        setDefaults((d) => ({ ...d, currency: s.display_currency }));
      })
      .catch(() => setNumistaKey(false));
  }, []);

  function reset() {
    setError(null);
    setPreview(null);
    setResult(null);
    setCsvResult(null);
  }

  function choose(next: Source) {
    reset();
    setSource(next);
  }

  async function run<T>(label: string, fn: () => Promise<T>): Promise<T | undefined> {
    setBusy(label);
    setError(null);
    try {
      return await fn();
    } catch (err) {
      setError((err as Error).message);
      return undefined;
    } finally {
      setBusy(null);
    }
  }

  const fileOptions = (overrides: Partial<ImportOptions> = {}): ImportOptions => ({
    format,
    // A different header line means different columns: let Cabinet guess again.
    mapping: format === "spreadsheet" && preview?.header_row === skipRows ? mapping : null,
    skip_rows: format === "spreadsheet" ? skipRows : null,
    defaults: { ...defaults, country: defaults.country?.trim() || null },
    ...overrides,
  });

  async function chooseFile(file: File | undefined) {
    if (!file) return;
    reset();
    if (upload) api.discardImport(upload.upload_id).catch(() => undefined);
    setUpload(null);
    const staged = await run("upload", () => api.uploadImport(file));
    if (!staged) return;
    setUpload(staged);
    setFormat(staged.format);
    setMapping(null);
    setSkipRows(null);
    const first = await run("preview", () =>
      api.previewImport(staged.upload_id, { format: staged.format, defaults }),
    );
    if (first) applyPreview(first);
  }

  function applyPreview(next: ImportPreview) {
    setPreview(next);
    setResult(null);
    if (next.mapping) setMapping(next.mapping);
    if (next.header_row != null) setSkipRows(next.header_row);
  }

  async function refreshPreview(overrides: Partial<ImportOptions> = {}) {
    if (!upload) return;
    const next = await run("preview", () =>
      api.previewImport(upload.upload_id, fileOptions(overrides)),
    );
    if (next) applyPreview(next);
  }

  async function importFile() {
    if (!upload) return;
    const done = await run("import", () => api.runImport(upload.upload_id, fileOptions()));
    if (!done) return;
    // Show the file as it now stands: what was just imported reads "already imported".
    const next = await api.previewImport(upload.upload_id, fileOptions()).catch(() => null);
    if (next) applyPreview(next);
    setResult(done);
  }

  async function previewNumista() {
    reset();
    const next = await run("preview", () =>
      api.previewNumistaImport({ catalogue_details: details, fetch_photos: pictures }),
    );
    if (next) setPreview(next);
  }

  async function importNumista() {
    const options = { catalogue_details: details, fetch_photos: pictures };
    const done = await run("import", () => api.runNumistaImport(options));
    if (!done) return;
    const next = await api.previewNumistaImport(options).catch(() => null);
    if (next) setPreview(next);
    setResult(done);
  }

  async function importCabinet(file: File | undefined) {
    if (!file) return;
    reset();
    const done = await run("import", () => api.importCsv(file));
    if (done) setCsvResult(done);
  }

  const setMapped = (key: string, column: string) =>
    setMapping((m) => {
      const next = { ...(m ?? {}) };
      if (column) next[key] = column;
      else delete next[key];
      return next;
    });

  const numistaReady = numistaKey === true;

  return (
    <>
      <div className="detail-header">
        <h1>Import</h1>
      </div>
      <p className="muted" style={{ marginTop: 0 }}>
        Bring a collection in from another tool. You'll see a preview first — nothing is added
        until you confirm — and importing the same source again skips what's already here.
      </p>

      <div className="import-sources">
        {SOURCES.map((s) => (
          <button
            key={s.key}
            type="button"
            className={`import-source${source === s.key ? " active" : ""}`}
            onClick={() => choose(s.key)}
          >
            <b>{s.title}</b>
            <small>{s.text}</small>
          </button>
        ))}
      </div>

      {error && <p className="error">{error}</p>}

      {source === "numista" && (
        <div className="card">
          <h2>My Numista collection</h2>
          {numistaKey === false && (
            <p className="error">
              Add your Numista API key in <Link to="/settings">Settings → Price sources</Link>{" "}
              first. The key is tied to your Numista account, so it can read your own collection.
            </p>
          )}
          <p className="muted" style={{ marginTop: 0 }}>
            Reads every coin and banknote in your collection on numista.com — grade, quantity,
            price paid, acquisition date and place, storage, comments, and slab details —
            and links each item to its Numista type, so Numista pricing works on it straight away.
            Tokens and medals (exonumia) aren't imported.
          </p>
          <div className="estimate-form" style={{ marginTop: 0 }}>
            <label className="slot">
              <input type="checkbox" checked={details} onChange={(e) => setDetails(e.target.checked)} />
              Fill in catalogue details (denomination, composition, weight, size) — one Numista
              request per coin type not looked up in the last week
            </label>
            <label className="slot">
              <input type="checkbox" checked={pictures} onChange={(e) => setPictures(e.target.checked)} />
              Download the pictures attached to your Numista items
            </label>
          </div>
          <div className="estimate-form">
            <button disabled={!numistaReady || busy !== null} onClick={previewNumista}>
              {busy === "preview" ? "Reading your collection…" : "Preview"}
            </button>
          </div>
        </div>
      )}

      {source === "file" && (
        <div className="card">
          <h2>A file from another tool</h2>
          <div className="estimate-form" style={{ marginTop: 0 }}>
            <label className="field">
              {busy === "upload" ? "Uploading…" : "File"}
              <input
                type="file"
                accept=".csv,.xlsx,.db,.txt,text/csv"
                disabled={busy !== null}
                onChange={(e) => {
                  chooseFile(e.target.files?.[0]);
                  e.target.value = "";
                }}
              />
            </label>
            {upload && (
              <label className="field">
                Read it as
                <select
                  value={format}
                  onChange={(e) => {
                    const next = e.target.value as ImportFormat;
                    setFormat(next);
                    setMapping(null);
                    refreshPreview({ format: next, mapping: null, skip_rows: null });
                  }}
                >
                  {(Object.keys(FORMAT_NAMES) as ImportFormat[]).map((f) => (
                    <option key={f} value={f}>
                      {FORMAT_NAMES[f]}
                      {f === upload.format ? " (detected)" : ""}
                    </option>
                  ))}
                </select>
              </label>
            )}
          </div>
          {upload && (
            <p className="muted">
              {upload.filename} · {formatBytes(upload.size)}
            </p>
          )}
          <details className="history">
            <summary>Where do I get these files?</summary>
            <ul className="sale-help">
              <li>
                <b>Numista</b> — on numista.com open your collection ("My coins"), choose
                <i> Export</i>, and pick CSV or Excel. Tick the columns you want; Cabinet reads
                them by name. (Or skip the file and use <i>My Numista collection</i>.)
              </li>
              <li>
                <b>OpenNumismat</b> — upload the collection file itself (the <code>.db</code>{" "}
                you open in OpenNumismat). Photos stored in it come along. Works with files
                from OpenNumismat 1.9 to 1.11.
              </li>
              <li>
                <b>Anything else</b> — export or save as CSV or Excel, then match its columns
                below. Colnect's export has a few lines above the column names; Cabinet finds the
                header row, and you can set it by hand.
              </li>
            </ul>
          </details>

          {upload && preview && format === "spreadsheet" && preview.fields && preview.headers && (
            <>
              <h3>Match the columns</h3>
              <p className="muted" style={{ margin: 0 }}>
                Cabinet guessed from the column names. Country, denomination, and year are
                required; a grade can be written any usual way (MS-64, XF, "Very Fine", 64 EPQ).
              </p>
              <div className="estimate-form">
                <label className="field">
                  Column names are on line
                  <input
                    type="number"
                    min={1}
                    style={{ width: "5rem" }}
                    value={(skipRows ?? 0) + 1}
                    onChange={(e) => setSkipRows(Math.max(0, Number(e.target.value) - 1))}
                  />
                </label>
                <label className="field">
                  Default type
                  <select
                    value={defaults.type}
                    onChange={(e) =>
                      setDefaults({ ...defaults, type: e.target.value as ImportDefaults["type"] })
                    }
                  >
                    <option value="coin">Coin</option>
                    <option value="note">Banknote</option>
                  </select>
                </label>
                <label className="field">
                  Default status
                  <select
                    value={defaults.status}
                    onChange={(e) =>
                      setDefaults({ ...defaults, status: e.target.value as ImportDefaults["status"] })
                    }
                  >
                    <option value="owned">Owned</option>
                    <option value="wishlist">Wish list</option>
                    <option value="sold">Sold</option>
                  </select>
                </label>
                <label className="field">
                  Default country
                  <input
                    value={defaults.country ?? ""}
                    placeholder="if the file has none"
                    onChange={(e) => setDefaults({ ...defaults, country: e.target.value })}
                  />
                </label>
              </div>
              <div className="import-mapping">
                {preview.fields.map((f) => (
                  <label key={f.key} className="field">
                    {f.label}
                    <select value={mapping?.[f.key] ?? ""} onChange={(e) => setMapped(f.key, e.target.value)}>
                      <option value="">— not imported —</option>
                      {preview.headers!.map((h) => (
                        <option key={h} value={h}>
                          {h}
                        </option>
                      ))}
                    </select>
                  </label>
                ))}
              </div>
            </>
          )}

          {upload && (
            <div className="estimate-form">
              {format !== "numista_file" && (
                <label className="field">
                  Currency of prices
                  <input
                    value={defaults.currency}
                    maxLength={3}
                    style={{ width: "4.5rem" }}
                    onChange={(e) => setDefaults({ ...defaults, currency: e.target.value.toUpperCase() })}
                  />
                </label>
              )}
              <button disabled={busy !== null} onClick={() => refreshPreview()}>
                {busy === "preview" ? "Reading…" : "Update preview"}
              </button>
            </div>
          )}
          {upload && format !== "numista_file" && (
            <p className="muted" style={{ marginBottom: 0 }}>
              Prices in the file are taken to be in this currency unless it names one
              {displayCurrency !== defaults.currency && ` (your display currency is ${displayCurrency})`}.
            </p>
          )}
        </div>
      )}

      {source === "cabinet" && (
        <div className="card">
          <h2>A Cabinet export</h2>
          <p className="muted" style={{ marginTop: 0 }}>
            Imports the CSV that Collection → CSV writes, with every field. Rows whose item
            already exists here are skipped. There's no preview for this format.
          </p>
          <label className="field">
            {busy === "import" ? "Importing…" : "CSV file"}
            <input
              type="file"
              accept=".csv,text/csv"
              disabled={busy !== null}
              onChange={(e) => {
                importCabinet(e.target.files?.[0]);
                e.target.value = "";
              }}
            />
          </label>
          {csvResult && (
            <p className={csvResult.errors.length ? "error" : "gain"}>
              Imported {csvResult.created} item{csvResult.created === 1 ? "" : "s"}.
              {csvResult.skipped > 0 && ` ${csvResult.skipped} already existed (skipped).`}
              {csvResult.errors.length > 0 &&
                ` ${csvResult.errors.length} row(s) failed: ` +
                  csvResult.errors.map((e) => `row ${e.row}: ${e.error}`).join("; ")}{" "}
              <Link to="/collection">Open the collection</Link>
            </p>
          )}
        </div>
      )}

      {preview && source !== "cabinet" && (
        <div className="card">
          <h2>Preview</h2>
          <div className="chip-row import-summary">
            <span className="chip active">{preview.new} new</span>
            {preview.duplicates > 0 && <span className="chip">{preview.duplicates} already imported</span>}
            {preview.errors > 0 && <span className="chip coverage-failed">{preview.errors} won't import</span>}
            {preview.warnings > 0 && <span className="chip">{preview.warnings} with notes</span>}
            {preview.photos > 0 && <span className="chip">{preview.photos} photos</span>}
          </div>
          {preview.types != null && (
            <p className="muted" style={{ marginTop: 0 }}>
              {preview.types} coin and note type{preview.types === 1 ? "" : "s"}.
              {details &&
                (preview.types_to_fetch
                  ? ` Importing looks up ${preview.types_to_fetch} of them on Numista (one request each, from your monthly quota).`
                  : " Their catalogue details are already cached.")}
              {preview.photos > 0 && !pictures && " Pictures won't be downloaded (the option is off)."}
            </p>
          )}
          {preview.total > preview.rows.length && (
            <p className="muted">Showing the first {preview.rows.length} of {preview.total}.</p>
          )}
          {preview.rows.length > 0 && (
            <div className="table-scroll">
              <table className="estimates">
                <thead>
                  <tr>
                    <th>#</th>
                    <th>Item</th>
                    <th>Grade</th>
                    <th>Status</th>
                    <th>Qty</th>
                    <th>Paid</th>
                    <th>Photos</th>
                    <th>Import</th>
                  </tr>
                </thead>
                <tbody>
                  {preview.rows.map((r) => (
                    <tr key={r.row} className={`import-${r.status}`}>
                      <td className="muted">{r.row}</td>
                      <td>
                        {r.label}
                        {r.type === "note" && <span className="muted"> · note</span>}
                        {(r.error || r.messages.length > 0) && (
                          <ul className="import-messages">
                            {r.error && <li>{r.error}</li>}
                            {r.messages.map((m, i) => (
                              <li key={i} className="muted">
                                {m}
                              </li>
                            ))}
                          </ul>
                        )}
                      </td>
                      <td>{r.grade ?? "—"}</td>
                      <td>{r.status_value ?? "—"}</td>
                      <td>{r.quantity ?? "—"}</td>
                      <td>{r.price != null ? money(r.price, r.currency) : "—"}</td>
                      <td>{r.photos || "—"}</td>
                      <td>{STATUS_LABELS[r.status]}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <div className="estimate-form">
            <button
              className="primary"
              disabled={busy !== null || preview.new === 0}
              onClick={source === "numista" ? importNumista : importFile}
            >
              {busy === "import"
                ? "Importing…"
                : `Import ${preview.new} item${preview.new === 1 ? "" : "s"}`}
            </button>
            {busy === "import" && (
              <span className="muted">This can take a while for a large collection with photos.</span>
            )}
          </div>
          {result && (
            <p className={result.errors.length ? "error" : "gain"}>
              Imported {result.created} item{result.created === 1 ? "" : "s"}
              {result.photos_added > 0 && ` with ${result.photos_added} photo${result.photos_added === 1 ? "" : "s"}`}.
              {result.skipped > 0 && ` ${result.skipped} were already here.`}
              {result.photos_failed > 0 && ` ${result.photos_failed} photo(s) couldn't be read.`}
              {result.errors.length > 0 && ` ${result.errors.length} row(s) weren't imported.`}{" "}
              <Link to="/collection">Open the collection</Link>
            </p>
          )}
        </div>
      )}
    </>
  );
}
