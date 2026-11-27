import { ReactNode, useLayoutEffect, useRef } from "react";

/** The one modal: the browser's own <dialog>, opened with showModal().
 *
 * That gives every overlay the same four things without a library: focus
 * moves into it when it opens, Tab stays inside, the page behind is inert,
 * and focus goes back to whatever opened it when it closes. Escape and a
 * click on the backdrop ask `onClose`; the caller decides (an editor in the
 * middle of a save says no by doing nothing).
 *
 * `className` is the look: "modal" (a centered card on a dimmed page) or
 * "lightbox" (the full-screen photo viewer). The dialog element itself is
 * the full-viewport backdrop, so a click that lands on it, and not on
 * anything inside, is a click outside the content. */
export function Overlay({
  label,
  className = "modal",
  onClose,
  children,
}: {
  label: string;
  className?: string;
  onClose: () => void;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const close = useRef(onClose);
  close.current = onClose;

  useLayoutEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (!dialog.open) dialog.showModal();
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden"; // the page behind doesn't scroll
    return () => {
      document.body.style.overflow = previous;
      if (dialog.open) dialog.close(); // hands focus back to what opened it
    };
  }, []);

  return (
    <dialog
      ref={ref}
      className={`overlay ${className}`}
      aria-label={label}
      onCancel={(e) => {
        // Escape: ask, never close by itself.
        e.preventDefault();
        close.current();
      }}
      onClose={() => {
        // A browser may close a dialog on a second Escape whatever the
        // first was told. If the caller is keeping it open, open it again.
        close.current();
        window.setTimeout(() => {
          const dialog = ref.current;
          if (dialog && dialog.isConnected && !dialog.open) dialog.showModal();
        }, 0);
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget) close.current();
      }}
    >
      {children}
    </dialog>
  );
}
