import { useEffect, useState } from "react";

import { api } from "../api";
import { SavedTick, useSavedTick } from "../pages/settings/shared";
import { DEFAULT_THEME, isThemeKey, ThemeKey, THEMES } from "../themes";
import { applyPalette } from "./theme";

/** Settings → General's theme cards. A choice applies at once and is saved
 * on the server (PUT /api/appearance, admin but no password again), so it
 * follows the owner to every device; light or dark stays the header's
 * toggle, per browser. */
export function ThemePicker() {
  const [current, setCurrent] = useState<ThemeKey | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, triggerSaved] = useSavedTick();
  const mode = document.documentElement.dataset.theme === "light" ? "light" : "dark";

  useEffect(() => {
    api
      .appearance()
      .then((a) => setCurrent(isThemeKey(a.theme) ? a.theme : DEFAULT_THEME))
      .catch((e: Error) => setError(e.message));
  }, []);

  async function choose(key: ThemeKey) {
    if (key === current || busy) return;
    const before = current;
    setCurrent(key);
    applyPalette(key);
    setBusy(true);
    setError(null);
    try {
      await api.setAppearance(key);
      triggerSaved();
    } catch (e) {
      setCurrent(before);
      if (before) applyPalette(before);
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="theme-picker">
      <div className="theme-cards" role="radiogroup" aria-label="Theme">
        {THEMES.map((t) => (
          <button
            key={t.key}
            type="button"
            role="radio"
            aria-checked={current === t.key}
            className={`theme-card${current === t.key ? " on" : ""}`}
            disabled={current === null}
            onClick={() => void choose(t.key)}
          >
            <span className="theme-swatches" aria-hidden="true">
              {t.swatches[mode].map((c, i) => (
                <i key={i} style={{ background: c }} />
              ))}
            </span>
            <span className="theme-name">{t.label}</span>
            <span className="theme-about">{t.description}</span>
          </button>
        ))}
      </div>
      <SavedTick shown={saved} />
      {error && <p className="error">{error}</p>}
    </div>
  );
}
