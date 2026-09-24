"use client";

import { PropertyForm } from "./PropertyForm";
import { PageHeader } from "../../components/PageHeader";

export function PropiedadNuevaPage() {
  return (
    <>
      <PageHeader
        title="Nueva propiedad"
        description="Registra un nuevo inmueble en el inventario"
      />
      <PropertyForm mode="create" />
    </>
  );
}