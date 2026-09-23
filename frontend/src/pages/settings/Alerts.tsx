import { AlertsCard } from "../../components/alerts";
import { useSettings } from "./shared";

/** Settings → Alerts & metrics: the webhook, spot alerts, and /api/metrics.
 * AlertsCard already renders its own single-h2 card. */
export default function AlertsSection() {
  const { settings, error, saving, apply } = useSettings();

  if (error && !settings) return <p className="error">{error}</p>;
  if (!settings) return <p className="muted">Loading…</p>;

  return <AlertsCard settings={settings} saving={saving} apply={apply} />;
}
