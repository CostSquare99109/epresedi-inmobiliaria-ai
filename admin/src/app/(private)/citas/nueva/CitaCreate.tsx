"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { createAppointment, getPropertySlots } from "@/app/citas/actions";
import type { PropertyDTO, LeadDTO } from "@/lib/types";
import { ErrorBanner } from "@/components/ErrorBanner";
import { ActionToast, type Feedback } from "@/components/ActionToast";
import { Icon } from "@/components/icons";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { Textarea } from "@/components/ui/Textarea";
import { Button } from "@/components/ui/Button";

export function CitaCreate() {
  const router = useRouter();
  const [feedback, setFeedback] = useState<Feedback | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadingSlots, setLoadingSlots] = useState(false);
  const [properties, setProperties] = useState<PropertyDTO[]>([]);
  const [leads, setLeads] = useState<LeadDTO[]>([]);
  const [slots, setSlots] = useState<any[]>([]);
  const [selectedPropertyId, setSelectedPropertyId] = useState<string>("");
  const [selectedLeadId, setSelectedLeadId] = useState<string>("");

  const [formData, setFormData] = useState({
    property_id: "",
    lead_id: "",
    scheduled_at: "",
    duration_minutes: "60",
    notes: "",
  });

  useEffect(() => {
    loadProperties();
    loadLeads();
  }, []);

  const loadProperties = async () => {
    try {
      const res = await fetch("/api/proxy/properties?limit=100", { cache: "no-store" });
      const body = await res.json();
      setProperties(body.properties ?? []);
    } catch (e) {
      console.error("Error loading properties:", e);
    }
  };

  const loadLeads = async () => {
    try {
      const res = await fetch("/api/proxy/leads?limit=100", { cache: "no-store" });
      const body = await res.json();
      setLeads(body.leads ?? []);
    } catch (e) {
      console.error("Error loading leads:", e);
    }
  };

  const handlePropertyChange = async (e: React.ChangeEvent<HTMLSelectElement>) => {
    const propertyId = e.target.value;
    setSelectedPropertyId(propertyId);
    setFormData(prev => ({ ...prev, property_id: propertyId, scheduled_at: "" }));
    setSlots([]);
    
    if (propertyId) {
      setLoadingSlots(true);
      try {
        const result = await getPropertySlots(propertyId, 14);
        if (result.ok) {
          setSlots(result.slots);
        }
      } catch (e) {
        console.error("Error loading slots:", e);
      } finally {
        setLoadingSlots(false);
      }
    }
  };

  const handleChange = (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) => {
    const { name, value } = e.target;
    setFormData(prev => ({ ...prev, [name]: value }));
  };

  const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setFeedback(null);
    setLoading(true);

    if (!formData.property_id || !formData.scheduled_at) {
      setFeedback({ tone: "error", message: "Propiedad y fecha/hora son obligatorias" });
      setLoading(false);
      return;
    }

    const submitData = new FormData();
    Object.entries(formData).forEach(([key, value]) => {
      if (value !== "" && value !== undefined && value !== null) {
        if (key === "duration_minutes") {
          submitData.append(key, String(parseInt(value, 10)));
        } else {
          submitData.append(key, String(value));
        }
      }
    });

    try {
      const result = await createAppointment(submitData);
      if (result.ok) {
        setFeedback({ tone: "ok", message: "Cita creada correctamente" });
        setTimeout(() => router.push(`/citas/${result.appointment?.id}`), 1500);
      } else {
        setFeedback({ tone: "error", message: result.error });
      }
    } catch (e) {
      setFeedback({ tone: "error", message: e instanceof Error ? e.message : "Error desconocido" });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="cita-create">
      <ActionToast feedback={feedback} onClose={() => setFeedback(null)} />

      <form onSubmit={handleSubmit} className="property-form" noValidate>
        <section className="card form-section" aria-labelledby="property-heading">
          <header className="card-head">
            <h2 id="property-heading" className="section-title">
              <Icon name="home" size={18} /> Propiedad
            </h2>
          </header>
          <div className="card-body form-grid">
            <Select
              label="Propiedad *"
              name="property_id"
              value={formData.property_id}
              onChange={handlePropertyChange}
              options={[
                { value: "", label: "Seleccionar propiedad..." },
                ...properties.map(p => ({ 
                  value: p.id, 
                  label: `${p.title} (${p.code}) - ${p.city}` 
                })),
              ]}
              required
            />
            {loadingSlots && <span className="loading-slots">Cargando horarios disponibles...</span>}
          </div>
        </section>

        <section className="card form-section" aria-labelledby="client-heading">
          <header className="card-head">
            <h2 id="client-heading" className="section-title">
              <Icon name="user" size={18} /> Cliente (opcional)
            </h2>
          </header>
          <div className="card-body form-grid">
            <Select
              label="Lead"
              name="lead_id"
              value={formData.lead_id}
              onChange={handleChange}
              options={[
                { value: "", label: "Sin lead asociado" },
                ...leads.map(l => ({ 
                  value: l.id, 
                  label: `${l.name} (${l.phone}) - ${l.status}` 
                })),
              ]}
            />
          </div>
        </section>

        <section className="card form-section" aria-labelledby="schedule-heading">
          <header className="card-head">
            <h2 id="schedule-heading" className="section-title">
              <Icon name="calendar" size={18} /> Fecha y hora
            </h2>
          </header>
          <div className="card-body form-grid">
            <div className="slots-container">
              {slots.length > 0 ? (
                <div className="slots-grid" role="group" aria-label="Horarios disponibles">
                  {slots.map((slot: any) => (
                    <button
                      key={slot.datetime}
                      type="button"
                      className={`slot-btn ${formData.scheduled_at === slot.datetime ? "selected" : ""}`}
                      onClick={() => setFormData(prev => ({ ...prev, scheduled_at: slot.datetime }))}
                      aria-pressed={formData.scheduled_at === slot.datetime}
                    >
                      {new Date(slot.datetime).toLocaleString()}
                    </button>
                  ))}
                </div>
              ) : selectedPropertyId && !loadingSlots ? (
                <p className="no-slots">No hay horarios disponibles en los próximos 14 días. Selecciona otra propiedad o amplía el rango en el backend.</p>
              ) : (
                <p className="no-slots">Selecciona una propiedad para ver horarios disponibles.</p>
              )}
            </div>
            <Input
              label="Fecha y hora (manual)"
              name="scheduled_at"
              type="datetime-local"
              value={formData.scheduled_at}
              onChange={handleChange}
              required
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
          </div>
        </section>

        <section className="card form-section" aria-labelledby="notes-heading">
          <header className="card-head">
            <h2 id="notes-heading" className="section-title">
              <Icon name="file-text" size={18} /> Notas
            </h2>
          </header>
          <div className="card-body">
            <Textarea
              label="Notas"
              name="notes"
              value={formData.notes}
              onChange={handleChange}
              rows={3}
              placeholder="Observaciones adicionales sobre la cita..."
            />
          </div>
        </section>

        <footer className="form-footer">
          <Link href="/citas" className="btn btn-secondary">
            <Icon name="x" size={16} />
            Cancelar
          </Link>
          <Button type="submit" loading={loading} className="btn-primary">
            {loading ? "Creando..." : "Crear cita"}
            <Icon name="calendar-plus" size={16} />
          </Button>
        </footer>
      </form>
    </div>
  );
}