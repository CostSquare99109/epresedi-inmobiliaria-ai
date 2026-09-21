import type { Metadata } from "next";
import { backend, type AuditLogDTO } from "@/lib/backend";
import { PageHeader } from "@/components/PageHeader";
import { EmptyState } from "@/components/EmptyState";
import { ErrorBanner } from "@/components/ErrorBanner";
import { RefreshButton } from "@/components/RefreshButton";
import { FilterTabs, Pagination } from "@/components/TableControls";
import { Icon } from "@/components/icons";
import { formatDateTime, timeAgo } from "@/lib/format";
import { singleParam, buildHref } from "@/lib/params";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Auditoría administrativa" };

const PAGE_SIZE = 25;

interface PageProps {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

export default async function Auditoria({ searchParams }: PageProps) {
  const sp = await searchParams;
  const accion = singleParam(sp.accion);
  const entidad = singleParam(sp.entidad);
  const q = singleParam(sp.q)?.trim() || "";
  const pagina = Math.max(1, parseInt(singleParam(sp.pagina) || "1", 10) || 1);

  const baseParams: Record<string, string | undefined> = {
    accion: accion || undefined,
    entidad: entidad || undefined,
    q: q || undefined,
  };

  let events: AuditLogDTO[] = [];
  let total = 0;
  let error = "";
  try {
    const queryParams = new URLSearchParams({
      limit: String(PAGE_SIZE),
      offset: String((pagina - 1) * PAGE_SIZE),
    });
    if (accion) queryParams.set("action", accion);
    if (entidad) queryParams.set("entity", entidad);
    const data = await backend<{ total: number; events: AuditLogDTO[] }>(`/audit-log?${queryParams.toString()}`);
    events = data.events ?? [];
    total = data.total ?? events.length;
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  const actions = [...new Set(events.map(e => e.action))].sort();
  const entities = [...new Set(events.map(e => e.entity))].sort();

  return (
    <>
      <PageHeader
        title="Auditoría administrativa"
        description="Registro de acciones realizadas por usuarios del panel: quién, qué, cuándo y resultado."
        actions={<RefreshButton label="Recargar" />}
      />

      {error && <ErrorBanner message={error} />}

      <section className="card" aria-label="Log de auditoría administrativa">
        <div className="card-head">
          <div className="toolbar">
            <div className="toolbar-filters">
              <form method="get" action="/auditoria" role="search" className="search-form">
                <span className="search-field">
                  <Icon name="search" size={14} />
                  <input
                    type="search"
                    name="q"
                    defaultValue={q}
                    placeholder="Buscar en metadatos, actor, entidad…"
                    aria-label="Búsqueda general"
                  />
                </span>
                <button type="submit" className="btn btn-secondary">Buscar</button>
              </form>
              {actions.length > 0 && (
                <div className="filter-tabs" role="navigation" aria-label="Filtrar por acción">
                  <a href={buildHref("/auditoria", baseParams, { accion: undefined })} className={`filter-tab${!accion ? " active" : ""}`} aria-current={!accion ? "true" : undefined}>
                    Todas las acciones
                  </a>
                  {actions.map((a) => (
                    <a key={a} href={buildHref("/auditoria", baseParams, { accion: a })} className={`filter-tab${accion === a ? " active" : ""}`} aria-current={accion === a ? "true" : undefined}>
                      {a}
                    </a>
                  ))}
                </div>
              )}
              {entities.length > 0 && (
                <div className="filter-tabs" role="navigation" aria-label="Filtrar por entidad">
                  <a href={buildHref("/auditoria", baseParams, { entidad: undefined })} className={`filter-tab${!entidad ? " active" : ""}`} aria-current={!entidad ? "true" : undefined}>
                    Todas las entidades
                  </a>
                  {entities.map((e) => (
                    <a key={e} href={buildHref("/auditoria", baseParams, { entidad: e })} className={`filter-tab${entidad === e ? " active" : ""}`} aria-current={entidad === e ? "true" : undefined}>
                      {e}
                    </a>
                  ))}
                </div>
              )}
            </div>
            <span className="toolbar-meta">{total} evento{total === 1 ? "" : "s"}</span>
          </div>
        </div>

        {events.length === 0 ? (
          <EmptyState
            bordered
            icon="shield"
            title={q || accion || entidad ? "Sin eventos" : "Sin auditoría todavía"}
            description={
              q || accion || entidad
                ? "Ningún evento coincide con los filtros aplicados."
                : "Las acciones administrativas se registrarán aquí automáticamente."
            }
            action={
              q || accion || entidad ? (
                <a href="/auditoria" className="btn btn-secondary">Limpiar filtros</a>
              ) : undefined
            }
          />
        ) : (
          <>
            <div className="table-wrap">
              <table>
                <caption className="visually-hidden">Log de auditoría: acción, entidad, actor, resultado y fecha</caption>
                <thead>
                  <tr>
                    <th>Acción</th>
                    <th className="table-responsive-hide-xs">Entidad</th>
                    <th className="table-responsive-hide-sm">ID entidad</th>
                    <th className="table-responsive-hide-xs">Actor</th>
                    <th>Resultado</th>
                    <th>Fecha</th>
                    <th className="table-responsive-hide-md">Detalles</th>
                  </tr>
                </thead>
                <tbody>
                  {events.map((e) => (
                    <tr key={e.id}>
                      <td>
                        <div className="cell-main">{e.action}</div>
                      </td>
                      <td className="table-responsive-hide-xs">{e.entity}</td>
                      <td className="table-responsive-hide-sm">
                        <div className="cell-main" style={{ fontFamily: "monospace", fontSize: "12px" }}>
                          {e.entity_id || "—"}
                        </div>
                      </td>
                      <td className="table-responsive-hide-xs">
                        <div className="cell-main">{e.actor_name || e.actor_email || "sistema"}</div>
                        <div className="cell-sub">{e.actor_email}</div>
                      </td>
                      <td>
                        <span className={`badge tone-${e.result === "success" ? "success" : "danger"}`}>
                          {e.result}
                        </span>
                      </td>
                      <td>
                        <div className="cell-main">{formatDateTime(e.created_at)}</div>
                        <div className="cell-sub">{timeAgo(e.created_at)}</div>
                      </td>
                      <td className="table-responsive-hide-md">
                        <details>
                          <summary className="cell-sub" style={{ cursor: "pointer" }}>Ver metadatos</summary>
                          <pre style={{ marginTop: "var(--sp-2)", fontSize: "11px", maxHeight: "150px", overflow: "auto" }}>
                            {JSON.stringify(e.metadata, null, 2)}
                            {e.error_message && `\nError: ${e.error_message}`}
                          </pre>
                        </details>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pagination
              basePath="/auditoria"
              params={baseParams}
              page={pagina}
              hasMore={(pagina * PAGE_SIZE) < total}
              shown={events.length}
              itemName="eventos"
            />
          </>
        )}
      </section>
    </>
  );
}