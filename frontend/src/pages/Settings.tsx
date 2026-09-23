import { ComponentType } from "react";
import { NavLink, useParams } from "react-router-dom";

import AboutSection from "./settings/About";
import AccountSection from "./settings/Account";
import AlertsSection from "./settings/Alerts";
import BackupsSection from "./settings/Backups";
import GeneralSection from "./settings/General";
import PricingSection from "./settings/Pricing";
import { SETTINGS_SECTIONS, useSettings } from "./settings/shared";

const SECTION_KEYS = new Set(SETTINGS_SECTIONS.map((s) => s.key));

const SECTION_COMPONENTS: Record<string, ComponentType> = {
  general: GeneralSection,
  pricing: PricingSection,
  backups: BackupsSection,
  alerts: AlertsSection,
  account: AccountSection,
  about: AboutSection,
};

/** Settings, split into routed sections (v0.30.2): a section nav beside (or,
 * on a narrow screen, above) the section's own content. An unknown section
 * falls back to General. */
export default function Settings() {
  const { section } = useParams<{ section: string }>();
  const key = section && SECTION_KEYS.has(section) ? section : "general";
  const Content = SECTION_COMPONENTS[key];

  // Fetched here only for the "secrets cleared" notice, which applies
  // regardless of which section is open.
  const { settings } = useSettings();

  return (
    <>
      <div className="detail-header">
        <h1>Settings</h1>
      </div>
      {settings && settings.secrets_cleared.length > 0 && (
        <p className="error">
          Re-enter: {settings.secrets_cleared.join(", ")}. Each was stored without this
          deployment's encryption, so Cabinet cleared it rather than use it.
        </p>
      )}
      <div className="settings-shell">
        <nav className="settings-nav" aria-label="Settings sections">
          {SETTINGS_SECTIONS.map((s) => (
            <NavLink key={s.key} to={s.path} className={key === s.key ? "active" : undefined}>
              {s.label}
            </NavLink>
          ))}
        </nav>
        <div className="settings-content">
          <Content />
        </div>
      </div>
    </>
  );
}
