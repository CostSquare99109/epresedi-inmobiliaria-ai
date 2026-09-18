import type { Metadata } from "next";
import { backend, type AdminUserDTO } from "@/lib/backend";
import { PageHeader } from "@/components/PageHeader";
import { EmptyState } from "@/components/EmptyState";
import { ErrorBanner } from "@/components/ErrorBanner";
import { RefreshButton } from "@/components/RefreshButton";
import { Icon } from "@/components/icons";
import Link from "next/link";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Usuarios administrativos" };

interface PageProps {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

export default async function Usuarios({ searchParams }: PageProps) {
  const sp = await searchParams;
  const q = (sp.q as string)?.trim() || "";

  let users: AdminUserDTO[] = [];
  let error = "";
  try {
    const data = await backend<{ users: AdminUserDTO[] }>("/admin-users");
    users = data.users;
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  const visible = q
    ? users.filter(
        (u) =>
          u.name.toLowerCase().includes(q.toLowerCase()) ||
          u.email.toLowerCase().includes(q.toLowerCase())
      )
    : users;

  const roleLabels: Record<string, string> = {
    superadmin: "Superadmin",
    admin: "Admin",
    editor: "Editor",
    asesor: "Asesor",
  };

  return (
    <>
      <PageHeader
        title="Usuarios administrativos"
        description="Gestión de cuentas de acceso al panel: roles, permisos y estado."
        actions={
          <>
            <Link href="/usuarios/nueva" className="btn btn-primary">
              <Icon name="plus" size={16} />
              Nuevo usuario
            </Link>
            <RefreshButton label="Recargar" />
          </>
        }
      />

      {error && <ErrorBanner message={error} />}

      <section className="card" aria-label="Listado de usuarios administrativos">
        <div className="card-head">
          <div className="toolbar">
            <div className="toolbar-filters">
              <form method="get" action="/usuarios" role="search" className="search-form">
                <span className="search-field">
                  <Icon name="search" size={14} />
                  <input
                    type="search"
                    name="q"
                    defaultValue={q}
                    placeholder="Buscar por nombre o email…"
                    aria-label="Búsqueda general"
                  />
                </span>
                <button type="submit" className="btn btn-secondary">
                  Buscar
                </button>
              </form>
            </div>
            <span className="toolbar-meta">{visible.length} usuario{visible.length === 1 ? "" : "s"}</span>
          </div>
        </div>

        {visible.length === 0 ? (
          <EmptyState
            bordered
            icon="users"
            title={q ? "Sin usuarios" : "Sin usuarios todavía"}
            description={
              q
                ? "Ningún usuario coincide con la búsqueda."
                : "Crea el primer usuario administrativo para comenzar."
            }
            action={
              q ? (
                <Link href="/usuarios" className="btn btn-secondary">
                  Limpiar búsqueda
                </Link>
              ) : (
                <Link href="/usuarios/nueva" className="btn btn-primary">
                  <Icon name="plus" size={14} />
                  Crear usuario
                </Link>
              )
            }
          />
        ) : (
          <div className="table-wrap">
            <table>
              <caption className="visually-hidden">
                Listado de usuarios administrativos con nombre, email, rol, estado y último acceso
              </caption>
              <thead>
                <tr>
                  <th>Usuario</th>
                  <th>Email</th>
                  <th>Rol</th>
                  <th>Estado</th>
                  <th>Último acceso</th>
                  <th>Acciones</th>
                </tr>
              </thead>
              <tbody>
                {visible.map((u) => (
                  <tr key={u.id}>
                    <td>
                      <div className="cell-main">{u.name}</div>
                      <div className="cell-sub">ID: {u.id.slice(0, 8)}…</div>
                    </td>
                    <td>{u.email}</td>
                    <td>
                      <span className={`status-badge status-${u.role === "superadmin" ? "success" : u.role === "admin" ? "warning" : u.role === "editor" ? "info" : "neutral"}`}>
                        {roleLabels[u.role] || u.role}
                      </span>
                    </td>
                    <td>
                      <span className={u.is_active ? "status-active" : "status-inactive"}>
                        {u.is_active ? "Activo" : "Inactivo"}
                      </span>
                    </td>
                    <td>
                      {u.last_login_at ? (
                        <>
                          <div className="cell-main">{new Date(u.last_login_at).toLocaleDateString()}</div>
                          <div className="cell-sub">{new Date(u.last_login_at).toLocaleTimeString()}</div>
                        </>
                      ) : (
                        <span className="muted">Nunca</span>
                      )}
                    </td>
                    <td>
                      <div className="btn-row">
                        <Link href={`/usuarios/${u.id}/editar`} className="btn btn-secondary btn-sm">
                          <Icon name="edit" size={14} /> Editar
                        </Link>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  );
}