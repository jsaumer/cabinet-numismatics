import { useSyncExternalStore } from "react";

import { currentPalette, subscribePalette } from "./theme";

/** The Cabinet coin in the current theme's colors (v0.35.2): one file per
 * theme in public/, written by scripts/theme_icons.py. */
export function Logo({ size }: { size: number }) {
  const palette = useSyncExternalStore(subscribePalette, currentPalette);
  return <img src={`/logo-${palette}.svg`} alt="" width={size} height={size} />;
}
