import type { Metadata } from "next";
import { backend, type CmsContentDTO } from "@/lib/backend";
import { PageHeader } from "@/components/PageHeader";
import { EmptyState } from "@/components/EmptyState";
import { ErrorBanner } from "@/components/ErrorBanner";
import { RefreshButton } from "@/components/RefreshButton";
import { Icon } from "@/components/icons";
import Link from "next/link";
import { singleParam } from "@/lib/params";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Contenido CMS" };

const GROUPS = ["general", "branding", "contact", "legal", "seo", "banners", "faqs"];

interface PageProps {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

export default async function Contenido({ searchParams }: PageProps) {
  const sp = await searchParams;
  const q = (sp.q as string)?.trim() || "";
  const grupo = singleParam(sp.grupo);

  let contents: CmsContentDTO[] = [];
  let error = "";
  try {
    const data = await backend<{ contents: CmsContentDTO[] }>("/cms-content");
    contents = data.contents ?? [];
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  const visible = contents.filter((c) => {
    if (q && !c.key.toLowerCase().includes(q.toLowerCase()) && !c.label.toLowerCase().includes(q.toLowerCase())) return false;
    if (grupo && c.group !== grupo) return false;
    return true;
  });

  const byGroup = contents.reduce<Record<string, number>>((acc, c) => {
    acc[c.group] = (acc[c.group] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <>
      <PageHeader
        title="Contenido CMS"
        description="Contenido administrable del sitio público: textos, banners, FAQs, legales, branding."
        actions={
          <>
            <Link href="/contenido/nueva" className="btn btn-primary">
              <Icon name="plus" size={16} />
              Nuevo contenido
            </Link>
            <RefreshButton label="Recargar" />
          </>
        }
      />

      {error && <ErrorBanner message={error} />}

      <section className="card" aria-label="Listado de contenido CMS">
        <div className="card-head">
          <div className="toolbar">
            <div className="toolbar-filters">
              <form method="get" action="/contenido" role="search" className="search-form">
                <span className="search-field">
                  <Icon name="search" size={14} />
                  <input
                    type="search"
                    name="q"
                    defaultValue={q}
                    placeholder="Buscar por clave, etiqueta…"
                    aria-label="Búsqueda general"
                  />
                </span>
                <button type="submit" className="btn btn-secondary">Buscar</button>
              </form>
              <div className="filter-tabs" role="navigation" aria-label="Filtrar por grupo">
                {["", ...GROUPS].map((g) => {
                  const active = grupo === g;
                  const params = new URLSearchParams({ ...(q && { q }), grupo: g || "" });
                  return (
                    <Link
                      key={g || "__all"}
                      href={`/contenido?${params.toString()}`}
                      className={`filter-tab${active ? " active" : ""}`}
                      aria-current={active ? "true" : undefined}
                    >
                      {g || "Todos"}
                      <span className="count">{byGroup[g] ?? 0}</span>
                    </Link>
                  );
                })}
              </div>
            </div>
            <span className="toolbar-meta">{visible.length} elemento{visible.length === 1 ? "" : "s"}</span>
          </div>
        </div>

        {visible.length === 0 ? (
          <EmptyState
            bordered
            icon="file"
            title={q || grupo ? "Sin contenido" : "Sin contenido todavía"}
            description={
              q || grupo
                ? "Ningún elemento coincide con los filtros."
                : "Crea tu primer contenido administrable (banner, FAQ, texto legal, etc.)."
            }
            action={
              q || grupo ? (
                <Link href="/contenido" className="btn btn-secondary">
                  Limpiar filtros
                </Link>
              ) : (
                <Link href="/contenido/nueva" className="btn btn-primary">
                  <Icon name="plus" size={14} />
                  Crear contenido
                </Link>
              )
            }
          />
        ) : (
          <div className="table-wrap">
            <table>
              <caption className="visually-hidden">Listado de contenido CMS con clave, tipo, grupo y estado</caption>
              <thead>
                <tr>
                  <th>Clave</th>
                  <th>Etiqueta</th>
                  <th>Tipo</th>
                  <th>Grupo</th>
                  <th>Público</th>
                  <th>Actualizado</th>
                  <th>Acciones</th>
                </tr>
              </thead>
              <tbody>
                {visible.map((c) => (
                  <tr key={c.id}>
                    <td>
                      <div className="cell-main" style={{ fontFamily: "monospace", fontSize: "12px" }}>{c.key}</div>
                    </td>
                    <td>
                      <div className="cell-main">{c.label || "—"}</div>
                      <div className="cell-sub">{c.description.slice(0, 60)}{c.description.length > 60 ? "…" : ""}</div>
                    </td>
                    <td>
                      <span className="badge">{c.type}</span>
                    </td>
                    <td>{c.group}</td>
                    <td>{c.is_public ? "Sí" : "No"}</td>
                    <td>
                      <div className="cell-main">{new Date(c.updated_at).toLocaleDateString()}</div>
                      <div className="cell-sub">{new Date(c.updated_at).toLocaleTimeString()}</div>
                    </td>
                    <td>
                      <div className="btn-row">
                        <Link href={`/contenido/${c.id}/editar`} className="btn btn-secondary btn-sm">
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