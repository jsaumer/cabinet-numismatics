// The dashboard layout: one ordered list of widget instances.

export type WidgetSize = "full" | "half" | "third";

/** An option value as the layout stores it. Unknown keys are dropped and bad
 * values replaced by the default when the server reads the layout back. */
export type WidgetOptionValue = string | number | null;

export type WidgetOptions = Record<string, WidgetOptionValue>;

export interface DashboardWidget {
  id: string; // unique in the layout, made by the client
  type: string;
  size: WidgetSize;
  title: string | null; // null = the widget's own title
  options: WidgetOptions;
}

export interface DashboardLayout {
  version: number;
  widgets: DashboardWidget[];
  is_default: boolean; // nothing saved: this is the built-in layout
}
