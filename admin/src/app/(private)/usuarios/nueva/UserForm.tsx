"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { createUser, updateUser, deleteUser } from "@/app/usuarios/actions";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { ErrorBanner } from "@/components/ErrorBanner";
import { ActionToast, type Feedback } from "@/components/ActionToast";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { Icon } from "@/components/icons";

interface UserFormProps {
  mode: "create" | "edit";
  initialData?: any;
  userId?: string;
}

export function UserForm({ mode, initialData, userId }: UserFormProps) {
  const router = useRouter();
  const [feedback, setFeedback] = useState<Feedback | null>(null);
  const [loading, setLoading] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);

  const [formData, setFormData] = useState({
    email: initialData?.email || "",
    name: initialData?.name || "",
    password: "",
    role: initialData?.role || "asesor",
    is_active: initialData?.is_active !== false,
  });

  const handleChange = (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
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
        result = await createUser(submitData);
      } else {
        result = await updateUser(userId!, submitData);
      }

      if (result.ok) {
        setFeedback({ tone: "ok", message: mode === "create" ? "Usuario creado correctamente" : "Usuario actualizado correctamente" });
        setTimeout(() => router.push("/usuarios"), 1500);
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
    if (!userId) return;
    try {
      const result = await deleteUser(userId);
      if (result.ok) {
        router.push("/usuarios");
      } else {
        setFeedback({ tone: "error", message: result.error });
      }
    } catch (e) {
      setFeedback({ tone: "error", message: "Error eliminando usuario" });
    }
    setShowDeleteConfirm(false);
  };

  const isEditing = mode === "edit";

  const ROLE_OPTIONS = [
    { value: "superadmin", label: "Superadmin" },
    { value: "admin", label: "Admin" },
    { value: "editor", label: "Editor" },
    { value: "asesor", label: "Asesor" },
  ];

  return (
    <div className="user-form-container">
      <ActionToast feedback={feedback} onClose={() => setFeedback(null)} />
      {feedback?.tone === "error" && <ErrorBanner title="Error" message={feedback.message} />}

      <form onSubmit={handleSubmit} className="property-form" noValidate>
        <section className="card form-section" aria-labelledby="basic-info-heading">
          <header className="card-head">
            <h2 id="basic-info-heading" className="section-title">
              <Icon name="info" size={18} /> Información del usuario
            </h2>
          </header>
          <div className="card-body form-grid">
            {!isEditing && (
              <Input
                label="Email *"
                name="email"
                type="email"
                value={formData.email}
                onChange={handleChange}
                placeholder="admin@expresedi.com"
                required
                maxLength={255}
              />
            )}
            {isEditing && (
              <div className="field">
                <label className="field-label">Email</label>
                <input className="field-input" value={formData.email} disabled />
                <span className="field-hint">El email no se puede cambiar</span>
              </div>
            )}
            <Input
              label="Nombre *"
              name="name"
              value={formData.name}
              onChange={handleChange}
              placeholder="Juan Pérez"
              required
              maxLength={160}
            />
            {!isEditing && (
              <Input
                label="Contraseña *"
                name="password"
                type="password"
                value={formData.password}
                onChange={handleChange}
                placeholder="••••••••"
                required
                minLength={8}
                maxLength={128}
              />
            )}
            {isEditing && (
              <Input
                label="Nueva contraseña (opcional)"
                name="password"
                type="password"
                value={formData.password}
                onChange={handleChange}
                placeholder="Dejar vacío para no cambiar"
                minLength={8}
                maxLength={128}
              />
            )}
            <Select
              label="Rol *"
              name="role"
              value={formData.role}
              onChange={handleChange}
              options={ROLE_OPTIONS}
              required
            />
            <label className="checkbox-field">
              <input
                type="checkbox"
                name="is_active"
                checked={formData.is_active}
                onChange={handleChange}
              />
              <span>Usuario activo</span>
            </label>
          </div>
        </section>

        <footer className="form-footer">
          <Link href="/usuarios" className="btn btn-secondary">
            <Icon name="x" size={16} />
            Cancelar
          </Link>
          <Button type="submit" loading={loading} className="btn-primary">
            {loading ? "Guardando..." : isEditing ? "Actualizar" : "Crear usuario"}
            <Icon name="save" size={16} />
          </Button>
        </footer>
      </form>

      {isEditing && userId && (
        <ConfirmDialog
          open={showDeleteConfirm}
          onConfirm={handleDelete}
          onCancel={() => setShowDeleteConfirm(false)}
          title="Eliminar usuario"
          description={`Se eliminará "${initialData?.name}" (${initialData?.email}). Esta acción no se puede deshacer.`}
          danger={true}
        />
      )}
    </div>
  );
}