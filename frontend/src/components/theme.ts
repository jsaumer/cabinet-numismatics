import { DEFAULT_THEME, isThemeKey, ThemeKey } from "../themes";

export function initialTheme(): "light" | "dark" {
  const stored = localStorage.getItem("theme");
  if (stored === "light" || stored === "dark") return stored;
  return "dark"; // the default look; the header toggle switches and remembers
}

export function applyTheme(theme: "light" | "dark") {
  document.documentElement.dataset.theme = theme;
  localStorage.setItem("theme", theme);
  syncBrowserChrome();
}

const PALETTE_KEY = "cabinet.palette";

/** The color theme this browser last showed. The server holds the real
 * choice (GET /api/appearance); this copy lets the sign-in page and the first
 * paint use it before anyone is signed in. */
export function initialPalette(): ThemeKey {
  try {
    const stored = localStorage.getItem(PALETTE_KEY);
    if (isThemeKey(stored)) return stored;
  } catch {
    // storage refused: the default theme
  }
  return DEFAULT_THEME;
}

export function applyPalette(palette: ThemeKey) {
  document.documentElement.dataset.palette = palette;
  try {
    localStorage.setItem(PALETTE_KEY, palette);
  } catch {
    // a browser that refuses storage still gets the theme for this visit
  }
  syncBrowserChrome();
  listeners.forEach((listener) => listener());
}

/** The theme on the page now, for components that draw something per theme
 * (the logo). Read through useSyncExternalStore with subscribePalette. */
export function currentPalette(): ThemeKey {
  const palette = document.documentElement.dataset.palette;
  return isThemeKey(palette) ? palette : DEFAULT_THEME;
}

const listeners = new Set<() => void>();

export function subscribePalette(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** What the browser draws around the page follows the theme too (v0.35.2):
 * the tab icon (SVG for most browsers, .ico for the rest) and the mobile
 * address bar's color, which is the header's. */
function syncBrowserChrome() {
  const palette = currentPalette();
  const svg = document.querySelector<HTMLLinkElement>('link[rel="icon"][type="image/svg+xml"]');
  if (svg) svg.href = `/logo-${palette}.svg`;
  const ico = document.querySelector<HTMLLinkElement>('link[rel="icon"][sizes="any"]');
  if (ico) ico.href = `/favicon-${palette}.ico`;
  const bar = document.querySelector<HTMLMetaElement>('meta[name="theme-color"]');
  const header = getComputedStyle(document.documentElement).getPropertyValue("--header-bg").trim();
  if (bar && header) bar.content = header;
}
