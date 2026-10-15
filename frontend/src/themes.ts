/** The colour themes (v0.35.0). The keys must match the backend's
 * routers/appearance.THEMES and the data-palette blocks in styles.css; the
 * swatches are only for the picker in Settings (header, page, card, accent,
 * chart), the real colours live in styles.css. */

export type ThemeKey = "bronze" | "silver" | "album" | "ledger";

export interface ThemeInfo {
  key: ThemeKey;
  label: string;
  description: string;
  swatches: { light: string[]; dark: string[] };
}

export const DEFAULT_THEME: ThemeKey = "bronze";

export const THEMES: ThemeInfo[] = [
  {
    key: "bronze",
    label: "Bronze",
    description: "Warm surfaces and a bronze accent. The default.",
    swatches: { light: ["#211d17", "#f7f4ee", "#fffdf9", "#7c5c1e", "#9a7a35"], dark: ["#0d0b09", "#12100d", "#1c1915", "#b8934a", "#c9a45c"] },
  },
  {
    key: "silver",
    label: "Silver",
    description: "Cool steel grays with a pewter-blue accent.",
    swatches: { light: ["#1f242b", "#f3f4f6", "#ffffff", "#4a5a70", "#5e6f86"], dark: ["#0b0d10", "#0f1114", "#171a1f", "#9fb2c9", "#9fb2c9"] },
  },
  {
    key: "album",
    label: "Album",
    description: "The green baize of a cabinet drawer, with a brass accent.",
    swatches: { light: ["#1d3a2e", "#f2f5f2", "#fbfdfb", "#2f5d48", "#3f7a5f"], dark: ["#0a120e", "#0d1612", "#13201a", "#c9a755", "#c9a755"] },
  },
  {
    key: "ledger",
    label: "Ledger",
    description: "Ink on white paper with one oxblood accent, under a light header.",
    swatches: { light: ["#ffffff", "#f6f6f4", "#ffffff", "#7d2e2e", "#3b3b38"], dark: ["#0b0b0b", "#121212", "#1a1a1a", "#d77b70", "#cfcfcb"] },
  },
];

export const isThemeKey = (value: unknown): value is ThemeKey =>
  THEMES.some((t) => t.key === value);
