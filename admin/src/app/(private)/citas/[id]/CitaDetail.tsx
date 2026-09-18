"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { cancelAppointment, updateAppointment, rescheduleAppointment, getPropertySlots } from "@/app/citas/actions";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { ErrorBanner } from "@/components/ErrorBanner";
import { ActionToast, type Feedback } from "@/components/ActionToast";
import { Icon } from "@/components/icons";
import { statusMeta, APPOINTMENT_STATUSES } from "@/lib/status";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { Textarea } from "@/components/ui/Textarea";
import { Button } from "@/components/ui/Button";

interface CitaDetailProps {
  cita: {
    id: string;
    property_id: string;
    lead_id: string | null;
    scheduled_at: string;
    duration_minutes: number;
    status: string;
    notes: string;
  };
  error: string;
}

export function CitaDetail({ cita, error }: CitaDetailProps) {
  const router = useRouter();
  const [feedback, setFeedback] = useState<Feedback | null>(null);
  const [isEditing, setIsEditing] = useState(false);
  const [showCancelConfirm, setShowCancelConfirm] = useState(false);
  const [showReschedule, setShowReschedule] = useState(false);
  const [saving, setSaving] = useState(false);
  const [slots, setSlots] = useState<any[]>([]);
  const [loadingSlots, setLoadingSlots] = useState(false);

  const [formData, setFormData] = useState({
    status: cita.status,
    notes: cita.notes,
    scheduled_at: new Date(cita.scheduled_at).toISOString().slice(0, 16),
    duration_minutes: cita.duration_minutes.toString(),
    new_scheduled_at: "",
  });

  const [rescheduleFormData, setRescheduleFormData] = useState({
    new_scheduled_at: "",
    notes: "Reprogramada desde admin",
  });

  const handleChange = (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) => {
    const { name, value } = e.target;
    setFormData(prev => ({ ...prev, [name]: value }));
  };

  const handleRescheduleChange = (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
    const { name, value } = e.target;
    setRescheduleFormData(prev => ({ ...prev, [name]: value }));
  };

  const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setFeedback(null);
    setSaving(true);

    const submitData: any = {};
    Object.entries(formData).forEach(([key, value]) => {
      if (value !== "" && value !== undefined && value !== null) {
        if (key === "duration_minutes") {
          submitData[key] = parseInt(value, 10);
        } else {
          submitData[key] = value;
        }
      }
    });

    if (Object.keys(submitData).length === 0) {
      setFeedback({ tone: "error", message: "No hay cambios para guardar" });
      setSaving(false);
      return;
    }

    try {
      const fd = new FormData();
      Object.entries(submitData).forEach(([k, v]) => fd.append(k, String(v)));
      const result = await updateAppointment(cita.id, fd);
      if (result.ok) {
        setFeedback({ tone: "ok", message: "Cita actualizada correctamente" });
        setIsEditing(false);
        router.refresh();
      } else {
        setFeedback({ tone: "error", message: result.error });
      }
    } catch (e) {
      setFeedback({ tone: "error", message: e instanceof Error ? e.message : "Error desconocido" });
    } finally {
      setSaving(false);
    }
  };

  const handleCancel = async () => {
    setFeedback(null);
    try {
      const result = await cancelAppointment(cita.id);
      if (result.ok) {
        setFeedback({ tone: "ok", message: "Cita cancelada correctamente" });
        router.refresh();
      } else {
        setFeedback({ tone: "error", message: result.error });
      }
    } catch (e) {
      setFeedback({ tone: "error", message: e instanceof Error ? e.message : "Error cancelando cita" });
    }
    setShowCancelConfirm(false);
  };

  const handleReschedule = async () => {
    if (!rescheduleFormData.new_scheduled_at) {
      setFeedback({ tone: "error", message: "Selecciona una nueva fecha y hora" });
      return;
    }
    setFeedback(null);
    setSaving(true);
    try {
      const result = await rescheduleAppointment(
        cita.id,
        rescheduleFormData.new_scheduled_at,
        rescheduleFormData.notes
      );
      if (result.ok) {
        setFeedback({ tone: "ok", message: "Cita reprogramada correctamente" });
        setShowReschedule(false);
        router.refresh();
      } else {
        setFeedback({ tone: "error", message: result.error });
      }
    } catch (e) {
      setFeedback({ tone: "error", message: e instanceof Error ? e.message : "Error reprogramando cita" });
    } finally {
      setSaving(false);
    }
  };

  const loadSlots = async () => {
    setLoadingSlots(true);
    try {
      const result = await getPropertySlots(cita.property_id, 14);
      if (result.ok) {
        setSlots(result.slots);
      } else {
        setFeedback({ tone: "error", message: result.error });
      }
    } catch (e) {
      setFeedback({ tone: "error", message: "Error cargando horarios disponibles" });
    } finally {
      setLoadingSlots(false);
    }
  };

  const status = statusMeta(cita.status);
  const scheduledDate = new Date(cita.scheduled_at);
  const isPast = scheduledDate < new Date();

  return (
    <div className="cita-detail">
      <ActionToast feedback={feedback} onClose={() => setFeedback(null)} />
      {error && <ErrorBanner message={error} />}

      <section className="card" aria-labelledby="detail-heading">
        <header className="card-head">
          <div className="detail-header">
            <div>
              <h1 id="detail-heading" className="detail-title">Cita #{cita.id.slice(0, 8)}...</h1>
              <div className="detail-meta">
                <span className={`status-badge status-${status.tone}`}>{status.label}</span>
              </div>
            </div>
            <div className="detail-actions">
              {!isEditing && !showReschedule ? (
                <>
                  <Button variant="secondary" onClick={loadSlots} loading={loadingSlots} disabled={isPast}>
                    <Icon name="calendar" size={16} /> Ver horarios
                  </Button>
                  <Button variant="primary" onClick={() => { setIsEditing(true); setShowReschedule(false); }}>
                    <Icon name="edit" size={16} /> Editar
                  </Button>
                </>
              ) : isEditing ? (
                <>
                  <Button variant="secondary" onClick={() => setIsEditing(false)}>
                    <Icon name="x" size={16} /> Cancelar
                  </Button>
                  <Button variant="primary" onClick={(e) => { e.preventDefault(); handleSubmit(e as unknown as React.FormEvent<HTMLFormElement>); }} loading={saving}>
                    {saving ? "Guardando..." : "Guardar"}
                  </Button>
                </>
              ) : (
                <>
                  <Button variant="secondary" onClick={() => setShowReschedule(false)}>
                    <Icon name="x" size={16} /> Cancelar
                  </Button>
                  <Button variant="primary" onClick={handleReschedule} loading={saving}>
                    {saving ? "Reprogramando..." : "Reprogramar"}
                  </Button>
                </>
              )}
            </div>
          </div>
        </header>

        <div className="card-body">
          <div className="detail-grid">
            <div className="detail-main">
              <section className="info-section">
                <h2 className="info-heading">
                  <Icon name="calendar" size={16} />
                  Información de la cita
                </h2>
                {isEditing ? (
                  <form id="cita-form" onSubmit={handleSubmit} className="form-grid">
                    <Select
                      label="Estado"
                      name="status"
                      value={formData.status}
                      onChange={handleChange}
                      options={APPOINTMENT_STATUSES.map((s: string) => ({ value: s, label: statusMeta(s).label }))}
                    />
                    <Input
                      label="Fecha y hora"
                      name="scheduled_at"
                      type="datetime-local"
                      value={formData.scheduled_at}
                      onChange={handleChange}
                    />
                    <Input
                      label="Duración (minutos)"
                      name="duration_minutes"
                      type="number"
                      min="15"
                      max="480"
                      step="15"
                      value={formData.duration_minutes}
                      onChange={handleChange}
                    />
                    <Textarea
                      label="Notas"
                      name="notes"
                      value={formData.notes}
                      onChange={handleChange}
                      rows={3}
                    />
                  </form>
                ) : (
                  <dl className="info-list">
                    <div>
                      <dt>Propiedad</dt>
                      <dd>
                        <Link href={`/propiedades/${cita.property_id}`}>
                          {cita.property_id.slice(0, 8)}...
                        </Link>
                      </dd>
                    </div>
                    {cita.lead_id && (
                      <div>
                        <dt>Lead</dt>
                        <dd>
                          <Link href={`/leads/${cita.lead_id}`}>
                            {cita.lead_id.slice(0, 8)}...
                          </Link>
                        </dd>
                      </div>
                    )}
                    <div>
                      <dt>Fecha y hora</dt>
                      <dd>{new Date(cita.scheduled_at).toLocaleString()}</dd>
                    </div>
                    <div>
                      <dt>Duración</dt>
                      <dd>{cita.duration_minutes} minutos</dd>
                    </div>
                    <div>
                      <dt>Estado</dt>
                      <dd><span className={`status-badge status-${status.tone}`}>{status.label}</span></dd>
                    </div>
                    {cita.notes && <div><dt>Notas</dt><dd>{cita.notes}</dd></div>}
                  </dl>
                )}
              </section>

              {showReschedule && (
                <section className="info-section">
                  <h2 className="info-heading">
                    <Icon name="calendar-clock" size={16} />
                    Reprogramar cita
                  </h2>
                  <form onSubmit={handleReschedule} className="form-grid">
                    <Input
                      label="Nueva fecha y hora *"
                      name="new_scheduled_at"
                      type="datetime-local"
                      value={rescheduleFormData.new_scheduled_at}
                      onChange={handleRescheduleChange}
                      required
                    />
                    <Textarea
                      label="Notas"
                      name="notes"
                      value={rescheduleFormData.notes}
                      onChange={handleRescheduleChange}
                      rows={2}
                    />
                  </form>
                </section>
              )}
            </div>

            <aside className="detail-sidebar">
              <div className="card sticky-sidebar">
                <header className="card-head">
                  <h2 className="section-title">Acciones</h2>
                </header>
                <div className="card-body action-list">
                  <Link href="/citas" className="action-item">
                    <Icon name="arrow-left" size={16} />
                    Volver al listado
                  </Link>
                  {!isEditing && !showReschedule && !isPast && (
                    <Button
                      variant="secondary"
                      onClick={() => { loadSlots(); setShowReschedule(true); }}
                      className="action-item"
                    >
                      <Icon name="calendar-clock" size={16} />
                      Reprogramar
                    </Button>
                  )}
                  {!isEditing && !showReschedule && (
                    <button
                      type="button"
                      className="action-item action-danger"
                      onClick={() => setShowCancelConfirm(true)}
                      disabled={status.tone === "danger" || status.tone === "neutral"}
                    >
                      <Icon name="x-circle" size={16} />
                      Cancelar cita
                    </button>
                  )}
                </div>
              </div>
            </aside>
          </div>
        </div>
      </section>

      <ConfirmDialog
        open={showCancelConfirm}
        onConfirm={handleCancel}
        onCancel={() => setShowCancelConfirm(false)}
        title="Cancelar cita"
        description={`Se cancelará la cita programada para ${new Date(cita.scheduled_at).toLocaleString()}. Esta acción no se puede deshacer.`}
        danger={true}
        confirmLabel="Cancelar cita"
      />
    </div>
  );
}