import { useCallback, useEffect, useRef } from "react";
import { useBlocker } from "react-router-dom";

export const UNSAVED_MESSAGE = "Leave this page? What you typed hasn't been saved.";

/** Asks before unsaved work is lost: on a navigation inside the app (the
 * sidebar, the header search, Back, a keyboard shortcut) and on a reload or
 * a closed tab, where the browser shows its own words.
 *
 * `dirty` is the page's own answer to "is there something to lose". Call the
 * returned `allow()` right before a navigation the page itself makes after a
 * successful save, or that save would be asked about too. */
export function useUnsavedGuard(dirty: boolean, message: string = UNSAVED_MESSAGE) {
  const allowed = useRef(false);
  const live = useRef(dirty);
  live.current = dirty;
  if (!dirty) allowed.current = false; // a clean page needs no pass, and gets no stale one

  const blocker = useBlocker(
    ({ currentLocation, nextLocation }) =>
      live.current && !allowed.current && currentLocation.pathname !== nextLocation.pathname,
  );

  useEffect(() => {
    if (blocker.state !== "blocked") return;
    if (window.confirm(message)) blocker.proceed();
    else blocker.reset();
  }, [blocker, message]);

  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => {
      if (allowed.current) return;
      event.preventDefault();
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  const allow = useCallback(() => {
    allowed.current = true;
  }, []);
  return { allow };
}
