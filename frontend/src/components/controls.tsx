import { ChangeEvent, ReactNode, useEffect, useRef, useState } from "react";

import { ChevronDownIcon } from "./icons";

/** A file picker that looks like the other buttons. The real input stays in
 * the label (hidden from sight, not from the keyboard or screen readers), so
 * clicking or pressing Enter on it opens the browser's picker as usual. */
export function FileButton({
  children,
  onFiles,
  accept,
  multiple,
  capture,
  disabled,
  primary,
  title,
}: {
  children: ReactNode;
  onFiles: (files: File[]) => void;
  accept?: string;
  multiple?: boolean;
  capture?: "environment" | "user";
  disabled?: boolean;
  primary?: boolean;
  title?: string;
}) {
  const change = (e: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.currentTarget.files ?? []);
    e.currentTarget.value = "";
    if (files.length) onFiles(files);
  };
  const cls = ["button", "file-button", primary ? "primary" : "", disabled ? "disabled" : ""]
    .filter(Boolean)
    .join(" ");
  return (
    <label className={cls} title={title}>
      {children}
      <input type="file" accept={accept} multiple={multiple} capture={capture}
        disabled={disabled} onChange={change} />
    </label>
  );
}

/** A button that opens a short list of links or actions. Closes on a click
 * anywhere else, on Escape, and after a choice. */
export function Menu({ label, children }: { label: ReactNode; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
    };
    const esc = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", esc);
    };
  }, [open]);

  return (
    <div className="menu" ref={ref}>
      <button type="button" aria-haspopup="menu" aria-expanded={open}
        onClick={() => setOpen(!open)}>
        {label} <ChevronDownIcon />
      </button>
      {open && (
        <div className="menu-items" role="menu" onClick={() => setOpen(false)}>
          {children}
        </div>
      )}
    </div>
  );
}
