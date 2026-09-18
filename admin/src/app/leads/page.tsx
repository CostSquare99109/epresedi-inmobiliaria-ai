import type { Metadata } from "next";
import { backend, type LeadDTO } from "@/lib/backend";
import { PageHeader } from "@/components/PageHeader";
import { StatusBadge } from "@/components/StatusBadge";
import { EmptyState } from "@/components/EmptyState";
import { ErrorBanner } from "@/components/ErrorBanner";
import { RefreshButton } from "@/components/RefreshButton";
import { FilterTabs } from "@/components/TableControls";
import { Icon } from "@/components/icons";
import { statusMeta } from "@/lib/status";
import { formatDateTime, formatMoney, timeAgo } from "@/lib/format";
import { singleParam } from "@/lib/params";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Leads" };

const STATUSES = ["NEW", "CONTACTED", "INTERESTED", "VISIT_SCHEDULED", "NEGOTIATION", "CLOSED", "LOST"];

interface PageProps {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

export default async function Leads({ searchParams }: PageProps) {
  const sp = await searchParams;
  const estado = singleParam(sp.estado);

  let leads: LeadDTO[] = [];
  let error = "";
  try {
    const body = await backend<{ leads: LeadDTO[] }>("/leads");
    leads = [...body.leads].sort((a, b) => b.created_at.localeCompare(a.created_at));
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  const byStatus = leads.reduce<Record<string, number>>((acc, l) => {
    acc[l.status] = (acc[l.status] ?? 0) + 1;
    return acc;
  }, {});
  const visible = estado ? leads.filter((l) => l.status === estado) : leads;

  return (
    <>
      <PageHeader
        title="Leads"
        description="Prospectos captados por el asistente: contacto directo, estado comercial y presupuesto declarado."
        actions={<RefreshButton />}
      />

      {error && <ErrorBanner message={error} />}

      {!error && (
        <section className="card" aria-label="Listado de leads">
          <div className="card-head">
            <div className="toolbar">
              <div className="toolbar-filters">
                <FilterTabs
                  basePath="/leads"
                  params={{}}
                  paramName="estado"
                  current={estado}
                  options={[
                    { value: "", label: "Todos", count: leads.length },
                    ...STATUSES.map((s) => ({
                      value: s,
                      label: statusMeta(s).label,
                      count: byStatus[s] ?? 0,
                    })),
                  ]}
                  ariaLabel="Filtrar por estado del lead"
                />
              </div>
              <span className="toolbar-meta">{visible.length} lead{visible.length === 1 ? "" : "s"}</span>
            </div>
          </div>

          {visible.length === 0 ? (
            <EmptyState
              bordered
              icon="user-plus"
              title={estado ? `Sin leads «${statusMeta(estado).label}»` : "Sin leads todavía"}
              description={
                estado
                  ? "Cambia de filtro para ver otros prospectos."
                  : "Cuando un usuario deje su contacto durante una conversación con el asistente, el prospecto aparecerá aquí automáticamente."
              }
              action={
                estado ? (
                  <a href="/leads" className="btn btn-secondary">
                    Ver todos los leads
                  </a>
                ) : undefined
              }
            />
          ) : (
            <div className="table-wrap">
              <table>
                <caption className="visually-hidden">
                  Listado de leads con contacto, estado comercial y presupuesto
                </caption>
                <thead>
                  <tr>
                    <th>Contacto</th>
                    <th>Teléfono</th>
                    <th>Estado</th>
                    <th className="num">Presupuesto</th>
                    <th>Registrado</th>
                  </tr>
                </thead>
                <tbody>
                  {visible.map((l) => (
                    <tr key={l.id}>
                      <td>
                        <div className="cell-main">{l.name || "Sin nombre"}</div>
                        <div className="cell-sub">Usuario #{l.user_id}</div>
                      </td>
                      <td>
                        {l.phone ? (
                          <a
                            className="call-link"
                            href={`tel:${l.phone}`}
                            aria-label={`Llamar a ${l.name || "este lead"} al ${l.phone}`}
                          >
                            <Icon name="phone" size={13} />
                            {l.phone}
                          </a>
                        ) : (
                          <span className="muted">—</span>
                        )}
                      </td>
                      <td>
                        <StatusBadge status={l.status} />
                      </td>
                      <td className="num">
                        {l.budget ? formatMoney(l.budget, "COP") : "—"}
                      </td>
                      <td>
                        {formatDateTime(l.created_at)}
                        <div className="cell-sub">{timeAgo(l.created_at)}</div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}
    </>
  );
}
