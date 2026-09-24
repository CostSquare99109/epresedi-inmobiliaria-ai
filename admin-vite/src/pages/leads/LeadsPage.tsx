"use client";

import { useEffect, useState, useMemo } from "react";
import { backend, type LeadDTO } from "../../api/client";
import { PageHeader } from "../../components/PageHeader";
import { StatusBadge } from "../../components/StatusBadge";
import { EmptyState } from "../../components/EmptyState";
import { ErrorBanner } from "../../components/ErrorBanner";
import { RefreshButton } from "../../components/RefreshButton";
import { LoadingState } from "../../components/LoadingState";
import { FilterTabs } from "../../components/TableControls";
import { Icon } from "../../components/icons";
import { statusMeta } from "../../lib/status";
import { formatDateTime, formatMoney, timeAgo } from "../../lib/format";

const STATUSES = ["NEW", "CONTACTED", "INTERESTED", "VISIT_SCHEDULED", "NEGOTIATION", "CLOSED", "LOST"];

export function LeadsPage() {
  const [leads, setLeads] = useState<LeadDTO[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      try {
        const body = await backend<{ leads: LeadDTO[] }>("/leads");
        const sorted = [...body.leads].sort((a, b) => b.created_at.localeCompare(a.created_at));
        setLeads(sorted);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  const byStatus = useMemo(
    () =>
      leads.reduce<Record<string, number>>((acc, l) => {
        acc[l.status] = (acc[l.status] ?? 0) + 1;
        return acc;
      }, {}),
    [leads]
  );

  const [estado] = useState("");

  const visible = estado ? leads.filter((l) => l.status === estado) : leads;

  if (loading) {
    return (
      <>
        <PageHeader title="Leads" description="Prospectos captados por el asistente: contacto directo, estado comercial y presupuesto declarado." />
        <div className="card">
          <div className="card-body">
            <LoadingState rows={5} label="Cargando leads…" />
          </div>
        </div>
      </>
    );
  }

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
                    <th className="table-responsive-hide-xs">Teléfono</th>
                    <th>Estado</th>
                    <th className="num table-responsive-hide-sm">Presupuesto</th>
                    <th className="table-responsive-hide-xs">Registrado</th>
                  </tr>
                </thead>
                <tbody>
                  {visible.map((l) => (
                    <tr key={l.id}>
                      <td>
                        <div className="cell-main">{l.name || "Sin nombre"}</div>
                        <div className="cell-sub">Usuario #{l.user_id}</div>
                      </td>
                      <td className="table-responsive-hide-xs">
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
                      <td className="num table-responsive-hide-sm">
                        {l.budget ? formatMoney(l.budget, "COP") : "—"}
                      </td>
                      <td className="table-responsive-hide-xs">
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