import type { ComponentType } from "react";
import { PACKAGING_LABELS } from "../api";
import type { Item, ItemType } from "../api";
import { BullionIcon, CoinIcon, NoteIcon, SetIcon } from "./icons";

/** What the interface calls each item type, and its stand-in icon. The one
 *  place a type is described: a new type is an entry here, and TypeScript
 *  refuses a `Record<ItemType, ...>` that leaves one out. */
interface TypeInfo {
  /** One piece: the form's choice, bulk edit, the import default. */
  one: string;
  /** Several: the list filter and the type breakdown. */
  many: string;
  /** Shown where a piece has no photo (the item page, share pages). */
  icon: ComponentType;
}

export const TYPE_INFO: Record<ItemType, TypeInfo> = {
  coin: { one: "Coin", many: "Coins", icon: CoinIcon },
  note: { one: "Note", many: "Notes", icon: NoteIcon },
  bullion: { one: "Bar or round", many: "Bars and rounds", icon: BullionIcon },
  mint_set: { one: "Proof or mint set", many: "Proof and mint sets", icon: SetIcon },
};

/** The short word a type's badge prints. */
export const typeBadge = (type: ItemType) => (type === "mint_set" ? "set" : type);

/** A set's kind, from its strike. */
export const setKind = (strike: Item["strike"]) =>
  strike === "proof" ? "Proof set" : strike === "specimen" ? "Specimen set" : "Uncirculated set";

/** A set's packaging in one line: "Sealed, with box and certificate",
 *  "Complete, with box, no certificate". Null when nothing is recorded. */
export function packagingLine(
  item: Pick<Item, "packaging" | "has_box" | "has_coa">,
): string | null {
  if (!item.packaging && !item.has_box && !item.has_coa) return null;
  const extras =
    item.has_box && item.has_coa
      ? "with box and certificate"
      : item.has_box
        ? "with box, no certificate"
        : item.has_coa
          ? "with certificate, no box"
          : "no box or certificate";
  return item.packaging ? `${PACKAGING_LABELS[item.packaging]}, ${extras}` : extras.charAt(0).toUpperCase() + extras.slice(1);
}

/** Every type, in the order the interface lists them. */
export const ITEM_TYPES = Object.keys(TYPE_INFO) as ItemType[];

/** The stand-in icon for a type; an unknown one (a newer server) gets the
 *  coin's rather than nothing. */
export function TypeIcon({ type }: { type: ItemType }) {
  const Icon = TYPE_INFO[type]?.icon ?? CoinIcon;
  return <Icon />;
}
