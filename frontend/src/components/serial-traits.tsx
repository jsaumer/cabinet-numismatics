import { useEffect, useState } from "react";

import { api, SerialTrait } from "../api";

// The trait labels change only with a release, so one fetch serves the session.
let cached: Promise<SerialTrait[]> | null = null;

const loadTraits = () => {
  if (!cached) {
    cached = api.serialTraits().catch(() => {
      cached = null; // try again next time
      return [];
    });
  }
  return cached;
};

/** The fancy-serial traits the server knows, in its order; empty until loaded. */
export function useSerialTraits(): SerialTrait[] {
  const [traits, setTraits] = useState<SerialTrait[]>([]);
  useEffect(() => {
    let live = true;
    loadTraits().then((t) => live && setTraits(t));
    return () => {
      live = false;
    };
  }, []);
  return traits;
}

const fallbackLabel = (key: string) => key.replace(/_/g, " ");

/** Badges for a serial number's traits; past `max`, the rest become "+n". */
export function TraitBadges({
  traits,
  reference,
  max,
}: {
  traits: string[] | null | undefined;
  reference: SerialTrait[];
  max?: number;
}) {
  if (!traits?.length) return null;
  const info = (key: string) => reference.find((t) => t.key === key);
  const shown = max != null ? traits.slice(0, max) : traits;
  const rest = traits.slice(shown.length);
  return (
    <>
      {shown.map((key) => (
        <span key={key} className="badge trait" title={info(key)?.description}>
          {info(key)?.label ?? fallbackLabel(key)}
        </span>
      ))}
      {rest.length > 0 && (
        <span
          className="badge trait"
          title={rest.map((key) => info(key)?.label ?? fallbackLabel(key)).join(", ")}
        >
          +{rest.length}
        </span>
      )}
    </>
  );
}
