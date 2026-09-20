// Edit mode: the bar at the top, the per-card controls, the widget catalogue,
// the options form, and the hand-written drag. Nothing here saves anything;
// the page holds the draft layout and only Save sends it.

import {
  ButtonHTMLAttributes,
  KeyboardEvent,
  PointerEvent,
  ReactNode,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import { api, DashboardWidget, SetInfo, TagInfo, WidgetOptions, WidgetSize } from "../api";
import {
  ArrowDownIcon,
  ArrowUpIcon,
  CloseIcon,
  CopyIcon,
  GripIcon,
  PlusIcon,
  SlidersIcon,
} from "../components/icons";
import { fetchOnce } from "./data";
import { OptionField } from "./options";
import { GROUPS, REGISTRY, widgetTitle } from "./registry";

const SIZES: { value: WidgetSize; label: string }[] = [
  { value: "full", label: "Full width" },
  { value: "half", label: "Half width" },
  { value: "third", label: "A third" },
];

interface Drag {
  id: string;
  from: number; // where it sat when the drag started
  to: number; // where it would land now
  pointerId: number;
  height: number; // the lifted card's height, for the placeholder
}

interface Landing {
  index: number;
  after: boolean;
  distance: number;
}

export interface Reorder {
  /** The widget being dragged with a pointer, drawn as the placeholder. */
  dragId: string | null;
  dragHeight: number;
  /** The widget picked up from the keyboard: it stays a normal card. */
  grabbedId: string | null;
  /** The widgets in the order they are drawn right now. */
  order: DashboardWidget[];
  registerCell: (id: string) => (node: HTMLDivElement | null) => void;
  handleProps: (
    widget: DashboardWidget,
    index: number,
  ) => ButtonHTMLAttributes<HTMLButtonElement>;
}

const EDGE = 90; // how close to an edge auto-scroll starts
const SPEED = 16; // pixels per frame at the very edge

/** Dragging and keyboard-moving the cards. The pointer drag previews its
 * landing spot and commits on release; the keyboard path applies each step as
 * it goes, so the focused handle travels with its card. */
export function useWidgetDrag(
  widgets: DashboardWidget[],
  move: (from: number, to: number) => void,
  announce: (text: string) => void,
): Reorder {
  const cells = useRef(new Map<string, HTMLDivElement>());
  const [drag, setDrag] = useState<Drag | null>(null);
  const dragRef = useRef<Drag | null>(null);
  const [grabbed, setGrabbed] = useState<{ id: string; from: number } | null>(null);
  const pointer = useRef({ x: 0, y: 0 });
  const speed = useRef(0);
  const frame = useRef<number | null>(null);
  const list = useRef(widgets);
  list.current = widgets;

  const setLive = (next: Drag | null) => {
    dragRef.current = next;
    setDrag(next);
  };

  /** Where the pointer says the card should land, as an index in the list
   * without it. The axis the pointer is furthest along decides before or
   * after, so cards side by side compare sideways and stacked cards compare
   * up and down, whatever span each one has. */
  const landingFor = (x: number, y: number, dragId: string): number => {
    // Over its own placeholder it stays put, or the cards would shuffle under
    // a pointer that isn't moving.
    const own = cells.current.get(dragId)?.getBoundingClientRect();
    if (own && x >= own.left && x <= own.right && y >= own.top && y <= own.bottom) {
      return dragRef.current?.to ?? 0;
    }
    const rest = list.current.filter((w) => w.id !== dragId);
    let best: Landing | null = null;
    for (let index = 0; index < rest.length; index++) {
      const node = cells.current.get(rest[index].id);
      if (!node) continue;
      const rect = node.getBoundingClientRect();
      if (rect.width === 0 || rect.height === 0) continue; // an empty card, hidden
      const cx = rect.left + rect.width / 2;
      const cy = rect.top + rect.height / 2;
      const dx = (x - cx) / rect.width;
      const dy = (y - cy) / rect.height;
      const after = Math.abs(dx) > Math.abs(dy) ? dx > 0 : dy > 0;
      const distance = Math.hypot(x - cx, y - cy);
      if (!best || distance < best.distance) best = { index, after, distance };
    }
    if (!best) return 0;
    return best.index + (best.after ? 1 : 0);
  };

  const stopScrolling = () => {
    if (frame.current != null) cancelAnimationFrame(frame.current);
    frame.current = null;
    speed.current = 0;
  };

  const step = () => {
    frame.current = null;
    const live = dragRef.current;
    if (!live || !speed.current) return;
    window.scrollBy(0, speed.current);
    // The page moved under a still pointer, so the landing spot may have too.
    const to = landingFor(pointer.current.x, pointer.current.y, live.id);
    if (to !== live.to) setLive({ ...live, to });
    frame.current = requestAnimationFrame(step);
  };

  const autoScroll = (y: number) => {
    const bottom = window.innerHeight - EDGE;
    let next = 0;
    if (y < EDGE) next = -Math.min(1, (EDGE - y) / EDGE) * SPEED;
    else if (y > bottom) next = Math.min(1, (y - bottom) / EDGE) * SPEED;
    speed.current = next;
    if (next && frame.current == null) frame.current = requestAnimationFrame(step);
  };

  // The drag listens on the window, not the handle: reordering the cards moves
  // the handle's DOM node, and a moved node loses its pointer capture, so the
  // release would never arrive.
  const listeners = useRef<(() => void) | null>(null);

  const finish = (commit: boolean) => {
    const live = dragRef.current;
    listeners.current?.();
    listeners.current = null;
    stopScrolling();
    document.body.classList.remove("dash-dragging");
    setLive(null);
    if (!live || !commit || live.to === live.from) return;
    const current = list.current;
    announce(`${widgetTitle(current[live.from])} moved to position ${live.to + 1} of ${current.length}`);
    move(live.from, live.to);
  };

  // Escape gives up on a drag in progress, wherever the pointer is.
  useEffect(() => {
    if (!drag) return;
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        finish(false);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [drag]);

  // Leaving edit mode, or the page, mid-drag.
  useEffect(
    () => () => {
      listeners.current?.();
      stopScrolling();
      document.body.classList.remove("dash-dragging");
    },
    [],
  );

  const registerCell = (id: string) => (node: HTMLDivElement | null) => {
    if (node) cells.current.set(id, node);
    else cells.current.delete(id);
  };

  const handleProps = (
    widget: DashboardWidget,
    index: number,
  ): ButtonHTMLAttributes<HTMLButtonElement> => {
    const picked = grabbed?.id === widget.id;
    return {
      type: "button",
      className: `dash-handle${drag?.id === widget.id ? " dragging" : ""}${picked ? " grabbed" : ""}`,
      title: "Drag to move, or press Space and use the arrow keys",
      "aria-label": `Move ${widgetTitle(widget)}`,
      "aria-pressed": picked,
      onPointerDown: (e: PointerEvent<HTMLButtonElement>) => {
        if (e.button !== 0 || dragRef.current) return;
        const node = cells.current.get(widget.id);
        if (!node) return;
        e.preventDefault();
        const onMove = (ev: globalThis.PointerEvent) => {
          const live = dragRef.current;
          if (!live || live.pointerId !== ev.pointerId) return;
          pointer.current = { x: ev.clientX, y: ev.clientY };
          const to = landingFor(ev.clientX, ev.clientY, live.id);
          if (to !== live.to) setLive({ ...live, to });
          autoScroll(ev.clientY);
        };
        const onUp = (ev: globalThis.PointerEvent) => {
          if (dragRef.current?.pointerId === ev.pointerId) finish(true);
        };
        const onCancel = () => finish(false);
        window.addEventListener("pointermove", onMove);
        window.addEventListener("pointerup", onUp);
        window.addEventListener("pointercancel", onCancel);
        listeners.current = () => {
          window.removeEventListener("pointermove", onMove);
          window.removeEventListener("pointerup", onUp);
          window.removeEventListener("pointercancel", onCancel);
        };
        pointer.current = { x: e.clientX, y: e.clientY };
        document.body.classList.add("dash-dragging");
        // The card's own height, so the placeholder leaves the same gap.
        const card = node.querySelector(".card");
        setLive({
          id: widget.id,
          from: index,
          to: index,
          pointerId: e.pointerId,
          height: (card ?? node).getBoundingClientRect().height,
        });
      },
      onKeyDown: (e: KeyboardEvent<HTMLButtonElement>) => {
        const current = list.current;
        const at = current.findIndex((w) => w.id === widget.id);
        if (at === -1) return;
        if (e.key === " " || e.key === "Enter") {
          e.preventDefault();
          if (picked) {
            setGrabbed(null);
            announce(`${widgetTitle(widget)} dropped at position ${at + 1} of ${current.length}`);
          } else {
            setGrabbed({ id: widget.id, from: at });
            announce(
              `${widgetTitle(widget)} picked up, position ${at + 1} of ${current.length}. ` +
                "Arrow keys move it, Space drops it, Escape puts it back.",
            );
          }
          return;
        }
        if (!picked) return;
        if (e.key === "Escape") {
          e.preventDefault();
          if (at !== grabbed!.from) {
            move(at, grabbed!.from);
            announce(
              `${widgetTitle(widget)} put back at position ${grabbed!.from + 1} of ${current.length}`,
            );
          }
          setGrabbed(null);
          return;
        }
        const delta =
          e.key === "ArrowUp" || e.key === "ArrowLeft"
            ? -1
            : e.key === "ArrowDown" || e.key === "ArrowRight"
              ? 1
              : 0;
        if (!delta) return;
        e.preventDefault();
        const to = at + delta;
        if (to < 0 || to >= current.length) return;
        move(at, to);
        announce(`${widgetTitle(widget)} moved to position ${to + 1} of ${current.length}`);
      },
      onBlur: () => {
        if (picked) setGrabbed(null);
      },
    };
  };

  const order = useMemo(() => {
    if (!drag) return widgets;
    const moving = widgets.find((w) => w.id === drag.id);
    if (!moving) return widgets;
    const rest = widgets.filter((w) => w.id !== drag.id);
    return [...rest.slice(0, drag.to), moving, ...rest.slice(drag.to)];
  }, [widgets, drag]);

  return {
    dragId: drag?.id ?? null,
    dragHeight: drag?.height ?? 0,
    grabbedId: grabbed?.id ?? null,
    order,
    registerCell,
    handleProps,
  };
}

/** The bar above a card in edit mode: the drag handle, the move buttons, the
 * size, and what else can be done to it. */
export function WidgetControls({
  widget,
  index,
  total,
  reorder,
  onMove,
  onSize,
  onOptions,
  onDuplicate,
  onRemove,
}: {
  widget: DashboardWidget;
  index: number;
  total: number;
  reorder: Reorder;
  onMove: (delta: number) => void;
  onSize: (size: WidgetSize) => void;
  onOptions: () => void;
  onDuplicate: () => void;
  onRemove: () => void;
}) {
  const title = widgetTitle(widget);
  return (
    <div className="dash-bar">
      <button {...reorder.handleProps(widget, index)}>
        <GripIcon />
      </button>
      <div className="spacer" />
      <button
        type="button"
        title="Move earlier"
        aria-label={`Move ${title} earlier`}
        disabled={index === 0}
        onClick={() => onMove(-1)}
      >
        <ArrowUpIcon />
      </button>
      <button
        type="button"
        title="Move later"
        aria-label={`Move ${title} later`}
        disabled={index === total - 1}
        onClick={() => onMove(1)}
      >
        <ArrowDownIcon />
      </button>
      <select
        value={widget.size}
        aria-label={`Width of ${title}`}
        onChange={(e) => onSize(e.target.value as WidgetSize)}
      >
        {SIZES.map((s) => (
          <option key={s.value} value={s.value}>
            {s.label}
          </option>
        ))}
      </select>
      <button type="button" title="Options" aria-label={`Options for ${title}`} onClick={onOptions}>
        <SlidersIcon />
      </button>
      <button
        type="button"
        title="Duplicate"
        aria-label={`Duplicate ${title}`}
        onClick={onDuplicate}
      >
        <CopyIcon />
      </button>
      <button
        type="button"
        className="danger"
        title="Remove"
        aria-label={`Remove ${title}`}
        onClick={onRemove}
      >
        <CloseIcon />
      </button>
    </div>
  );
}

/** A dialog on the usual modal, closed by Escape or the backdrop. */
function Dialog({
  label,
  onClose,
  children,
}: {
  label: string;
  onClose: () => void;
  children: ReactNode;
}) {
  useEffect(() => {
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      className="modal"
      role="dialog"
      aria-modal="true"
      aria-label={label}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="modal-body card">{children}</div>
    </div>
  );
}

/** Everything that can go on the dashboard, grouped. */
export function WidgetCatalogue({
  onAdd,
  onClose,
}: {
  onAdd: (type: string) => void;
  onClose: () => void;
}) {
  return (
    <Dialog label="Add a widget" onClose={onClose}>
      <div className="detail-header">
        <h2>Add a widget</h2>
        <div className="spacer" />
        <button type="button" onClick={onClose}>
          Close
        </button>
      </div>
      {GROUPS.map((group) => (
        <section key={group}>
          <h3>{group}</h3>
          <div className="import-sources">
            {Object.entries(REGISTRY)
              .filter(([, spec]) => spec.group === group)
              .map(([type, spec]) => (
                <button
                  key={type}
                  type="button"
                  className="import-source"
                  onClick={() => onAdd(type)}
                >
                  <b>{spec.name}</b>
                  <small>{spec.description}</small>
                </button>
              ))}
          </div>
        </section>
      ))}
    </Dialog>
  );
}

/** One widget's options, plus a title of its own. */
export function WidgetOptionsDialog({
  widget,
  onApply,
  onClose,
}: {
  widget: DashboardWidget;
  onApply: (changes: { title: string | null; options: WidgetOptions }) => void;
  onClose: () => void;
}) {
  const spec = REGISTRY[widget.type];
  const [title, setTitle] = useState(widget.title ?? "");
  const [options, setOptions] = useState<WidgetOptions>({ ...widget.options });
  // A count is kept as text while it is typed (half-typed and empty included)
  // and turned into a number in range on Apply, since the server refuses
  // anything else for these.
  const [counts, setCounts] = useState<Record<string, string>>(() => {
    const start: Record<string, string> = {};
    for (const f of spec.fields ?? []) {
      if (f.kind === "count") start[f.key] = String(widget.options[f.key] ?? "");
    }
    return start;
  });
  const [tags, setTags] = useState<TagInfo[]>([]);
  const [sets, setSets] = useState<SetInfo[]>([]);

  const wantsTags = spec.fields?.some((f) => f.kind === "tag") ?? false;
  const wantsSets = spec.fields?.some((f) => f.kind === "set") ?? false;

  useEffect(() => {
    if (wantsTags) {
      fetchOnce("tags", () => api.listTags())
        .then(setTags)
        .catch(() => setTags([]));
    }
    if (wantsSets) {
      fetchOnce("sets", () => api.listSets())
        .then(setSets)
        .catch(() => setSets([]));
    }
  }, [wantsTags, wantsSets]);

  const set = (key: string, value: string | number | null) =>
    setOptions((o) => ({ ...o, [key]: value }));

  const field = (f: OptionField) => {
    if (f.kind === "choice") {
      const current = options[f.key];
      return (
        <label className="field" key={f.key}>
          {f.label}
          <select
            value={String(current ?? "")}
            onChange={(e) => {
              const picked = f.choices.find((c) => String(c.value) === e.target.value);
              if (picked) set(f.key, picked.value);
            }}
          >
            {f.choices.map((c) => (
              <option key={String(c.value)} value={String(c.value)}>
                {c.label}
              </option>
            ))}
          </select>
        </label>
      );
    }
    if (f.kind === "count") {
      return (
        <label className="field" key={f.key}>
          {f.label} ({f.min} to {f.max})
          <input
            type="number"
            min={f.min}
            max={f.max}
            value={counts[f.key] ?? ""}
            style={{ width: "6rem" }}
            onChange={(e) => setCounts((c) => ({ ...c, [f.key]: e.target.value }))}
          />
          {f.hint && <span className="muted">{f.hint}</span>}
        </label>
      );
    }
    if (f.kind === "tag") {
      const current = options[f.key];
      return (
        <label className="field" key={f.key}>
          {f.label}
          <select
            value={typeof current === "string" ? current : ""}
            onChange={(e) => set(f.key, e.target.value || null)}
          >
            <option value="">Every item</option>
            {tags.map((t) => (
              <option key={t.name} value={t.name}>
                {t.name} ({t.count})
              </option>
            ))}
          </select>
        </label>
      );
    }
    const current = options[f.key];
    return (
      <label className="field" key={f.key}>
        {f.label}
        <select
          value={typeof current === "number" ? String(current) : ""}
          onChange={(e) => set(f.key, e.target.value ? Number(e.target.value) : null)}
        >
          <option value="">Every item</option>
          {sets.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
        </select>
      </label>
    );
  };

  return (
    <Dialog label={`${spec.name} options`} onClose={onClose}>
      <div className="detail-header">
        <h2>{spec.name}</h2>
      </div>
      <p className="muted" style={{ marginTop: 0 }}>
        {spec.description}
      </p>
      <div className="estimate-form" style={{ marginTop: 0 }}>
        <label className="field" style={{ flex: "1 1 16rem" }}>
          Title (leave empty for the usual one)
          <input
            value={title}
            maxLength={80}
            placeholder={widgetTitle({ ...widget, title: null })}
            onChange={(e) => setTitle(e.target.value)}
          />
        </label>
        {spec.fields?.map(field)}
      </div>
      <div className="actions" style={{ marginTop: "0.9rem" }}>
        <button
          type="button"
          className="primary"
          onClick={() => {
            const next: WidgetOptions = { ...options };
            for (const f of spec.fields ?? []) {
              if (f.kind !== "count") continue;
              const typed = Number(counts[f.key]);
              const fallback = spec.defaultOptions[f.key];
              next[f.key] =
                counts[f.key]?.trim() && Number.isFinite(typed)
                  ? Math.min(f.max, Math.max(f.min, Math.round(typed)))
                  : typeof fallback === "number"
                    ? fallback
                    : f.min;
            }
            onApply({ title: title.trim() || null, options: next });
          }}
        >
          Apply
        </button>
        <button type="button" onClick={onClose}>
          Cancel
        </button>
      </div>
    </Dialog>
  );
}

/** The bar above the grid in edit mode. */
export function DashboardEditBar({
  count,
  saving,
  onAdd,
  onReset,
  onCancel,
  onSave,
  announcement,
}: {
  count: number;
  saving: boolean;
  onAdd: () => void;
  onReset: () => void;
  onCancel: () => void;
  onSave: () => void;
  announcement: string;
}) {
  return (
    <div className="toolbar advanced dash-editbar">
      <button type="button" className="primary" onClick={onAdd}>
        <PlusIcon /> Add widget
      </button>
      <span className="muted" style={{ alignSelf: "center" }}>
        {count} widget(s). Drag a card by its handle, or move it with the arrow buttons.
      </span>
      <div className="spacer" />
      <button type="button" onClick={onReset}>
        Reset to default
      </button>
      <button type="button" onClick={onCancel}>
        Cancel
      </button>
      <button type="button" className="primary" disabled={saving} onClick={onSave}>
        {saving ? "Saving…" : "Save"}
      </button>
      <p className="dash-live muted" aria-live="polite">
        {announcement}
      </p>
    </div>
  );
}
