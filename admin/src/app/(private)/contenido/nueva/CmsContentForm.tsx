"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { createCmsContent, updateCmsContent, deleteCmsContent } from "@/app/contenido/actions";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { Textarea } from "@/components/ui/Textarea";
import { ErrorBanner } from "@/components/ErrorBanner";
import { ActionToast, type Feedback } from "@/components/ActionToast";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { Icon } from "@/components/icons";

const TYPE_OPTIONS = [
  { value: "text", label: "Texto plano" },
  { value: "html", label: "HTML" },
  { value: "json", label: "JSON" },
  { value: "image", label: "Imagen (URL)" },
  { value: "number", label: "Número" },
  { value: "boolean", label: "Booleano" },
];

const GROUP_OPTIONS = [
  { value: "general", label: "General" },
  { value: "branding", label: "Branding" },
  { value: "contact", label: "Contacto" },
  { value: "legal", label: "Legal" },
  { value: "seo", label: "SEO" },
  { value: "banners", label: "Banners" },
  { value: "faqs", label: "FAQs" },
];

interface CmsContentFormProps {
  mode: "create" | "edit";
  initialData?: any;
  contentId?: string;
}

export function CmsContentForm({ mode, initialData, contentId }: CmsContentFormProps) {
  const router = useRouter();
  const [feedback, setFeedback] = useState<Feedback | null>(null);
  const [loading, setLoading] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);

  const [formData, setFormData] = useState({
    key: initialData?.key || "",
    type: initialData?.type || "text",
    value: initialData?.value || "",
    label: initialData?.label || "",
    description: initialData?.description || "",
    group: initialData?.group || "general",
    is_public: initialData?.is_public || false,
  });

  const handleChange = (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) => {
    const { name, value, type } = e.target;
    setFormData(prev => ({
      ...prev,
      [name]: type === "checkbox" ? (e.target as HTMLInputElement).checked : value,
    }));
    setFeedback(null);
  };

  const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setFeedback(null);
    setLoading(true);

    const submitData = new FormData();
    Object.entries(formData).forEach(([key, value]) => {
      if (value !== "" && value !== undefined && value !== null) {
        submitData.append(key, String(value));
      }
    });

    try {
      let result;
      if (mode === "create") {
        result = await createCmsContent(submitData);
      } else {
        result = await updateCmsContent(contentId!, submitData);
      }

      if (result.ok) {
        setFeedback({ tone: "ok", message: mode === "create" ? "Contenido creado correctamente" : "Contenido actualizado correctamente" });
        setTimeout(() => router.push("/contenido"), 1500);
      } else {
        setFeedback({ tone: "error", message: result.error });
      }
    } catch (e) {
      setFeedback({ tone: "error", message: e instanceof Error ? e.message : "Error desconocido" });
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async () => {
    if (!contentId) return;
    try {
      const result = await deleteCmsContent(contentId);
      if (result.ok) {
        router.push("/contenido");
      } else {
        setFeedback({ tone: "error", message: result.error });
      }
    } catch (e) {
      setFeedback({ tone: "error", message: "Error eliminando contenido" });
    }
    setShowDeleteConfirm(false);
  };

  const isEditing = mode === "edit";

  return (
    <div className="cms-form-container">
      <ActionToast feedback={feedback} onClose={() => setFeedback(null)} />
      {feedback?.tone === "error" && <ErrorBanner title="Error" message={feedback.message} />}

      <form onSubmit={handleSubmit} className="property-form" noValidate>
        <section className="card form-section" aria-labelledby="basic-info-heading">
          <header className="card-head">
            <h2 id="basic-info-heading" className="section-title">
              <Icon name="info" size={18} /> Información del contenido
            </h2>
          </header>
          <div className="card-body form-grid">
            {!isEditing && (
              <Input
                label="Clave *"
                name="key"
                value={formData.key}
                onChange={handleChange}
                placeholder="ej: hero_banner_principal"
                required
                maxLength={100}
              />
            )}
            {isEditing && (
              <div className="field">
                <label className="field-label">Clave</label>
                <input className="field-input" value={formData.key} disabled />
                <span className="field-hint">La clave no se puede cambiar</span>
              </div>
            )}
            <Input
              label="Etiqueta *"
              name="label"
              value={formData.label}
              onChange={handleChange}
              placeholder="Título visible en el panel"
              required
              maxLength={200}
            />
            <Select
              label="Tipo *"
              name="type"
              value={formData.type}
              onChange={handleChange}
              options={TYPE_OPTIONS}
              required
            />
            <Select
              label="Grupo *"
              name="group"
              value={formData.group}
              onChange={handleChange}
              options={GROUP_OPTIONS}
              required
            />
            <label className="checkbox-field">
              <input
                type="checkbox"
                name="is_public"
                checked={formData.is_public}
                onChange={handleChange}
              />
              <span>Público (accesible desde frontend sin auth)</span>
            </label>
          </div>
        </section>

        <section className="card form-section" aria-labelledby="value-heading">
          <header className="card-head">
            <h2 id="value-heading" className="section-title">
              <Icon name="file-text" size={18} /> Valor
            </h2>
          </header>
          <div className="card-body form-grid">
            <Textarea
              label="Descripción (interna)"
              name="description"
              value={formData.description}
              onChange={handleChange}
              placeholder="Descripción para administradores: qué es este contenido, dónde se usa..."
              rows={3}
            />
            <Textarea
              label="Valor"
              name="value"
              value={formData.value}
              onChange={handleChange}
              placeholder={formData.type === "json" ? '{"clave": "valor"}' : formData.type === "html" ? "<p>Contenido HTML...</p>" : "Texto del contenido..."}
              rows={5}
            />
          </div>
        </section>

        <footer className="form-footer">
          <Link href="/contenido" className="btn btn-secondary">
            <Icon name="x" size={16} />
            Cancelar
          </Link>
          <Button type="submit" loading={loading} className="btn-primary">
            {loading ? "Guardando..." : isEditing ? "Actualizar" : "Crear contenido"}
            <Icon name="save" size={16} />
          </Button>
        </footer>
      </form>

      {isEditing && contentId && (
        <ConfirmDialog
          open={showDeleteConfirm}
          onConfirm={handleDelete}
          onCancel={() => setShowDeleteConfirm(false)}
          title="Eliminar contenido"
          description={`Se eliminará "${initialData?.key}" (${initialData?.label}). Esta acción no se puede deshacer.`}
          danger={true}
        />
      )}
    </div>
  );
}