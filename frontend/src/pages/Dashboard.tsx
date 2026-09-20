import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api, DashboardLayout, DashboardWidget, WidgetOptions, WidgetSize } from "../api";
import { invalidateData, useData } from "../dashboard/data";
import {
  DashboardEditBar,
  useWidgetDrag,
  WidgetCatalogue,
  WidgetControls,
  WidgetOptionsDialog,
} from "../dashboard/edit";
import { DEFAULT_WIDGETS, newWidget, REGISTRY, widgetTitle } from "../dashboard/registry";
import { WidgetFrame } from "../dashboard/WidgetFrame";
import { SetupWidget } from "../dashboard/widgets/value";

/** Take the widget at `from` out and put it back at `to`. */
function reorderList(widgets: DashboardWidget[], from: number, to: number): DashboardWidget[] {
  const next = [...widgets];
  const [moving] = next.splice(from, 1);
  next.splice(to, 0, moving);
  return next;
}

export default function Dashboard() {
  const [saved, setSaved] = useState<DashboardLayout | null>(null);
  const [draft, setDraft] = useState<DashboardWidget[]>([]);
  const [layoutNote, setLayoutNote] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [catalogue, setCatalogue] = useState(false);
  const [optionsFor, setOptionsFor] = useState<string | null>(null);
  const [announcement, setAnnouncement] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const [refreshNote, setRefreshNote] = useState<string | null>(null);

  // The shell needs the counts to know whether the collection is empty; the
  // widgets read the same cached request.
  const stats = useData("stats", () => api.collectionStats());

  useEffect(() => {
    api
      .dashboardLayout()
      .then((layout) => {
        setSaved(layout);
        setDraft(layout.widgets);
      })
      .catch((e: Error) => {
        // The page is worth more than its arrangement: fall back to the
        // built-in layout and say why.
        setLayoutNote(`The dashboard layout couldn't be read (${e.message}); showing the default.`);
        setSaved({ version: 1, widgets: DEFAULT_WIDGETS, is_default: true });
        setDraft(DEFAULT_WIDGETS);
      });
  }, []);

  const moveWidget = (from: number, to: number) =>
    setDraft((widgets) => reorderList(widgets, from, to));

  const drag = useWidgetDrag(draft, moveWidget, setAnnouncement);

  const patch = (id: string, changes: Partial<DashboardWidget>) =>
    setDraft((widgets) => widgets.map((w) => (w.id === id ? { ...w, ...changes } : w)));

  function nudge(id: string, delta: number) {
    const at = draft.findIndex((w) => w.id === id);
    const to = at + delta;
    if (at === -1 || to < 0 || to >= draft.length) return;
    moveWidget(at, to);
    setAnnouncement(`${widgetTitle(draft[at])} moved to position ${to + 1} of ${draft.length}`);
  }

  function addWidget(type: string) {
    const widget = newWidget(
      type,
      draft.map((w) => w.id),
    );
    setDraft((widgets) => [...widgets, widget]);
    setCatalogue(false);
    setAnnouncement(`${widgetTitle(widget)} added at position ${draft.length + 1}`);
  }

  function duplicate(id: string) {
    const at = draft.findIndex((w) => w.id === id);
    if (at === -1) return;
    const copy = {
      ...newWidget(
        draft[at].type,
        draft.map((w) => w.id),
      ),
      size: draft[at].size,
      title: draft[at].title,
      options: { ...draft[at].options },
    };
    setDraft((widgets) => [...widgets.slice(0, at + 1), copy, ...widgets.slice(at + 1)]);
    setAnnouncement(`${widgetTitle(copy)} duplicated`);
  }

  function remove(id: string) {
    const widget = draft.find((w) => w.id === id);
    setDraft((widgets) => widgets.filter((w) => w.id !== id));
    if (widget) setAnnouncement(`${widgetTitle(widget)} removed`);
  }

  async function store(run: () => Promise<DashboardLayout>) {
    setSaving(true);
    setLayoutNote(null);
    try {
      const layout = await run();
      setSaved(layout);
      setDraft(layout.widgets);
      setEditing(false);
      setAnnouncement("");
      invalidateData(); // a new widget may want data nothing has fetched yet
    } catch (e) {
      setLayoutNote((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  function reset() {
    if (!window.confirm("Put the dashboard back to the default layout? Your arrangement goes.")) {
      return;
    }
    store(() => api.resetDashboardLayout());
  }

  async function refreshMelt() {
    setRefreshing(true);
    setRefreshNote(null);
    try {
      const r = await api.refreshMelt();
      setRefreshNote(
        `Melt refresh: ${r.updated} updated, ${r.skipped} skipped${r.failed ? `, ${r.failed} failed` : ""}.`,
      );
      invalidateData();
    } catch (e) {
      setRefreshNote((e as Error).message);
    } finally {
      setRefreshing(false);
    }
  }

  if (stats.error) return <p className="error">{stats.error}</p>;
  if (!stats.data || !saved) return <p className="muted">Loading…</p>;

  if (stats.data.counts.total === 0) {
    return (
      <>
        <div className="detail-header">
          <h1>Dashboard</h1>
        </div>
        <div className="card setup-card">
          <SetupWidget />
        </div>
        <div className="empty">
          Nothing to report yet. <Link to="/items/new">Add your first item</Link>.
        </div>
      </>
    );
  }

  const shown = editing ? drag.order : draft;
  const editingWidget = optionsFor ? draft.find((w) => w.id === optionsFor) : undefined;

  return (
    <>
      <div className="detail-header">
        <h1>Dashboard</h1>
        <div className="spacer" />
        <button onClick={refreshMelt} disabled={refreshing}>
          {refreshing ? "Refreshing…" : "Refresh melt values"}
        </button>
        <Link className="button" to="/report">
          Insurance report
        </Link>
        {!editing && (
          <button
            onClick={() => {
              setDraft(saved.widgets);
              setAnnouncement("");
              setEditing(true);
            }}
          >
            Edit dashboard
          </button>
        )}
      </div>
      {refreshNote && <p className="muted">{refreshNote}</p>}
      {layoutNote && <p className="error">{layoutNote}</p>}

      {editing && (
        <DashboardEditBar
          count={draft.length}
          saving={saving}
          announcement={announcement}
          onAdd={() => setCatalogue(true)}
          onReset={reset}
          onCancel={() => {
            setDraft(saved.widgets);
            setEditing(false);
            setAnnouncement("");
          }}
          onSave={() => store(() => api.saveDashboardLayout(draft))}
        />
      )}

      <div className="dash-grid">
        {shown.map((widget, index) => {
          const spec = REGISTRY[widget.type];
          if (!spec) return null; // a widget this build retired
          const Widget = spec.Component;
          const lifted = widget.id === drag.dragId ? { height: drag.dragHeight } : undefined;
          return (
            <WidgetFrame
              key={widget.id}
              widget={widget}
              title={widgetTitle(widget)}
              untitled={spec.untitled}
              cardClass={
                [spec.cardClass, drag.grabbedId === widget.id ? "dash-grabbed" : ""]
                  .filter(Boolean)
                  .join(" ") || undefined
              }
              editing={editing}
              cellRef={drag.registerCell(widget.id)}
              lifted={lifted}
              controls={
                editing ? (
                  <WidgetControls
                    widget={widget}
                    index={index}
                    total={shown.length}
                    reorder={drag}
                    onMove={(delta) => nudge(widget.id, delta)}
                    onSize={(size: WidgetSize) => patch(widget.id, { size })}
                    onOptions={() => setOptionsFor(widget.id)}
                    onDuplicate={() => duplicate(widget.id)}
                    onRemove={() => remove(widget.id)}
                  />
                ) : undefined
              }
            >
              <Widget options={widget.options} />
            </WidgetFrame>
          );
        })}
      </div>

      {catalogue && (
        <WidgetCatalogue onAdd={addWidget} onClose={() => setCatalogue(false)} />
      )}
      {editingWidget && (
        <WidgetOptionsDialog
          widget={editingWidget}
          onClose={() => setOptionsFor(null)}
          onApply={(changes: { title: string | null; options: WidgetOptions }) => {
            patch(editingWidget.id, changes);
            setOptionsFor(null);
          }}
        />
      )}
    </>
  );
}
