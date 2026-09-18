"use client";

import { useRouter } from "next/navigation";
import { Icon } from "./icons";

/**
 * Recarga los datos de la página (server render). El feedback real es la
 * actualización del contenido; sin estados falsos de "cargando".
 */
export function RefreshButton({ label = "Actualizar" }: { label?: string }) {
  const router = useRouter();
  return (
    <button
      type="button"
      className="btn btn-secondary"
      onClick={() => router.refresh()}
      title="Volver a consultar el backend"
    >
      <Icon name="refresh" size={15} />
      {label}
    </button>
  );
}
