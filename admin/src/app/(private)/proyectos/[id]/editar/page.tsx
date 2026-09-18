import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { backend, type ProjectDTO } from "@/lib/backend";
import { PageHeader } from "@/components/PageHeader";
import { ProjectForm } from "@/app/proyectos/nueva/ProjectForm";

interface PageProps {
  params: Promise<{ id: string }>;
}

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { id } = await params;
  try {
    const project = await backend<ProjectDTO>(`/projects/${id}`);
    return { title: `Editar ${project.name}` };
  } catch {
    return { title: "Editar proyecto" };
  }
}

export default async function EditarProyecto({ params }: PageProps) {
  const { id } = await params;
  let project: ProjectDTO | null = null;
  let error = "";

  try {
    project = await backend<ProjectDTO>(`/projects/${id}`);
  } catch (e) {
    error = e instanceof Error ? e.message : "Error cargando proyecto";
  }

  if (!project) {
    notFound();
  }

  return (
    <>
      <PageHeader
        title="Editar proyecto"
        description={`Modifica la información de ${project.name}`}
      />
      <ProjectForm mode="edit" initialData={project} projectId={id} />
    </>
  );
}