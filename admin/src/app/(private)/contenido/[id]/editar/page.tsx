import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { backend, type CmsContentDTO } from "@/lib/backend";
import { PageHeader } from "@/components/PageHeader";
import { CmsContentForm } from "@/app/contenido/nueva/CmsContentForm";

interface PageProps {
  params: Promise<{ id: string }>;
}

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { id } = await params;
  try {
    const content = await backend<CmsContentDTO>(`/cms-content/${id}`);
    return { title: `Editar ${content.label || content.key}` };
  } catch {
    return { title: "Editar contenido CMS" };
  }
}

export default async function EditarContenido({ params }: PageProps) {
  const { id } = await params;
  let content: CmsContentDTO | null = null;
  let error = "";

  try {
    const data = await backend<{ contents: CmsContentDTO[] }>("/cms-content");
    content = data.contents.find(c => c.id === id) || null;
  } catch (e) {
    error = e instanceof Error ? e.message : "Error cargando contenido";
  }

  if (!content) {
    notFound();
  }

  return (
    <>
      <PageHeader
        title="Editar contenido CMS"
        description={`Modifica ${content.label || content.key} (${content.type})`}
      />
      <CmsContentForm mode="edit" initialData={content} contentId={id} />
    </>
  );
}