import { useEffect } from "react";

const BASE = "Epresedi Inmobiliaria";

/** Equivalente SPA de `metadata.title` de Next.js (template «%s · Epresedi Inmobiliaria»). */
export function usePageTitle(title?: string): void {
  useEffect(() => {
    document.title = title ? `${title} · ${BASE}` : BASE;
  }, [title]);
}