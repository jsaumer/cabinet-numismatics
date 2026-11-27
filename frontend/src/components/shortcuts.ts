import { useSyncExternalStore } from "react";

// The single-key shortcuts (J, K, E, N on the collection, "/" for search)
// can be turned off, per browser. A shortcut that is one character with no
// modifier collides with speech input and with other tools' own keys, so it
// has to be something a person can switch off. Arrow keys, Enter, and Escape
// are not affected: they aren't characters.

const KEY = "cabinet.shortcuts";
const listeners = new Set<() => void>();

export function shortcutsEnabled(): boolean {
  try {
    return window.localStorage.getItem(KEY) !== "off";
  } catch {
    return true;
  }
}

export function setShortcutsEnabled(on: boolean) {
  try {
    if (on) window.localStorage.removeItem(KEY);
    else window.localStorage.setItem(KEY, "off");
  } catch {
    /* storage refused: the choice lasts for this page view only */
  }
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** Whether the single-key shortcuts are on, kept current when the setting
 * changes. */
export function useShortcutsEnabled(): boolean {
  return useSyncExternalStore(subscribe, shortcutsEnabled);
}
