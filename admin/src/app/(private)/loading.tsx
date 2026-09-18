import { LoadingState } from "@/components/LoadingState";

/** Estado de carga a nivel de ruta (App Router). */
export default function Loading() {
  return (
    <>
      <div className="skeleton skeleton-title" aria-hidden="true" />
      <div className="skeleton skeleton-row" style={{ width: "55%" }} aria-hidden="true" />
      <div className="card section-gap">
        <LoadingState rows={5} label="Cargando la sección…" />
      </div>
    </>
  );
}
