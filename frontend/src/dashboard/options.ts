// Widget options: how the options form describes a field, and how a widget
// reads one. The server validates the same set and replaces a bad value with
// the default, so a reader only has to cope with a missing key.

import type { WidgetOptions } from "../api";

export type OptionField =
  | {
      key: string;
      label: string;
      kind: "choice";
      choices: { value: string | number; label: string }[];
    }
  | { key: string; label: string; kind: "count"; min: number; max: number; hint?: string }
  | { key: string; label: string; kind: "tag" }
  | { key: string; label: string; kind: "set" };

/** A string option, or the default when it is absent or empty. */
export function optionText(options: WidgetOptions, key: string, fallback: string): string {
  const value = options[key];
  return typeof value === "string" && value.trim() ? value : fallback;
}

/** A number option, or the default when it is absent or not a number. */
export function optionNumber(options: WidgetOptions, key: string, fallback: number): number {
  const value = options[key];
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

/** An optional string option: null rather than a default. */
export function optionOrNull(options: WidgetOptions, key: string): string | null {
  const value = options[key];
  return typeof value === "string" && value.trim() ? value : null;
}

/** An optional id option: null rather than a default. */
export function optionIdOrNull(options: WidgetOptions, key: string): number | null {
  const value = options[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}
