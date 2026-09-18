import type { Metadata } from "next";
import { PageHeader } from "@/components/PageHeader";
import { PropertyForm } from "./PropertyForm";

export const metadata: Metadata = { title: "Nueva propiedad" };

export default function NuevaPropiedad() {
  return (
    <>
      <PageHeader
        title="Nueva propiedad"
        description="Crea una nueva propiedad completando la información básica, características, ubicación y descripción."
      />
      <PropertyForm mode="create" />
    </>
  );
}