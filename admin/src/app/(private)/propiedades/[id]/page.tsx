import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { backend, type PropertyDTO } from "@/lib/backend";
import { PageHeader } from "@/components/PageHeader";
import { PropertyDetail } from "./PropertyDetail";

interface PageProps {
  params: Promise<{ id: string }>;
}

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { id } = await params;
  try {
    const prop = await backend<PropertyDTO>(`/properties/${id}`);
    return { title: `${prop.title} (${prop.code})` };
  } catch {
    return { title: "Propiedad no encontrada" };
  }
}

export default async function PropiedadDetalle({ params }: PageProps) {
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
        title={property.title}
        description={`${property.code} · ${property.property_type} · ${property.operation === "SALE" ? "Venta" : "Arriendo"} · ${property.city}`}
      />
      <PropertyDetail property={property} error={error} />
    </>
  );
}