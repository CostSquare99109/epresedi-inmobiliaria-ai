import Link from "next/link";
import { EmptyState } from "@/components/EmptyState";

export default function NotFound() {
  return (
    <div className="card section-gap">
      <EmptyState
        icon="dashboard"
        title="Página no encontrada"
        description="La sección que buscas no existe en el panel. Utiliza la navegación lateral para volver a la operación."
        action={
          <Link href="/" className="btn btn-secondary">
            Volver al panel general
          </Link>
        }
      />
    </div>
  );
}
