import { DEFAULT_THEME, isThemeKey, ThemeKey } from "../themes";

export function initialTheme(): "light" | "dark" {
  const stored = localStorage.getItem("theme");
  if (stored === "light" || stored === "dark") return stored;
  return "dark"; // the default look; the header toggle switches and remembers
}

export function applyTheme(theme: "light" | "dark") {
  document.documentElement.dataset.theme = theme;
  localStorage.setItem("theme", theme);
}

const PALETTE_KEY = "cabinet.palette";

/** The colour theme this browser last showed. The server holds the real
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
}
