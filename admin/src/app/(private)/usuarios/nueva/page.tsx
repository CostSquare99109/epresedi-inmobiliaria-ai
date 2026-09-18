import type { Metadata } from "next";
import { PageHeader } from "@/components/PageHeader";
import { UserForm } from "./UserForm";

export const metadata: Metadata = { title: "Nuevo usuario" };

export default function NuevoUsuario() {
  return (
    <>
      <PageHeader
        title="Nuevo usuario administrativo"
        description="Crea una nueva cuenta de acceso al panel con rol y permisos."
      />
      <UserForm mode="create" />
    </>
  );
}