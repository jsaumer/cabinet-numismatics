import { useEffect, useState } from "react";

import { SourceStatus, ValueStrategy } from "../../api";
import { Section, SavedTick, SettingRow, useSavedTick, useSettings } from "./shared";

/** Settings → General: display currency, melt cadence, the blended-value
 * strategy, and the trash's automatic clear-out. */
export default function GeneralSection() {
  const { settings, error, note, saving, apply } = useSettings();
  const [currency, setCurrency] = useState("");
  const [cadence, setCadence] = useState("");
  const [valueStrategy, setValueStrategy] = useState<ValueStrategy>("latest");
  const [preferredSource, setPreferredSource] = useState("");
  const [retentionSaved, triggerRetentionSaved] = useSavedTick();

  useEffect(() => {
    if (!settings) return;
    setCurrency(settings.display_currency);
    setCadence(String(settings.reestimate_days));
    setValueStrategy(settings.value_strategy);
    setPreferredSource(settings.preferred_source ?? "");
  }, [settings]);

  if (error && !settings) return <p className="error">{error}</p>;
  if (!settings) return <p className="muted">Loading…</p>;

  return (
    <Section
      title="General"
      description="Amounts in other currencies convert at cached daily ECB rates; anything unconvertible is excluded from totals and counted, never guessed. The value strategy controls this single blended number; the item page always shows every source's own latest value."
    >
      {error && <p className="error">{error}</p>}
      {note && <p className="muted">{note}</p>}
      <SettingRow
        label="Display currency"
        help="Totals, the dashboard, and the reports convert into this."
        htmlFor="display-currency"
      >
        <input
          id="display-currency"
          value={currency}
          maxLength={3}
          style={{ width: "5rem" }}
          onChange={(e) => setCurrency(e.target.value)}
        />
      </SettingRow>
      <SettingRow
        label="Melt refresh cadence"
        help="Days between automatic melt-value refreshes; 0 disables them."
        htmlFor="melt-cadence"
      >
        <input
          id="melt-cadence"
          type="number"
          min={0}
          max={365}
          value={cadence}
          style={{ width: "6rem" }}
          onChange={(e) => setCadence(e.target.value)}
        />
      </SettingRow>
      <SettingRow
        label="Value shown in the list, dashboard, and export"
        help="The one blended number; the item page always shows every source's own latest value."
        htmlFor="value-strategy"
      >
        <select
          id="value-strategy"
          value={valueStrategy}
          onChange={(e) => setValueStrategy(e.target.value as ValueStrategy)}
        >
          <option value="latest">Latest estimate (any source)</option>
          <option value="preferred_source">Preferred source (falls back to latest)</option>
          <option value="average">Average of sources</option>
        </select>
      </SettingRow>
      {valueStrategy === "preferred_source" && (
        <SettingRow label="Preferred source" htmlFor="preferred-source">
          <select
            id="preferred-source"
            value={preferredSource}
            onChange={(e) => setPreferredSource(e.target.value)}
          >
            <option value="" disabled>choose…</option>
            {settings.sources.map((s: SourceStatus) => (
              <option key={s.key} value={s.key}>{s.name}</option>
            ))}
          </select>
        </SettingRow>
      )}
      <SettingRow label="" help="Currency, cadence, and the value strategy save together.">
        <button
          className="primary"
          disabled={saving}
          onClick={() =>
            apply(
              {
                display_currency: currency.trim().toUpperCase(),
                reestimate_days: Number(cadence),
                value_strategy: valueStrategy,
                preferred_source: valueStrategy === "preferred_source" ? (preferredSource || null) : null,
              },
              "General settings saved.",
            )
          }
        >
          Save
        </button>
      </SettingRow>

      <SettingRow label="Empty the trash automatically">
        <select
          value={settings.trash_retention_days}
          disabled={saving}
          onChange={(e) => {
            const days = Number(e.target.value);
            apply({ trash_retention_days: days }, null).then((ok) => ok && triggerRetentionSaved());
          }}
        >
          <option value={0}>Never</option>
          <option value={7}>After 7 days</option>
          <option value={30}>After 30 days</option>
          <option value={90}>After 90 days</option>
          <option value={365}>After a year</option>
        </select>
        <SavedTick shown={retentionSaved} />
      </SettingRow>
    </Section>
  );
}
