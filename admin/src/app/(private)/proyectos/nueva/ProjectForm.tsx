"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { createProject, updateProject, deleteProject } from "@/app/proyectos/actions";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Textarea } from "@/components/ui/Textarea";
import { ErrorBanner } from "@/components/ErrorBanner";
import { ActionToast, type Feedback } from "@/components/ActionToast";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { Icon } from "@/components/icons";

interface ProjectFormProps {
  mode: "create" | "edit";
  initialData?: any;
  projectId?: string;
}

export function ProjectForm({ mode, initialData, projectId }: ProjectFormProps) {
  const router = useRouter();
  const [feedback, setFeedback] = useState<Feedback | null>(null);
  const [loading, setLoading] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);

  const [formData, setFormData] = useState({
    name: initialData?.name || "",
    description: initialData?.description || "",
    city: initialData?.city || "",
  });

  const handleChange = (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
    const { name, value } = e.target;
    setFormData(prev => ({ ...prev, [name]: value }));
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
        result = await createProject(submitData);
      } else {
        result = await updateProject(projectId!, submitData);
      }

      if (result.ok) {
        setFeedback({ tone: "ok", message: mode === "create" ? "Proyecto creado correctamente" : "Proyecto actualizado correctamente" });
        setTimeout(() => router.push("/proyectos"), 1500);
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
    if (!projectId) return;
    try {
      const result = await deleteProject(projectId);
      if (result.ok) {
        router.push("/proyectos");
      } else {
        setFeedback({ tone: "error", message: result.error });
      }
    } catch (e) {
      setFeedback({ tone: "error", message: "Error eliminando proyecto" });
    }
    setShowDeleteConfirm(false);
  };

  const isEditing = mode === "edit";

  return (
    <div className="project-form-container">
      <ActionToast feedback={feedback} onClose={() => setFeedback(null)} />
      {feedback?.tone === "error" && <ErrorBanner title="Error" message={feedback.message} />}

      <form onSubmit={handleSubmit} className="property-form" noValidate>
        <section className="card form-section" aria-labelledby="basic-info-heading">
          <header className="card-head">
            <h2 id="basic-info-heading" className="section-title">
              <Icon name="info" size={18} /> Información del proyecto
            </h2>
          </header>
          <div className="card-body form-grid">
            <Input
              label="Nombre *"
              name="name"
              value={formData.name}
              onChange={handleChange}
              placeholder="Ej: Villas de Carepa"
              required
              maxLength={160}
            />
            <Input
              label="Ciudad"
              name="city"
              value={formData.city}
              onChange={handleChange}
              placeholder="Ej: Carepa"
              maxLength={80}
            />
          </div>
        </section>

        <section className="card form-section" aria-labelledby="description-heading">
          <header className="card-head">
            <h2 id="description-heading" className="section-title">
              <Icon name="file-text" size={18} /> Descripción
            </h2>
          </header>
          <div className="card-body">
            <Textarea
              label="Descripción"
              name="description"
              value={formData.description}
              onChange={handleChange}
              placeholder="Describe el proyecto, ubicación, características comunes..."
              rows={4}
            />
          </div>
        </section>

        <footer className="form-footer">
          <Link href="/proyectos" className="btn btn-secondary">
            <Icon name="x" size={16} />
            Cancelar
          </Link>
          <Button type="submit" loading={loading} className="btn-primary">
            {loading ? "Guardando..." : isEditing ? "Actualizar" : "Crear proyecto"}
            <Icon name="save" size={16} />
          </Button>
        </footer>
      </form>

      {isEditing && projectId && (
        <ConfirmDialog
          open={showDeleteConfirm}
          onConfirm={handleDelete}
          onCancel={() => setShowDeleteConfirm(false)}
          title="Eliminar proyecto"
          description={`Se eliminará "${initialData?.name}". Esta acción no se puede deshacer. El proyecto no debe tener propiedades asignadas.`}
          danger={true}
        />
      )}
    </div>
  );
}