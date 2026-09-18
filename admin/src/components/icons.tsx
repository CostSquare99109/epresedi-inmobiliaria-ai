/** Iconografía única: SVG monolínea 24×24, trazo 1.7, currentColor. */

import type { SVGProps } from "react";

const PATHS: Record<string, React.ReactNode> = {
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
  chat: (
    <>
      <path d="M21 14.5a2 2 0 0 1-2 2H8l-4.5 4V5.5a2 2 0 0 1 2-2H19a2 2 0 0 1 2 2z" />
    </>
  ),
  file: (
    <>
      <path d="M14 3H7a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" />
      <path d="M14 3v5h5" />
      <path d="M9 13h6M9 17h6" />
    </>
  ),
  list: (
    <>
      <path d="M8.5 6h12M8.5 12h12M8.5 18h12" />
      <path d="M3.5 6h.01M3.5 12h.01M3.5 18h.01" />
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
