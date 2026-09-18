import type { Metadata } from "next";
import { PageHeader } from "@/components/PageHeader";
import { CmsContentForm } from "./CmsContentForm";

export const metadata: Metadata = { title: "Nuevo contenido CMS" };

export default function NuevoContenido() {
  return (
    <>
      <PageHeader
        title="Nuevo contenido CMS"
        description="Crea un nuevo elemento de contenido administrable para el sitio público."
      />
      <CmsContentForm mode="create" />
    </>
  );
}