import { AlertsCard } from "../../components/alerts";
import { useSettings } from "./shared";
import { ErrorNote } from "../../components/notes";

/** Settings → Alerts & metrics: the webhook, spot alerts, and /api/metrics.
 * AlertsCard already renders its own single-h2 card. */
export default function AlertsSection() {
  const { settings, error, saving, apply } = useSettings();

  if (error && !settings) return <ErrorNote>{error}</ErrorNote>;
  if (!settings) return <p className="muted">Loading…</p>;

  return <AlertsCard settings={settings} saving={saving} apply={apply} />;
}
