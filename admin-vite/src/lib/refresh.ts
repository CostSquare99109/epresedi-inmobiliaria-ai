import { useEffect } from "react";

const REFRESH_EVENT = "admin:refresh";

/** Solicita a la página activa que vuelva a consultar el backend.
 *
 * Equivalente SPA de `router.refresh()` de Next.js / `revalidatePath`: los
 * datos se vuelven a pedir y el contenido actualizado ES el feedback.
 */
export function requestRefresh(): void {
  window.dispatchEvent(new CustomEvent(REFRESH_EVENT));
}

/** Registra un refetch de la página mientras esté montada. */
export function useOnRefresh(onRefresh: () => void): void {
  useEffect(() => {
    const handler = () => onRefresh();
    window.addEventListener(REFRESH_EVENT, handler);
    return () => window.removeEventListener(REFRESH_EVENT, handler);
  }, [onRefresh]);
}