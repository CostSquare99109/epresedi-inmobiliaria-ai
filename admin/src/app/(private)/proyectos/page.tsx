import type { Metadata } from "next";
import { backend, type ProjectDTO } from "@/lib/backend";
import { PageHeader } from "@/components/PageHeader";
import { EmptyState } from "@/components/EmptyState";
import { ErrorBanner } from "@/components/ErrorBanner";
import { RefreshButton } from "@/components/RefreshButton";
import { DeleteButton } from "@/components/DeleteButton";
import { Icon } from "@/components/icons";
import Link from "next/link";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Proyectos" };

interface PageProps {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

export default async function Proyectos({ searchParams }: PageProps) {
  const sp = await searchParams;
  const q = (sp.q as string)?.trim() || "";

  let projects: ProjectDTO[] = [];
  let error = "";
  try {
    const data = await backend<{ projects: ProjectDTO[] }>("/projects");
    projects = data.projects;
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  const visible = q
    ? projects.filter(
        (p) =>
          p.name.toLowerCase().includes(q.toLowerCase()) ||
          p.city.toLowerCase().includes(q.toLowerCase()) ||
          p.description.toLowerCase().includes(q.toLowerCase())
      )
    : projects;

  return (
    <>
      <PageHeader
        title="Proyectos"
        description="Agrupaciones de propiedades por desarrollo o zona."
        actions={
          <>
            <Link href="/proyectos/nueva" className="btn btn-primary">
              <Icon name="plus" size={16} />
              Nuevo proyecto
            </Link>
            <RefreshButton label="Recargar" />
          </>
        }
      />

      {error && <ErrorBanner message={error} />}

      <section className="card" aria-label="Listado de proyectos">
        <div className="card-head">
          <div className="toolbar">
            <div className="toolbar-filters">
              <form method="get" action="/proyectos" role="search" className="search-form">
                <span className="search-field">
                  <Icon name="search" size={14} />
                  <input
                    type="search"
                    name="q"
                    defaultValue={q}
                    placeholder="Buscar por nombre, ciudad, descripción…"
                    aria-label="Búsqueda general"
                  />
                </span>
                <button type="submit" className="btn btn-secondary">
                  Buscar
                </button>
              </form>
            </div>
            <span className="toolbar-meta">{visible.length} proyecto{visible.length === 1 ? "" : "s"}</span>
          </div>
        </div>

        {visible.length === 0 ? (
          <EmptyState
            bordered
            icon="folder"
            title={q ? "Sin proyectos" : "Sin proyectos todavía"}
            description={
              q
                ? "Ningún proyecto coincide con la búsqueda. Prueba con otros términos."
                : "Crea tu primer proyecto para agrupar propiedades."
            }
            action={
              q ? (
                <Link href="/proyectos" className="btn btn-secondary">
                  Limpiar búsqueda
                </Link>
              ) : (
                <Link href="/proyectos/nueva" className="btn btn-primary">
                  <Icon name="plus" size={14} />
                  Crear proyecto
                </Link>
              )
            }
          />
        ) : (
          <div className="table-wrap">
            <table>
              <caption className="visually-hidden">
                Listado de proyectos con nombre, ciudad, cantidad de propiedades y fechas
              </caption>
              <thead>
                <tr>
                  <th>Proyecto</th>
                  <th className="table-responsive-hide-xs">Ciudad</th>
                  <th className="num table-responsive-hide-xs">Propiedades</th>
                  <th className="table-responsive-hide-sm">Creado</th>
                  <th className="table-responsive-hide-sm">Actualizado</th>
                  <th>Acciones</th>
                </tr>
              </thead>
              <tbody>
                {visible.map((p) => (
                  <tr key={p.id}>
                    <td>
                      <div className="cell-main">{p.name}</div>
                      {p.description && <div className="cell-sub">{p.description.slice(0, 80)}</div>}
                    </td>
                    <td className="table-responsive-hide-xs">{p.city || "—"}</td>
                    <td className="num table-responsive-hide-xs">{p.property_count}</td>
                    <td className="table-responsive-hide-sm">
                      <div className="cell-main">{new Date(p.created_at).toLocaleDateString()}</div>
                      <div className="cell-sub">{new Date(p.created_at).toLocaleTimeString()}</div>
                    </td>
                    <td className="table-responsive-hide-sm">
                      <div className="cell-main">{new Date(p.updated_at).toLocaleDateString()}</div>
                      <div className="cell-sub">{new Date(p.updated_at).toLocaleTimeString()}</div>
                    </td>
                    <td>
                      <div className="btn-row">
                        <Link href={`/proyectos/${p.id}/editar`} className="btn btn-secondary btn-sm">
                          <Icon name="edit" size={14} /> Editar
                        </Link>
                        <DeleteButton
                          name={p.name}
                          href={`/api/proxy/projects/${p.id}?_method=DELETE`}
                          ariaLabel={`Eliminar ${p.name}`}
                        />
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