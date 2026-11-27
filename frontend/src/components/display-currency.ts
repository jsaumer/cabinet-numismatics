import { useEffect, useState } from "react";

import { api } from "../api";

/** The display currency from Settings, General, or null until it is known
 * (or when it can't be read). A new piece starts in it: the form, the quick
 * add, and "Add a run" all ask here. */
export function useDisplayCurrency(): string | null {
  const [currency, setCurrency] = useState<string | null>(null);
  useEffect(() => {
    let gone = false;
    api
      .getSettings()
      .then((s) => {
        if (!gone && s.display_currency) setCurrency(s.display_currency.toUpperCase());
      })
      .catch(() => {
        /* the form keeps its own default */
      });
    return () => {
      gone = true;
    };
  }, []);
  return currency;
}
