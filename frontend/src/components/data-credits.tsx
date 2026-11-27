import { useEffect, useState } from "react";
import { useLocation } from "react-router-dom";

import { api, DataCredit } from "../api";

/** The credits a data source's terms ask for on every page that shows its
 * data, under the page's content: today PCGS's, once anything from PCGS is
 * held. The server owns the wording (`services/credits.py`); the agreement
 * asks for at least 10-point type, which `.data-credits` keeps. It prints
 * with the reports, so it carries no `no-print`. */
export function DataCredits() {
  const [credits, setCredits] = useState<DataCredit[]>([]);
  const { pathname } = useLocation();

  // Asked again on each page: switching a source on in Settings, or a first
  // PCGS lookup, makes one due.
  useEffect(() => {
    let stale = false;
    api
      .dataCredits()
      .then((list) => {
        if (!stale) setCredits(list);
      })
      .catch(() => undefined);
    return () => {
      stale = true;
    };
  }, [pathname]);

  if (credits.length === 0) return null;
  return (
    <footer className="data-credits">
      {credits.map((credit) => (
        <p key={credit.source}>
          <a href={credit.url} target="_blank" rel="noreferrer">
            {credit.name}
          </a>
          : {credit.notice}
        </p>
      ))}
    </footer>
  );
}
