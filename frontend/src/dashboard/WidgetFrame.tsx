import {
  Component,
  createContext,
  ReactNode,
  RefObject,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import type { DashboardWidget, WidgetOptions } from "../api";
import { Loaded, useData } from "./data";

export interface WidgetProps {
  options: WidgetOptions;
}

interface WidgetContextValue {
  /** The card is near enough to the viewport to be worth fetching for. */
  near: boolean;
  /** The widget has nothing to show: hide the card, except in edit mode. */
  setEmpty: (empty: boolean) => void;
}

const WidgetContext = createContext<WidgetContextValue>({ near: true, setEmpty: () => {} });

/** True once the element has come within 300px of the viewport, and then for
 * good: a widget scrolled past keeps what it fetched. */
function useNearViewport(ref: RefObject<HTMLElement | null>): boolean {
  const [near, setNear] = useState(false);
  useEffect(() => {
    if (near) return;
    const node = ref.current;
    if (!node || typeof IntersectionObserver === "undefined") {
      setNear(true);
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) setNear(true);
      },
      { rootMargin: "300px" },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [ref, near]);
  return near;
}

/** Tell the frame this widget has nothing worth a card. */
export function useWidgetEmpty(empty: boolean) {
  const { setEmpty } = useContext(WidgetContext);
  useEffect(() => {
    setEmpty(empty);
  }, [empty, setEmpty]);
}

/** A widget's data: shared with any other widget wanting the same `key`, and
 * not asked for until the card is near the viewport. `pending` is what to
 * render while it is in flight or after it failed. */
export function useWidgetData<T>(
  key: string,
  load: () => Promise<T>,
  enabled = true,
): Loaded<T> & { pending: ReactNode } {
  const { near } = useContext(WidgetContext);
  const state = useData(key, load, near && enabled);
  const pending = state.error ? (
    <p className="error">{state.error}</p>
  ) : (
    <p className="muted">Loading…</p>
  );
  return { ...state, pending };
}

/** One broken widget shows its error in its own card, not instead of the page. */
class WidgetErrorBoundary extends Component<{ children: ReactNode }, { message: string | null }> {
  state: { message: string | null } = { message: null };

  static getDerivedStateFromError(error: unknown) {
    return { message: error instanceof Error ? error.message : String(error) };
  }

  render() {
    if (this.state.message) {
      return <p className="error">This widget failed: {this.state.message}</p>;
    }
    return this.props.children;
  }
}

/** The card around a widget: its title, its own loading and error states, and
 * the edit-mode bar above it. */
export function WidgetFrame({
  widget,
  title,
  untitled,
  cardClass,
  editing,
  controls,
  cellRef,
  lifted,
  children,
}: {
  widget: DashboardWidget;
  title: string;
  untitled?: boolean;
  cardClass?: string;
  editing: boolean;
  controls?: ReactNode;
  /** The grid cell, which the drag hit-tests against. */
  cellRef?: (node: HTMLDivElement | null) => void;
  /** Being dragged: this cell is where it will land. The card gives way to a
   * placeholder, and the frame stays mounted so the handle keeps the pointer
   * capture the drag depends on. */
  lifted?: { height: number };
  children: ReactNode;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const near = useNearViewport(ref);
  const [empty, setEmpty] = useState(false);
  const context = useMemo<WidgetContextValue>(() => ({ near, setEmpty }), [near]);

  const hidden = empty && !editing;
  const cls = ["dash-cell", `size-${widget.size}`, hidden ? "dash-hidden" : ""]
    .filter(Boolean)
    .join(" ");

  const setNode = (node: HTMLDivElement | null) => {
    ref.current = node;
    cellRef?.(node);
  };

  if (lifted) {
    return (
      <div className={cls} ref={setNode}>
        {controls}
        <div
          className="dash-placeholder"
          style={{ minHeight: `${Math.max(lifted.height, 80)}px` }}
        >
          {title}
        </div>
      </div>
    );
  }

  return (
    <div className={cls} ref={setNode}>
      {controls}
      <div className={cardClass ? `card ${cardClass}` : "card"}>
        {(!untitled || editing) && <h2>{title}</h2>}
        <WidgetErrorBoundary>
          <WidgetContext.Provider value={context}>
            {near ? children : <p className="muted">Loading…</p>}
          </WidgetContext.Provider>
        </WidgetErrorBoundary>
        {/* The widget itself renders nothing when it is empty. */}
        {empty && editing && <p className="muted">Nothing to show yet.</p>}
      </div>
    </div>
  );
}
