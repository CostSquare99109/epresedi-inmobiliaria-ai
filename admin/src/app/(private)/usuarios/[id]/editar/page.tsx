import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { backend, type AdminUserDTO } from "@/lib/backend";
import { PageHeader } from "@/components/PageHeader";
import { UserForm } from "@/app/usuarios/nueva/UserForm";

interface PageProps {
  params: Promise<{ id: string }>;
}

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { id } = await params;
  try {
    const user = await backend<AdminUserDTO>(`/admin-users/${id}`);
    return { title: `Editar ${user.name}` };
  } catch {
    return { title: "Editar usuario" };
  }
}

export default async function EditarUsuario({ params }: PageProps) {
  const { id } = await params;
  let user: AdminUserDTO | null = null;
  let error = "";

  try {
    const data = await backend<{ users: AdminUserDTO[] }>("/admin-users");
    user = data.users.find(u => u.id === id) || null;
  } catch (e) {
    error = e instanceof Error ? e.message : "Error cargando usuario";
  }

  if (!user) {
    notFound();
  }

  return (
    <>
      <PageHeader
        title="Editar usuario"
        description={`Modifica la información de ${user.name} (${user.email})`}
      />
      <UserForm mode="edit" initialData={user} userId={id} />
    </>
  );
}