"use client";

import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { Link } from "react-router-dom";
import { backend, type AppointmentDTO, type PropertyDTO, type LeadDTO } from "../../api/client";
import { PageHeader } from "../../components/PageHeader";
import { StatusBadge } from "../../components/StatusBadge";
import { ErrorBanner } from "../../components/ErrorBanner";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { Icon } from "../../components/icons";
import { formatDateTime, timeAgo } from "../../lib/format";
import { LoadingState } from "../../components/LoadingState";

export function CitaDetallePage() {
  const params = useParams();
  const navigate = useNavigate();
  const [appointment, setAppointment] = useState<AppointmentDTO | null>(null);
  const [property, setProperty] = useState<PropertyDTO | null>(null);
  const [lead, setLead] = useState<LeadDTO | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    async function load() {
      try {
        const a = await backend<AppointmentDTO>(`/appointments/${params.id}`);
        setAppointment(a);
        // Find property and lead
        const propRes = await backend<{ properties: PropertyDTO[] }>(`/properties?limit=200`);
        const leadRes = await backend<{ leads: LeadDTO[] }>(`/leads`);
        const prop = propRes.properties.find(pr => pr.id === a.property_id);
        const ld = a.lead_id ? leadRes.leads.find(le => le.id === a.lead_id) : null;
        if (prop) setProperty(prop);
        if (ld) setLead(ld);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Error cargando cita");
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [params.id]);

  const handleDelete = async () => {
    setDeleting(true);
    try {
      const res = await fetch(`/api/appointments/${params.id}`, { method: "DELETE" });
      if (res.ok) {
        navigate("/citas");
      } else {
        setError("Error eliminando cita");
      }
    } catch (e) {
      setError("Error de conexión");
    } finally {
      setDeleting(false);
      setShowDeleteConfirm(false);
    }
  };

  if (loading) {
    return (
      <>
        <PageHeader title="Cargando..." description="Obteniendo datos de la cita" />
        <div className="card">
          <div className="card-body">
            <LoadingState rows={4} label="Cargando cita…" variant="blocks" />
          </div>
        </div>
      </>
    );
  }

  if (!appointment) {
    return (
      <>
        <PageHeader title="Error" />
        <ErrorBanner message={error || "Cita no encontrada"} />
      </>
    );
  }

  const status = appointment.status;

  return (
    <>
      <PageHeader
        title={`Cita ${appointment.id.slice(0, 8)}…`}
        description={`${appointment.status} · ${formatDateTime(appointment.scheduled_at)}`}
      />

      {error && <ErrorBanner message={error} />}

      <section className="card" aria-label="Detalle de la cita">
        <div className="card-body">
          <div className="detail-grid">
            <div>
              <dl className="info-list">
                <div>
                  <dt>Propiedad</dt>
                  <dd>
                    {property ? (
                      <>
                        <div className="cell-main">{property.title}</div>
                        <div className="cell-sub">{property.code} · {property.city}</div>
                      </>
                    ) : (
                      `Propiedad ${appointment.property_id.slice(0, 8)}…`
                    )}
                  </dd>
                </div>
                <div>
                  <dt>Interesado</dt>
                  <dd>
                    {lead ? (
                      <>
                        <div className="cell-main">{lead.name || "Cliente"}</div>
                        {lead.phone && (
                          <a className="call-link" href={`tel:${lead.phone}`}>
                            <Icon name="phone" size={12} /> {lead.phone}
                          </a>
                        )}
                      </>
                    ) : (
                      <span className="muted">—</span>
                    )}
                  </dd>
                </div>
                <div>
                  <dt>Fecha programada</dt>
                  <dd>
                    <div className="cell-main">{formatDateTime(appointment.scheduled_at)}</div>
                    <div className="cell-sub">{timeAgo(appointment.scheduled_at)}</div>
                  </dd>
                </div>
                <div>
                  <dt>Duración</dt>
                  <dd>{appointment.duration_minutes} minutos</dd>
                </div>
                <div>
                  <dt>Estado</dt>
                  <dd><StatusBadge status={status} /></dd>
                </div>
                {appointment.notes && (
                  <div>
                    <dt>Notas</dt>
                    <dd>{appointment.notes}</dd>
                  </div>
                )}
              </dl>
            </div>

            <aside>
              <div className="card sticky-sidebar">
                <header className="card-head">
                  <h2 className="section-title">Acciones</h2>
                </header>
                <div className="card-body action-list">
                  <Link to="/citas" className="action-item">
                    <Icon name="arrow-left" size={16} />
                    Volver al listado
                  </Link>
                  <button
                    type="button"
                    className="action-item action-danger"
                    onClick={() => setShowDeleteConfirm(true)}
                    disabled={deleting}
                  >
                    <Icon name="trash" size={16} />
                    Eliminar cita
                  </button>
                </div>
              </div>
            </aside>
          </div>
        </div>
      </section>

      <ConfirmDialog
        open={showDeleteConfirm}
        onConfirm={handleDelete}
        onCancel={() => setShowDeleteConfirm(false)}
        title="Eliminar cita"
        description={`Se eliminará la cita programada para ${formatDateTime(appointment.scheduled_at)}. Esta acción no se puede deshacer.`}
        danger
        busy={deleting}
        confirmLabel="Eliminar"
      />
    </>
  );
}