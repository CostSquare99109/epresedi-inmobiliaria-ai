"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { patchLead } from "@/app/propiedades/actions";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { ErrorBanner } from "@/components/ErrorBanner";
import { ActionToast, type Feedback } from "@/components/ActionToast";
import { Icon } from "@/components/icons";
import { formatMoney } from "@/lib/format";
import { statusMeta, LEAD_STATUSES } from "@/lib/status";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { Textarea } from "@/components/ui/Textarea";
import { Button } from "@/components/ui/Button";

interface LeadDetailProps {
  lead: {
    id: string;
    user_id: number;
    name: string;
    phone: string;
    status: string;
    budget: number | null;
    preferences: Record<string, any>;
    created_at: string;
    updated_at: string;
  };
  error: string;
}

export function LeadDetail({ lead, error }: LeadDetailProps) {
  const router = useRouter();
  const [feedback, setFeedback] = useState<Feedback | null>(null);
  const [isEditing, setIsEditing] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [saving, setSaving] = useState(false);

  const [formData, setFormData] = useState({
    name: lead.name,
    phone: lead.phone,
    status: lead.status,
    budget: lead.budget?.toString() || "",
    notes: "",
    preferences: JSON.stringify(lead.preferences || {}, null, 2),
  });

  const handleChange = (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) => {
    const { name, value } = e.target;
    setFormData(prev => ({ ...prev, [name]: value }));
  };

  const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setFeedback(null);
    setSaving(true);

    const submitData: any = {};
    Object.entries(formData).forEach(([key, value]) => {
      if (value !== "" && value !== undefined && value !== null) {
        if (key === "budget") {
          submitData[key] = parseFloat(value);
        } else if (key === "preferences") {
          try {
            submitData[key] = JSON.parse(value);
          } catch {
            setFeedback({ tone: "error", message: "Preferencias: JSON inválido" });
            setSaving(false);
            return;
          }
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
      const result = await patchLead(lead.id, submitData);
      if (result.ok) {
        setFeedback({ tone: "ok", message: "Lead actualizado correctamente" });
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

  const handleDelete = async () => {
    setFeedback({ tone: "error", message: "Eliminación de leads no implementada aún" });
    setShowDeleteConfirm(false);
  };

  const status = statusMeta(lead.status);

  return (
    <div className="lead-detail">
      <ActionToast feedback={feedback} onClose={() => setFeedback(null)} />
      {error && <ErrorBanner message={error} />}

      <section className="card" aria-labelledby="detail-heading">
        <header className="card-head">
          <div className="detail-header">
            <div>
              <h1 id="detail-heading" className="detail-title">{lead.name}</h1>
              <div className="detail-meta">
                <span className="detail-code">ID: {lead.id.slice(0, 8)}...</span>
                <span className={`status-badge status-${status.tone}`}>{status.label}</span>
              </div>
            </div>
            <div className="detail-actions">
              {!isEditing ? (
                <Button variant="primary" onClick={() => setIsEditing(true)}>
                  <Icon name="edit" size={16} /> Editar
                </Button>
              ) : (
                <>
                  <Button variant="secondary" onClick={() => setIsEditing(false)}>
                    <Icon name="x" size={16} /> Cancelar
                  </Button>
                  <Button variant="primary" onClick={(e) => { e.preventDefault(); handleSubmit(e as unknown as React.FormEvent<HTMLFormElement>); }} loading={saving}>
                    {saving ? "Guardando..." : "Guardar"}
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
                  <Icon name="user" size={16} />
                  Información de contacto
                </h2>
                {isEditing ? (
                  <form id="lead-form" onSubmit={handleSubmit} className="form-grid">
                    <Input
                      label="Nombre *"
                      name="name"
                      value={formData.name}
                      onChange={handleChange}
                      required
                    />
                    <Input
                      label="Teléfono *"
                      name="phone"
                      type="tel"
                      value={formData.phone}
                      onChange={handleChange}
                      required
                    />
                    <Input
                      label="Presupuesto (COP)"
                      name="budget"
                      type="number"
                      step="1000000"
                      min="0"
                      value={formData.budget}
                      onChange={handleChange}
                    />
                    <Select
                      label="Estado"
                      name="status"
                      value={formData.status}
                      onChange={handleChange}
                      options={LEAD_STATUSES.map((s: { value: string; label: string }) => ({ value: s.value, label: s.label }))}
                    />
                    <Textarea
                      label="Notas"
                      name="notes"
                      value={formData.notes}
                      onChange={handleChange}
                      rows={3}
                    />
                    <Textarea
                      label="Preferencias (JSON)"
                      name="preferences"
                      value={formData.preferences}
                      onChange={handleChange}
                      rows={5}
                    />
                  </form>
                ) : (
                  <dl className="info-list">
                    <div><dt>Teléfono</dt><dd><a href={`tel:${lead.phone}`}>{lead.phone}</a></dd></div>
                    {lead.budget && <div><dt>Presupuesto</dt><dd>{formatMoney(lead.budget, "COP")}</dd></div>}
                    <div><dt>Estado</dt><dd><span className={`status-badge status-${status.tone}`}>{status.label}</span></dd></div>
                    <div><dt>Usuario ID</dt><dd>{lead.user_id}</dd></div>
                    <div><dt>Creado</dt><dd>{new Date(lead.created_at).toLocaleString()}</dd></div>
                    <div><dt>Actualizado</dt><dd>{new Date(lead.updated_at).toLocaleString()}</dd></div>
                  </dl>
                )}
              </section>

              {Object.keys(lead.preferences || {}).length > 0 && (
                <section className="info-section">
                  <h2 className="info-heading">
                    <Icon name="settings" size={16} />
                    Preferencias
                  </h2>
                  {isEditing ? (
                    <p className="form-hint">Edita el JSON en el campo "Preferencias (JSON)" arriba.</p>
                  ) : (
                    <pre className="preferences-json">{JSON.stringify(lead.preferences, null, 2)}</pre>
                  )}
                </section>
              )}
            </div>

            <aside className="detail-sidebar">
              <div className="card sticky-sidebar">
                <header className="card-head">
                  <h2 className="section-title">Acciones</h2>
                </header>
                <div className="card-body action-list">
                  <Link href="/leads" className="action-item">
                    <Icon name="arrow-left" size={16} />
                    Volver al listado
                  </Link>
                  <button
                    type="button"
                    className="action-item action-danger"
                    onClick={() => setShowDeleteConfirm(true)}
                    disabled={isEditing}
                  >
                    <Icon name="trash" size={16} />
                    Eliminar lead
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
        title="Eliminar lead"
        description={`Se eliminará "${lead.name}". Esta acción no se puede deshacer.`}
        danger={true}
        confirmLabel="Eliminar"
      />
    </div>
  );
}