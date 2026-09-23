// Share links (v0.32.0, SPEC_0320): read-only links to the collection, a
// set, or a checklist, opened without signing in. The admin routes are
// under "share-links" (ShareLink, ShareLinkCreate, ShareLinkPatch,
// NewShareLink); the public routes a link itself opens are under "share"
// (ShareManifest, ShareItem, ShareItemsPage, ShareChecklistSlot).

import type { Angle, CacSticker, ItemType } from "./items";

export type ShareKind = "collection" | "set" | "checklist";

// --- managing links (admin) --------------------------------------------------------

export interface ShareLink {
  id: string;
  kind: ShareKind;
  set_id: number | null;
  checklist_id: number | null;
  target_name: string | null;
  name: string;
  show_photos: boolean;
  show_grades: boolean;
  show_tags: boolean;
  show_notes: boolean;
  show_values: boolean;
  show_certs: boolean;
  created_at: string | null;
  created_by: string;
  last_opened_at: string | null;
  opens: number;
}

/** What creating or regenerating a link answers: the row plus the full URL,
 * shown this once. */
export interface NewShareLink extends ShareLink {
  url: string;
}

export interface ShareLinkCreate {
  kind: ShareKind;
  set_id?: number | null;
  checklist_id?: number | null;
  name: string;
  show_photos?: boolean;
  show_grades?: boolean;
  show_tags?: boolean;
  show_notes?: boolean;
  show_values?: boolean;
  show_certs?: boolean;
}

export interface ShareLinkPatch {
  name?: string;
  show_photos?: boolean;
  show_grades?: boolean;
  show_tags?: boolean;
  show_notes?: boolean;
  show_values?: boolean;
  show_certs?: boolean;
}

// --- opening a link (public, no sign-in) ---------------------------------------------

/** GET /api/share/{token}: what the link shares and how many pieces. */
export interface ShareManifest {
  kind: ShareKind;
  name: string;
  show_photos: boolean;
  show_grades: boolean;
  show_tags: boolean;
  show_notes: boolean;
  show_values: boolean;
  show_certs: boolean;
  item_count: number;
  filled?: number; // checklist links only
  total?: number; // checklist links only
}

export interface ShareItemPhoto {
  id: string;
  angle: Angle | null;
  has_thumbnail: boolean;
}

/** One piece through the share allowlist (services/share.py's item_view):
 * never a cost, a gain, a location, a document, a serial number, or a
 * custom field. The toggle-gated keys are optional, present only when the
 * link's matching show_* is on. */
export interface ShareItem {
  id: string;
  type: ItemType;
  country: string;
  denomination: string;
  year_label: string;
  mint_mark: string | null;
  series: string | null;
  variety: string | null;
  composition: string | null;
  weight_g: number | null;
  fineness: number | null;
  diameter_mm: number | null;
  width_mm: number | null;
  height_mm: number | null;
  shape: string | null;
  issuer: string | null;
  quantity: number;
  photos?: ShareItemPhoto[]; // show_photos
  grade_label?: string | null; // show_grades
  grade_details?: string | null;
  designations?: string[];
  cac_sticker?: CacSticker | null;
  cert_service?: string | null; // show_grades
  cert_number?: string | null; // show_certs
  tags?: string[]; // show_tags
  notes?: string | null; // show_notes
  value?: { amount: number; currency: string } | null; // show_values
}

export interface ShareItemsPage {
  items: ShareItem[];
  total: number;
}

/** A checklist link's filled slots only: a share never shows a want list. */
export interface ShareChecklistSlot {
  position: number;
  label: string;
  year: number | null;
  mint_mark: string | null;
  item_id: string | null; // null when the slot was ticked by hand, with no piece
}

export interface ShareChecklistView {
  slots: ShareChecklistSlot[];
}
