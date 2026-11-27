import { useEffect } from "react";

const APP = "Cabinet";

/** Names the browser tab, the history entry, and what a screen reader says
 * on arrival: "Stack · Cabinet". Every page calls it once. `null` leaves the
 * title alone, for a view shown inside another page (a piece open beside
 * the collection list). */
export function useTitle(title: string | null) {
  useEffect(() => {
    if (title === null) return;
    document.title = title ? `${title} · ${APP}` : APP;
  }, [title]);
}
