"use client";

import { PageHeader } from "@/components/PageHeader";
import { ErrorBanner } from "@/components/ErrorBanner";

/** Error boundary a nivel de ruta (App Router). */
export default function RouteError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <>
      <PageHeader
        title="Algo salió mal"
        description="No se pudo renderizar esta sección. Vuelve a intentarlo; si el problema persiste, verifica que el backend esté corriendo."
      />
      <ErrorBanner
        title="Error inesperado"
        message={error.digest ? `${error.message} (ref: ${error.digest})` : error.message}
        onRetry={reset}
        retryLabel="Reintentar"
      />
    </>
  );
}
