import { CSSProperties, ReactNode } from "react";

/** An error a person has to hear about: announced by a screen reader the
 * moment it appears (`role="alert"`), and nothing at all while there is
 * none. Every error message in the app that comes and goes is one of these,
 * so a new page can't forget the role.
 *
 * A warning that is part of the page from the start (a notice about where a
 * key is stored, say) is not an alert: reading it out on every visit would
 * be noise. Those stay plain `className="error"` text. */
export function ErrorNote({
  children,
  inline = false,
  style,
}: {
  children: ReactNode;
  /** Sits inside a line of controls: a span, not a paragraph. */
  inline?: boolean;
  style?: CSSProperties;
}) {
  if (children === null || children === undefined || children === false || children === "") {
    return null;
  }
  const Tag = inline ? "span" : "p";
  return (
    <Tag className="error" role="alert" style={style}>
      {children}
    </Tag>
  );
}

/** Something that went right, or is under way: announced politely
 * (`role="status"`), never interrupting. `tone` is the look: muted text, or
 * the green of a gain for "it worked". */
export function StatusNote({
  children,
  tone = "muted",
  style,
}: {
  children: ReactNode;
  tone?: "muted" | "gain";
  style?: CSSProperties;
}) {
  if (children === null || children === undefined || children === false || children === "") {
    return null;
  }
  return (
    <p className={tone} role="status" style={style}>
      {children}
    </p>
  );
}
