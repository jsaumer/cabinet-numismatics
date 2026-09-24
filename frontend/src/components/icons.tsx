import { ReactNode } from "react";

/** Small inline icons, drawn here so they look the same on every system
 * (emoji don't) and nothing loads from outside the app. They take the text
 * colour and size of whatever they sit in. */
function Icon({ children }: { children: ReactNode }) {
  return (
    <svg
      className="icon"
      viewBox="0 0 24 24"
      width="1em"
      height="1em"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {children}
    </svg>
  );
}

/** Stands in for a coin with no photo. */
export const CoinIcon = () => (
  <Icon>
    <circle cx="12" cy="12" r="8.5" />
    <circle cx="12" cy="12" r="4.5" />
  </Icon>
);

/** Stands in for a note with no photo. */
export const NoteIcon = () => (
  <Icon>
    <rect x="2.5" y="6" width="19" height="12" rx="1.5" />
    <circle cx="12" cy="12" r="2.6" />
  </Icon>
);

/** Stands in for a bar or round with no photo. */
export const BullionIcon = () => (
  <Icon>
    <path d="M5 8.5L7 5.5h10l2 3v9l-2 3H7l-2-3z" />
    <path d="M7.3 8.5h9.4" />
  </Icon>
);

/** Settings, as sliders: a drawn gear at this size reads as a sun. */
export const SettingsIcon = () => (
  <Icon>
    <path d="M3 6.5h9M17 6.5h4M3 12h3M11 12h10M3 17.5h11M19 17.5h2" />
    <circle cx="14.5" cy="6.5" r="2.3" />
    <circle cx="8.5" cy="12" r="2.3" />
    <circle cx="16.5" cy="17.5" r="2.3" />
  </Icon>
);

export const MoonIcon = () => (
  <Icon>
    <path d="M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5z" />
  </Icon>
);

export const SunIcon = () => (
  <Icon>
    <circle cx="12" cy="12" r="4" />
    <path d="M12 2v2.5M12 19.5V22M2 12h2.5M19.5 12H22M4.9 4.9l1.8 1.8M17.3 17.3l1.8 1.8M4.9 19.1l1.8-1.8M17.3 6.7l1.8-1.8" />
  </Icon>
);

export const TrashIcon = () => (
  <Icon>
    <path d="M4 7h16M9.5 7V4.5h5V7M6.5 7l1 13h9l1-13M10 11v5.5M14 11v5.5" />
  </Icon>
);

export const CameraIcon = () => (
  <Icon>
    <path d="M3 8.5h4l1.5-2.5h7L17 8.5h4v11H3z" />
    <circle cx="12" cy="13.5" r="3.2" />
  </Icon>
);

export const WebcamIcon = () => (
  <Icon>
    <rect x="2.5" y="6.5" width="13" height="11" rx="2" />
    <path d="M15.5 11l6-3.5v9l-6-3.5" />
  </Icon>
);

export const UploadIcon = () => (
  <Icon>
    <path d="M12 16V4.5M7 9l5-5 5 5M4 15.5v4h16v-4" />
  </Icon>
);

export const LockIcon = () => (
  <Icon>
    <rect x="5" y="11" width="14" height="9.5" rx="2" />
    <path d="M8 11V8a4 4 0 0 1 8 0v3" />
  </Icon>
);

export const ChevronDownIcon = () => (
  <Icon>
    <path d="M6 9.5l6 6 6-6" />
  </Icon>
);

/** The only place a dashboard widget can be picked up and dragged. */
export const GripIcon = () => (
  <Icon>
    <path d="M9 6h.01M15 6h.01M9 12h.01M15 12h.01M9 18h.01M15 18h.01" strokeWidth="2.6" />
  </Icon>
);

export const ArrowUpIcon = () => (
  <Icon>
    <path d="M12 20V5M6 11l6-6 6 6" />
  </Icon>
);

export const ArrowDownIcon = () => (
  <Icon>
    <path d="M12 4v15M6 13l6 6 6-6" />
  </Icon>
);

export const PlusIcon = () => (
  <Icon>
    <path d="M12 5v14M5 12h14" />
  </Icon>
);

export const CloseIcon = () => (
  <Icon>
    <path d="M6 6l12 12M18 6L6 18" />
  </Icon>
);

/** Duplicate: one card copied from another. */
export const CopyIcon = () => (
  <Icon>
    <rect x="9" y="9" width="11" height="11" rx="2" />
    <path d="M15 5.5H6a1.5 1.5 0 0 0-1.5 1.5v9" />
  </Icon>
);

export const SlidersIcon = () => (
  <Icon>
    <path d="M4 8h10M18 8h2M4 16h4M12 16h8" />
    <circle cx="16" cy="8" r="2.2" />
    <circle cx="10" cy="16" r="2.2" />
  </Icon>
);

export const EyeIcon = () => (
  <Icon>
    <path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z" />
    <circle cx="12" cy="12" r="3" />
  </Icon>
);

/** Sign-in provider glyphs (v0.33.0): simple monochrome marks, drawn the
 * same way as every other icon here (no external brand asset is fetched;
 * the CSP allows none). A custom OpenID Connect provider gets the generic
 * key. */
export const GoogleIcon = () => (
  <Icon>
    <path d="M4 12a8 8 0 0 1 8-8c2.1 0 3.9.75 5.3 2.05l-2.25 2.2A5 5 0 0 0 12 7.5a4.5 4.5 0 0 0 0 9 4.6 4.6 0 0 0 4.7-3.6h-4.7v-3h7.9c.1.5.15 1 .15 1.6 0 4.6-3.1 7.9-8 7.9A8 8 0 0 1 4 12z" />
  </Icon>
);

export const MicrosoftIcon = () => (
  <Icon>
    <rect x="3.5" y="3.5" width="7.7" height="7.7" />
    <rect x="12.8" y="3.5" width="7.7" height="7.7" />
    <rect x="3.5" y="12.8" width="7.7" height="7.7" />
    <rect x="12.8" y="12.8" width="7.7" height="7.7" />
  </Icon>
);

export const GitHubIcon = () => (
  <Icon>
    <path d="M12 3a9 9 0 0 0-2.85 17.54c.45.08.6-.2.6-.43v-1.68c-2.5.55-3.03-1.08-3.03-1.08-.4-1.05-1-1.32-1-1.32-.83-.56.06-.55.06-.55.9.06 1.38.93 1.38.93.8 1.38 2.1.98 2.6.75.08-.58.32-.98.57-1.2-2-.23-4.1-1-4.1-4.45 0-.98.35-1.79.92-2.42-.1-.23-.4-1.14.1-2.38 0 0 .76-.24 2.5.92a8.6 8.6 0 0 1 4.5 0c1.73-1.16 2.5-.92 2.5-.92.5 1.24.2 2.15.1 2.38.57.63.92 1.44.92 2.42 0 3.46-2.1 4.22-4.1 4.44.33.28.62.85.62 1.7v2.5c0 .24.15.52.6.43A9 9 0 0 0 12 3z" />
  </Icon>
);

export const KeyIcon = () => (
  <Icon>
    <circle cx="8" cy="15" r="3.5" />
    <path d="M10.5 12.5L18 5M15.5 7.5l2 2M18.5 4.5l2 2" />
  </Icon>
);

export const EyeOffIcon = () => (
  <Icon>
    <path d="M3 3l18 18M9.9 5.1A10.6 10.6 0 0 1 12 5.5c6 0 9.5 6.5 9.5 6.5a15.6 15.6 0 0 1-3.1 3.9M6.3 6.9C3.8 8.7 2.5 12 2.5 12S6 18.5 12 18.5a9.6 9.6 0 0 0 3.4-.6" />
    <path d="M14.6 14.6a3 3 0 0 1-4.2-4.2" />
  </Icon>
);
