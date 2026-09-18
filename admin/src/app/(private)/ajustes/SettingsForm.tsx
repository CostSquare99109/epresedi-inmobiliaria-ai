"use client";

import { useState } from "react";
import { updateSettings } from "@/app/ajustes/actions";
import { ActionToast, type Feedback } from "@/components/ActionToast";
import { ErrorBanner } from "@/components/ErrorBanner";
import { Icon } from "@/components/icons";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";

export function SettingsForm() {
  const [feedback, setFeedback] = useState<Feedback | null>(null);
  const [loading, setLoading] = useState(false);
  const [formData, setFormData] = useState<Record<string, string>>({});

  const handleChange = (key: string, value: string) => {
    setFormData(prev => ({ ...prev, [key]: value }));
  };

  const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setFeedback(null);
    setLoading(true);

    const settings: Record<string, any> = {};
    for (const [key, value] of Object.entries(formData)) {
      if (value === "") continue;
      try {
        settings[key] = JSON.parse(value);
      } catch {
        settings[key] = value;
      }
    }

    if (Object.keys(settings).length === 0) {
      setFeedback({ tone: "error", message: "No hay cambios para guardar" });
      setLoading(false);
      return;
    }

    try {
      const result = await updateSettings(settings);
      if (result.ok) {
        setFeedback({ tone: "ok", message: `Ajustes actualizados: ${result.updated.join(", ")}` });
        setFormData({});
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
    <form onSubmit={handleSubmit} className="settings-form" noValidate>
      <ActionToast feedback={feedback} onClose={() => setFeedback(null)} />
      {feedback?.tone === "error" && <ErrorBanner title="Error" message={feedback.message} />}

      <div className="card-body form-grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))" }}>
        <Input
          label="Clave (ej: max_upload_mb)"
          name="key"
          value={formData.key || ""}
          onChange={(e) => handleChange("key", e.target.value)}
          placeholder="max_upload_mb"
        />
        <Input
          label="Valor (JSON para objetos/arrays, texto plano para strings)"
          name="value"
          value={formData.value || ""}
          onChange={(e) => handleChange("value", e.target.value)}
          placeholder='15 o {"horas": [9,10,11,14,15,16,17]}'
        />
      </div>

      <div className="form-actions" style={{ marginTop: "var(--sp-4)", display: "flex", gap: "var(--sp-2)" }}>
        <Button type="submit" loading={loading} className="btn-primary">
          {loading ? "Guardando..." : "Actualizar ajustes"}
          <Icon name="save" size={16} />
        </Button>
        <button type="button" className="btn btn-secondary" onClick={() => setFormData({})}>
          <Icon name="x" size={16} /> Limpiar
        </button>
      </div>
    </form>
  );
}