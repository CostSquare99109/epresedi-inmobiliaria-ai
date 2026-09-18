import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { backend, type PropertyDTO } from "@/lib/backend";
import { PageHeader } from "@/components/PageHeader";
import { PropertyForm } from "@/app/propiedades/nueva/PropertyForm";

interface PageProps {
  params: Promise<{ id: string }>;
}

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { id } = await params;
  try {
    const prop = await backend<PropertyDTO>(`/properties/${id}`);
    return { title: `Editar ${prop.title}` };
  } catch {
    return { title: "Editar propiedad" };
  }
}

export default async function EditarPropiedad({ params }: PageProps) {
  const { id } = await params;
  let property: PropertyDTO | null = null;
  let error = "";

  try {
    property = await backend<PropertyDTO>(`/properties/${id}`);
  } catch (e) {
    error = e instanceof Error ? e.message : "Error cargando propiedad";
  }

  if (!property) {
    notFound();
  }

  return (
    <>
      <PageHeader
        title="Editar propiedad"
        description={`Modifica la información de ${property?.title} (${property?.code})`}
      />
      <PropertyForm mode="edit" initialData={property} propertyId={id} />
    </>
  );
}