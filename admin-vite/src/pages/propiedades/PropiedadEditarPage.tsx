"use client";

import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { backend, type PropertyDTO } from "../../api/client";
import { PageHeader } from "../../components/PageHeader";
import { PropertyForm } from "./PropertyForm";
import { ErrorBanner } from "../../components/ErrorBanner";
import { LoadingState } from "../../components/LoadingState";

export function PropiedadEditarPage() {
  const params = useParams();
  const [property, setProperty] = useState<PropertyDTO | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      try {
        const prop = await backend<PropertyDTO>(`/properties/${params.id}`);
        setProperty(prop);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Error cargando propiedad");
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [params.id]);

  if (loading) {
    return (
      <>
        <PageHeader title="Editar propiedad" description="Cargando..." />
        <div className="card">
          <div className="card-body">
            <LoadingState rows={6} label="Cargando propiedad…" variant="blocks" />
          </div>
        </div>
      </>
    );
  }

  if (!property) {
    return (
      <>
        <PageHeader title="Error" />
        <ErrorBanner message={error || "Propiedad no encontrada"} />
      </>
    );
  }

  return (
    <>
      <PageHeader
        title="Editar propiedad"
        description={`Modifica la información de ${property.title} (${property.code})`}
      />
      <PropertyForm mode="edit" initialData={property} propertyId={params.id} />
    </>
  );
}