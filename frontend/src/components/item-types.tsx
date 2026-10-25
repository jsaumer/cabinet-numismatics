import type { ComponentType } from "react";
import type { ItemType } from "../api";
import { BullionIcon, CoinIcon, NoteIcon } from "./icons";

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
};

/** Every type, in the order the interface lists them. */
export const ITEM_TYPES = Object.keys(TYPE_INFO) as ItemType[];

/** The stand-in icon for a type; an unknown one (a newer server) gets the
 *  coin's rather than nothing. */
export function TypeIcon({ type }: { type: ItemType }) {
  const Icon = TYPE_INFO[type]?.icon ?? CoinIcon;
  return <Icon />;
}
