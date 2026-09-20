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
