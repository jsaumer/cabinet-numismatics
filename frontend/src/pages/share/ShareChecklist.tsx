import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api, ShareChecklistSlot, ShareManifest } from "../../api";

/** A checklist link's slots: filled ones only, since a share never shows a
 * want list (services/share.py's filled_slots). A slot links to its piece
 * when the share includes one, plain text when it was ticked by hand with
 * none on record. */
export default function ShareChecklist({ token, manifest }: { token: string; manifest: ShareManifest }) {
  const [slots, setSlots] = useState<ShareChecklistSlot[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setSlots(null);
    setError(null);
    api
      .shareChecklist(token)
      .then((view) => setSlots(view.slots))
      .catch((e: Error) => setError(e.message));
  }, [token]);

  return (
    <div className="share-list">
      <p className="muted">
        {manifest.filled ?? 0} of {manifest.total ?? 0} filled.
      </p>
      {error && <p className="error">{error}</p>}
      {!slots && !error && <p className="muted">Loading…</p>}
      {slots && slots.length === 0 && <p className="empty">Nothing filled here yet.</p>}
      {slots && slots.length > 0 && (
        <ul className="share-checklist">
          {slots.map((slot) => (
            <li key={slot.position}>
              {slot.item_id ? (
                <Link to={`/s/${token}/items/${slot.item_id}`}>{slot.label}</Link>
              ) : (
                <span>{slot.label}</span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
