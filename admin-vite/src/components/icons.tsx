/** Iconografía única: SVG monolínea 24×24, trazo 1.7, currentColor. */

import type { SVGProps } from "react";

const PATHS = {
  home: (
    <>
      <path d="M3 9.5 12 3l9 6.5" />
      <path d="M5 8.5V20a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8.5" />
      <path d="M9.5 21v-6h5v6" />
    </>
  ),
  dashboard: (
    <>
      <rect x="3.5" y="3.5" width="7" height="7" rx="1" />
      <rect x="13.5" y="3.5" width="7" height="7" rx="1" />
      <rect x="3.5" y="13.5" width="7" height="7" rx="1" />
      <rect x="13.5" y="13.5" width="7" height="7" rx="1" />
    </>
  ),
  building: (
    <>
      <path d="M4.5 21V5a1 1 0 0 1 1-1h9a1 1 0 0 1 1 1v16" />
      <path d="M15.5 9.5H19a1 1 0 0 1 1 1V21" />
      <path d="M2.5 21h19" />
      <path d="M8 8h4M8 12h4M8 16h4" />
    </>
  ),
  calendar: (
    <>
      <rect x="3.5" y="5" width="17" height="16" rx="1.5" />
      <path d="M8 3v4M16 3v4M3.5 10.5h17" />
    </>
  ),
  "user-plus": (
    <>
      <path d="M15.5 21v-2a4 4 0 0 0-4-4h-6a4 4 0 0 0-4 4v2" />
      <circle cx="8.5" cy="7.5" r="3.5" />
      <path d="M19 8v6M22 11h-6" />
    </>
  ),
  menu: <path d="M3.5 6.5h17M3.5 12h17M3.5 17.5h17" />,
  x: <path d="M18 6 6 18M6 6l12 12" />,
  alert: (
    <>
      <path d="M10.3 4.1 2.2 17.6A2 2 0 0 0 3.9 20.6h16.2a2 2 0 0 0 1.7-3L13.7 4.1a2 2 0 0 0-3.4 0Z" />
      <path d="M12 9.5v4M12 17h.01" />
    </>
  ),
  refresh: (
    <>
      <path d="M21.5 4.5v5h-5" />
      <path d="M2.5 19.5v-5h5" />
      <path d="M4 9.5a8.5 8.5 0 0 1 14-3.2l3.5 3.2" />
      <path d="M20 14.5a8.5 8.5 0 0 1-14 3.2l-3.5-3.2" />
    </>
  ),
  upload: (
    <>
      <path d="M20.5 15.5v3a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2v-3" />
      <path d="M16.5 8 12 3.5 7.5 8" />
      <path d="M12 3.5V15" />
    </>
  ),
  trash: (
    <>
      <path d="M3.5 6.5h17" />
      <path d="M18.5 6.5V19a2 2 0 0 1-2 2h-9a2 2 0 0 1-2-2V6.5" />
      <path d="M8.5 6.5V5a2 2 0 0 1 2-2h3a2 2 0 0 1 2 2v1.5" />
      <path d="M10 11v6M14 11v6" />
    </>
  ),
  check: <path d="M20 6.5 9.5 17.5 4 12" />,
  "chevron-right": <path d="M9 18.5 15 12 9 5.5" />,
  "chevron-left": <path d="M15 18.5 9 12l6-6.5" />,
  search: (
    <>
      <circle cx="11" cy="11" r="6.5" />
      <path d="m20.5 20.5-4.8-4.8" />
    </>
  ),
  phone: (
    <path d="M6.6 3.5c.5 0 1 .3 1.2.8l1.3 2.8c.2.5.1 1.1-.3 1.5l-1.3 1.3a13.6 13.6 0 0 0 6.6 6.6l1.3-1.3c.4-.4 1-.5 1.5-.3l2.8 1.3c.5.2.8.7.8 1.2v2.3c0 .9-.7 1.6-1.6 1.5C9.9 20.6 3.4 14.1 2.8 5.1c-.1-.9.6-1.6 1.5-1.6z" />
  ),
  eye: (
    <>
      <path d="M2.5 12s3.5-6 9.5-6 9.5 6 9.5 6-3.5 6-9.5 6-9.5-6-9.5-6Z" />
      <circle cx="12" cy="12" r="2.5" />
    </>
  ),
  "eye-off": (
    <>
      <path d="M10.6 5.1A9.8 9.8 0 0 1 12 5c6 0 9.5 7 9.5 7a17.6 17.6 0 0 1-2.2 3.1" />
      <path d="M6.6 6.6A17.2 17.2 0 0 0 2.5 12s3.5 7 9.5 7a9.6 9.6 0 0 0 4-1" />
      <path d="M9.9 9.9a3 3 0 0 0 4.2 4.2" />
      <path d="m2.5 2.5 19 19" />
    </>
  ),
  edit: (
    <>
      <path d="M4 20h4L19.5 8.5a2.12 2.12 0 0 0-3-3L5 17v3Z" />
      <path d="m14.5 7.5 2 2" />
    </>
  ),
  folder: (
    <path d="M3.5 6.5A1.5 1.5 0 0 1 5 5h5l2 2.5h7.5A1.5 1.5 0 0 1 21 9v9.5a1.5 1.5 0 0 1-1.5 1.5h-14A1.5 1.5 0 0 1 4 18.5Z" />
  ),
  user: (
    <>
      <circle cx="12" cy="8" r="3.5" />
      <path d="M5 20v-.8a6 6 0 0 1 6-6h2a6 6 0 0 1 6 6v.8" />
    </>
  ),
  "log-in": (
    <>
      <path d="M14 4h4a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-4" />
      <path d="m10 8 4 4-4 4" />
      <path d="M14 12H3.5" />
    </>
  ),
  "log-out": (
    <>
      <path d="M10 4H6a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h4" />
      <path d="m14 8 4 4-4 4" />
      <path d="M18 12H9.5" />
    </>
  ),
  save: (
    <>
      <path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2Z" />
      <path d="M17 21v-8H7v8M7 3v5h8" />
    </>
  ),
  sliders: (
    <>
      <path d="M3.5 6.5h8M17 6.5h3.5M3.5 12h3M11 12h9.5M3.5 17.5h11M19 17.5h1.5" />
      <circle cx="15" cy="6.5" r="2" />
      <circle cx="9" cy="12" r="2" />
      <circle cx="17" cy="17.5" r="2" />
    </>
  ),
  info: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M12 11v5M12 7.5h.01" />
    </>
  ),
  "file-text": (
    <>
      <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8Z" />
      <path d="M14 3v5h5" />
      <path d="M9 13.5h6M9 17h6" />
    </>
  ),
  plus: <path d="M12 5v14M5 12h14" />,
  "map-pin": (
    <>
      <path d="M19.5 10.2c0 5-7.5 10.3-7.5 10.3S4.5 15.2 4.5 10.2a7.5 7.5 0 0 1 15 0Z" />
      <circle cx="12" cy="10" r="2.5" />
    </>
  ),
  "dollar-sign": (
    <>
      <path d="M12 2.5v19" />
      <path d="M16.5 6.5h-5a3.5 3.5 0 0 0 0 7h3a3.5 3.5 0 0 1 0 7h-6" />
    </>
  ),
  tag: (
    <>
      <path d="M20.6 13.4 13.4 20.6a2 2 0 0 1-2.8 0L2.5 12.5V2.5h10l8.1 8.1a2 2 0 0 1 0 2.8Z" />
      <circle cx="7.5" cy="7.5" r="1" />
    </>
  ),
  "arrow-left": <path d="M19 12H5M11 18l-6-6 6-6" />,
  image: (
    <>
      <rect x="3.5" y="4.5" width="17" height="15" rx="1.5" />
      <circle cx="9" cy="10" r="1.5" />
      <path d="m5 18 5.5-5.5 3 3L17 12l3.5 3.5" />
    </>
  ),
  star: (
    <path d="m12 3 2.7 5.6 6.1.8-4.5 4.2 1.1 6-5.4-3-5.4 3 1.1-6L3.2 9.4l6.1-.8Z" />
  ),
  toggle: (
    <>
      <rect x="2.5" y="7.5" width="19" height="9" rx="4.5" />
      <circle cx="16.5" cy="12" r="2.2" />
    </>
  ),
  expand: (
    <path d="M9 4H4v5M15 4h5v5M9 20H4v-5M15 20h5v-5" />
  ),
  car: (
    <>
      <path d="M5.5 11 7 6.8a1.5 1.5 0 0 1 1.4-1.1h7.2A1.5 1.5 0 0 1 17 6.8L18.5 11" />
      <rect x="4" y="11" width="16" height="6" rx="1.5" />
      <path d="M7 17v1.5M17 17v1.5" />
    </>
  ),
  "calendar-plus": (
    <>
      <rect x="3.5" y="5" width="17" height="16" rx="1.5" />
      <path d="M8 3v4M16 3v4M3.5 10.5h17" />
      <path d="M18 14v5M15.5 16.5h5" />
    </>
  ),
  bed: (
    <>
      <path d="M3 18v-7a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v7" />
      <path d="M3 18h18M5 9V7a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v2" />
    </>
  ),
  bath: (
    <>
      <path d="M4 12h16v2a5 5 0 0 1-5 5H9a5 5 0 0 1-5-5Z" />
      <path d="M6 12V6a2 2 0 0 1 4 0" />
      <path d="M8 19l-1 1.5M16 19l1 1.5" />
    </>
  ),
};

export type IconName = keyof typeof PATHS;

interface IconProps extends SVGProps<SVGSVGElement> {
  name: IconName;
  size?: number;
}

export function Icon({ name, size = 17, ...rest }: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.7}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      {...rest}
    >
      {PATHS[name]}
    </svg>
  );
}
