import type { Metadata } from "next";
import { PageHeader } from "@/components/PageHeader";
import { CitaCreate } from "./CitaCreate";

export const metadata: Metadata = { title: "Nueva cita" };

export default function NuevaCita() {
  return (
    <>
      <PageHeader
        title="Nueva cita"
        description="Programa una nueva visita seleccionando propiedad, cliente y horario disponible."
      />
      <CitaCreate />
    </>
  );
}