import type { Metadata } from "next";
import { PageHeader } from "@/components/PageHeader";
import { ProjectForm } from "./ProjectForm";

export const metadata: Metadata = { title: "Nuevo proyecto" };

export default function NuevoProyecto() {
  return (
    <>
      <PageHeader
        title="Nuevo proyecto"
        description="Crea un nuevo proyecto para agrupar propiedades relacionadas."
      />
      <ProjectForm mode="create" />
    </>
  );
}