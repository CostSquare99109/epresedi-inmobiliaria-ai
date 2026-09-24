"use client";

import { useEffect, useState } from "react";
import { backend, type AppointmentDTO, type LeadDTO, type PropertyDTO } from "../../api/client";
import { PageHeader } from "../../components/PageHeader";
import { StatusBadge } from "../../components/StatusBadge";
import { EmptyState } from "../../components/EmptyState";
import { ErrorBanner } from "../../components/ErrorBanner";
import { RefreshButton } from "../../components/RefreshButton";
import { LoadingState } from "../../components/LoadingState";
import { FilterTabs } from "../../components/TableControls";
import { Icon } from "../../components/icons";
import { statusMeta } from "../../lib/status";
import { formatDateTime, timeAgo } from "../../lib/format";

const STATUSES = ["REQUESTED", "CONFIRMED", "COMPLETED", "CANCELLED"];

export function CitasPage() {
  const [appts, setAppts] = useState<AppointmentDTO[]>([]);
  const [props, setProps] = useState<PropertyDTO[]>([]);
  const [leads, setLeads] = useState<LeadDTO[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      try {
        const [a, p, l] = await Promise.all([
          backend<{ appointments: AppointmentDTO[] }>("/appointments"),
          backend<{ properties: PropertyDTO[] }>("/properties?limit=200"),
          backend<{ leads: LeadDTO[] }>("/leads"),
        ]);
        setAppts(a.appointments);
        setProps(p.properties);
        setLeads(l.leads);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  const propById = new Map(props.map((p) => [p.id, p]));
  const leadById = new Map(leads.map((l) => [l.id, l]));
  const byStatus = appts.reduce<Record<string, number>>((acc, a) => {
    acc[a.status] = (acc[a.status] ?? 0) + 1;
    return acc;
  }, {});

  const now = Date.now();
  const sorted = [...appts].sort((a, b) => {
    const aUp = new Date(a.scheduled_at).getTime() >= now;
    const bUp = new Date(b.scheduled_at).getTime() >= now;
    if (aUp !== bUp) return aUp ? -1 : 1;
    return aUp
      ? a.scheduled_at.localeCompare(b.scheduled_at)
      : b.scheduled_at.localeCompare(a.scheduled_at);
  });

  if (loading) {
    return (
      <>
        <PageHeader title="Citas" description="Visitas agendadas por los clientes: propiedad, interesado, fecha programada y estado." />
        <div className="card">
          <div className="card-body">
            <LoadingState rows={5} label="Cargando citas…" />
          </div>
        </div>
      </>
    );
  }

  return (
    <>
      <PageHeader
        title="Citas"
        description="Visitas agendadas por los clientes: propiedad, interesado, fecha programada y estado."
        actions={<RefreshButton />}
      />

      {error && <ErrorBanner message={error} />}

      {!error && (
        <section className="card" aria-label="Listado de citas">
          <div className="card-head">
            <div className="toolbar">
              <div className="toolbar-filters">
                <FilterTabs
                  basePath="/citas"
                  params={{}}
                  paramName="estado"
                  current=""
                  options={[
                    { value: "", label: "Todas", count: appts.length },
                    ...STATUSES.map((s) => ({
                      value: s,
                      label: statusMeta(s).label,
                      count: byStatus[s] ?? 0,
                    })),
                  ]}
                  ariaLabel="Filtrar por estado de la cita"
                />
              </div>
              <span className="toolbar-meta">{sorted.length} cita{sorted.length === 1 ? "" : "s"}</span>
            </div>
          </div>

          {sorted.length === 0 ? (
            <EmptyState
              bordered
              icon="calendar"
              title="Sin citas agendadas"
              description="Las visitas que los clientes agenden a través del asistente aparecerán aquí ordenadas por fecha."
            />
          ) : (
            <div className="table-wrap">
              <table>
                <caption className="visually-hidden">
                  Listado de citas con propiedad, interesado, fecha y estado
                </caption>
                <thead>
                  <tr>
                    <th>Propiedad</th>
                    <th>Interesado</th>
                    <th>Fecha programada</th>
                    <th>Estado</th>
                  </tr>
                </thead>
                <tbody>
                  {sorted.map((a) => {
                    const prop = propById.get(a.property_id);
                    const lead = a.lead_id ? leadById.get(a.lead_id) : undefined;
                    return (
                      <tr key={a.id}>
                        <td>
                          <div className="cell-main">
                            {prop ? prop.title : `Propiedad ${a.property_id.slice(0, 8)}…`}
                          </div>
                          <div className="cell-sub">
                            {prop
                              ? `${prop.code} · ${prop.city}`
                              : a.property_id}
                          </div>
                        </td>
                        <td>
                          {lead ? (
                            <>
                              <div className="cell-main">{lead.name || "Cliente"}</div>
                              {lead.phone && (
                                <a
                                  className="call-link"
                                  href={`tel:${lead.phone}`}
                                  aria-label={`Llamar a ${lead.name || "el interesado"} al ${lead.phone}`}
                                >
                                  <Icon name="phone" size={12} />
                                  {lead.phone}
                                </a>
                              )}
                            </>
                          ) : (
                            <span className="muted">—</span>
                          )}
                        </td>
                        <td>
                          {formatDateTime(a.scheduled_at)}
                          <div className="cell-sub">{timeAgo(a.scheduled_at)}</div>
                        </td>
                        <td>
                          <StatusBadge status={a.status} />
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}
    </>
  );
}