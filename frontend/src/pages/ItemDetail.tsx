import { useCallback, useEffect, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";

import {
  api,
  CalendarReference,
  ItemDetail as ItemDetailData,
  ItemEvent,
  ItemPayload,
  SourceStatus,
} from "../api";
import { DocumentsCard } from "../components/documents";
import { ItemFacts } from "../components/item-facts";
import { ItemHero } from "../components/item-hero";
import { LookupLinks } from "../components/lookup";
import { PhotoGallery } from "../components/photo-gallery";
import { SalesLog } from "../components/sales";
import { useSerialTraits } from "../components/serial-traits";
import { ValueHistory } from "../components/value-history";

type Tab = "overview" | "value" | "files" | "history";
const TABS: { key: Tab; label: string }[] = [
  { key: "overview", label: "Overview" },
  { key: "value", label: "Value" },
  { key: "files", label: "Photos and files" },
  { key: "history", label: "History" },
];

/** The item page. With `embedded`, the same piece as the collection's
 * inspector: the id comes from the list, the sections sit behind tabs, and
 * leaving the piece (delete) stays in the list instead of navigating away. */
export default function ItemDetail({
  itemId,
  embedded = false,
  onChanged,
}: { itemId?: string; embedded?: boolean; onChanged?: () => void } = {}) {
  const params = useParams();
  const id = itemId ?? params.id;
  const navigate = useNavigate();
  const location = useLocation();
  const [tab, setTab] = useState<Tab>("overview");
  const [item, setItem] = useState<ItemDetailData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [events, setEvents] = useState<ItemEvent[] | null>(null);
  const [sources, setSources] = useState<SourceStatus[]>([]);
  const [numistaSales, setNumistaSales] = useState(false);
  const [calendars, setCalendars] = useState<CalendarReference | null>(null);
  const traitReference = useSerialTraits();
  const struckCalendar = item?.struck_calendar ?? null;

  // Calendar names, only for a piece dated in one.
  useEffect(() => {
    if (struckCalendar) api.calendars().then(setCalendars).catch(() => setCalendars(null));
  }, [struckCalendar]);

  // Which automatic sources this build offers, and whether they're switched on.
  useEffect(() => {
    api
      .getSettings()
      .then((s) => {
        setSources(s.sources);
        setNumistaSales(s.numista_sales_enabled);
      })
      .catch(() => setSources([]));
  }, []);

  const loadHistory = () => {
    if (!id) return;
    api.itemHistory(id).then(setEvents).catch(() => setEvents([]));
  };

  const reload = useCallback(() => {
    if (!id) return;
    setError(null);
    api.getItem(id).then(setItem).catch((e: Error) => setError(e.message));
  }, [id]);

  // A new piece in the inspector starts clean: no old item, no old history.
  useEffect(() => {
    setItem(null);
    setEvents(null);
  }, [id]);
  useEffect(reload, [reload]);

  // The list reloads too when something here changes what it shows.
  const changed = useCallback(() => {
    reload();
    onChanged?.();
  }, [reload, onChanged]);

  // Opening the History tab loads it, as opening the details used to.
  useEffect(() => {
    if (embedded && tab === "history" && events === null) loadHistory();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [embedded, tab, id, events]);

  if (error) return <p className="error">{error}</p>;
  if (!item) return <p className="muted">Loading…</p>;

  async function cloneItem() {
    if (!id) return;
    try {
      const copy = await api.cloneItem(id);
      navigate(`/items/${copy.id}/edit`);
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function deleteItem() {
    if (!id || !window.confirm("Move this item to the trash? You can restore it from there.")) return;
    try {
      await api.deleteItem(id);
      if (embedded) {
        onChanged?.();
        navigate(`/collection${location.search}`);
      } else {
        navigate("/collection");
      }
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function restoreItem() {
    if (!id) return;
    try {
      await api.restoreItem(id);
      changed();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function purgeItem() {
    if (
      !id ||
      !window.confirm(
        "Delete this item for good? Its photos, values, and history go too; this can't be undone.",
      )
    )
      return;
    try {
      await api.deleteItem(id, true);
      navigate("/trash");
    } catch (err) {
      setError((err as Error).message);
    }
  }

  // The actions stay outside the disabled fieldset below: a trashed item can
  // still be restored or deleted for good.
  const actions = item.deleted_at ? (
    <>
      <button className="primary" onClick={restoreItem}>Restore</button>
      <button className="danger" onClick={purgeItem}>Delete for good</button>
    </>
  ) : (
    <>
      <button onClick={cloneItem}>Clone</button>
      <Link className="button" to={`/items/${item.id}/edit`}>Edit</Link>
      <button className="danger" onClick={deleteItem}>Delete</button>
      {embedded && (
        <Link className="button" to={`/items/${item.id}`} title="Open the full page (Enter)">
          Open
        </Link>
      )}
    </>
  );

  // Facts change in place through the same PATCH the edit form uses.
  const saveFact = async (patch: Partial<ItemPayload>) => {
    await api.updateItem(item.id, patch);
    changed();
  };

  const history = (
    <>
      {events === null && <p className="muted">Loading…</p>}
      {events && events.length === 0 && <p className="muted">No history recorded.</p>}
      {events?.map((event) => (
        <div className="history-entry" key={event.id}>
          <span className="muted">{new Date(event.at).toLocaleString()}</span>: {event.action}
          {event.changes && (
            <>
              {": "}
              {Object.entries(event.changes).map(([field, [from, to]]) => (
                <span key={field}>
                  <code>{field}</code>{" "}
                  <span className="muted">
                    {JSON.stringify(from)} → {JSON.stringify(to)}
                  </span>{" "}
                </span>
              ))}
            </>
          )}
        </div>
      ))}
    </>
  );

  if (embedded) {
    return (
      <div className="inspector-body">
        {item.deleted_at && (
          <p className="trash-banner">
            In the <Link to="/trash">trash</Link> since{" "}
            {new Date(item.deleted_at).toLocaleDateString()}. Restore it to edit it again.
          </p>
        )}
        <ItemHero item={item} actions={actions} />
        <div className="tabs" role="tablist" aria-label="Item sections">
          {TABS.map((t) => (
            <button
              key={t.key}
              type="button"
              role="tab"
              id={`tab-${t.key}`}
              aria-selected={tab === t.key}
              aria-controls={`panel-${t.key}`}
              className={tab === t.key ? "tab active" : "tab"}
              onClick={() => setTab(t.key)}
            >
              {t.label}
              {t.key === "files" && item.photos.length + item.documents.length > 0 && (
                <span className="count"> {item.photos.length + item.documents.length}</span>
              )}
            </button>
          ))}
        </div>
        <fieldset
          className="plain-fieldset"
          disabled={item.deleted_at !== null}
          role="tabpanel"
          id={`panel-${tab}`}
          aria-labelledby={`tab-${tab}`}
        >
          {tab === "overview" && (
            <>
              <ItemFacts item={item} calendars={calendars} traitReference={traitReference}
                onSave={saveFact} />
              <div className="card">
                {item.notes && <p className="item-notes">{item.notes}</p>}
                <LookupLinks item={item} />
              </div>
            </>
          )}
          {tab === "value" && (
            <>
              <ValueHistory item={item} sources={sources} onChanged={changed} />
              <SalesLog
                item={item}
                compsEnabled={sources.some((s) => s.key === "comps" && s.enabled)}
                numistaSales={numistaSales}
                onChanged={changed}
              />
            </>
          )}
          {tab === "files" && (
            <>
              <PhotoGallery item={item} onChanged={changed} />
              <DocumentsCard item={item} onChanged={changed} />
            </>
          )}
          {tab === "history" && <div className="card">{history}</div>}
        </fieldset>
      </div>
    );
  }

  return (
    <>
      {item.deleted_at && (
        <p className="trash-banner">
          This item is in the <Link to="/trash">trash</Link> since{" "}
          {new Date(item.deleted_at).toLocaleDateString()}. Restore it to edit it again.
        </p>
      )}

      <ItemHero item={item} actions={actions} />

      <fieldset className="plain-fieldset" disabled={item.deleted_at !== null}>

      <ItemFacts item={item} calendars={calendars} traitReference={traitReference}
                onSave={saveFact} />

      <div className="card">
        {item.notes && <p className="item-notes">{item.notes}</p>}
        <LookupLinks item={item} />
      </div>

      <PhotoGallery item={item} onChanged={reload} />

      <DocumentsCard item={item} onChanged={reload} />

      <ValueHistory item={item} sources={sources} onChanged={reload} />

      <SalesLog
        item={item}
        compsEnabled={sources.some((s) => s.key === "comps" && s.enabled)}
        numistaSales={numistaSales}
        onChanged={reload}
      />

      <details className="history" onToggle={(e) => e.currentTarget.open && loadHistory()}>
        <summary>Edit history</summary>
        {events === null && <p className="muted">Loading…</p>}
        {events && events.length === 0 && <p className="muted">No history recorded.</p>}
        {events?.map((event) => (
          <div className="history-entry" key={event.id}>
            <span className="muted">{new Date(event.at).toLocaleString()}</span>: {event.action}
            {event.changes && (
              <>
                {": "}
                {Object.entries(event.changes).map(([field, [from, to]]) => (
                  <span key={field}>
                    <code>{field}</code>{" "}
                    <span className="muted">
                      {JSON.stringify(from)} → {JSON.stringify(to)}
                    </span>{" "}
                  </span>
                ))}
              </>
            )}
          </div>
        ))}
      </details>
      </fieldset>
    </>
  );
}
