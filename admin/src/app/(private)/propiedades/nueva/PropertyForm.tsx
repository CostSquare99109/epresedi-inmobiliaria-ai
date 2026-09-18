"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { createProperty, uploadPropertyImage } from "../actions";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { Textarea } from "@/components/ui/Textarea";
import { CheckboxGroup } from "@/components/ui/CheckboxGroup";
import { ErrorBanner } from "@/components/ErrorBanner";
import { ActionToast, type Feedback } from "@/components/ActionToast";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { Icon } from "@/components/icons";
import { PROPERTY_TYPES, OPERATIONS, FEATURES } from "@/lib/property-constants";
import { formatMoney } from "@/lib/format";

interface PropertyFormProps {
  mode: "create" | "edit";
  initialData?: any;
  propertyId?: string;
}

export function PropertyForm({ mode, initialData, propertyId }: PropertyFormProps) {
  const router = useRouter();
  const [feedback, setFeedback] = useState<Feedback | null>(null);
  const [loading, setLoading] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [images, setImages] = useState<string[]>(initialData?.images || []);
  const [uploadingImage, setUploadingImage] = useState(false);

  const [formData, setFormData] = useState({
    title: initialData?.title || "",
    property_type: initialData?.property_type || "casa",
    operation: initialData?.operation || "SALE",
    price: initialData?.price || "",
    currency: initialData?.currency || "COP",
    city: initialData?.city || "",
    neighborhood: initialData?.neighborhood || "",
    address: initialData?.address || "",
    area_m2: initialData?.area_m2 || "",
    bedrooms: initialData?.bedrooms || "",
    bathrooms: initialData?.bathrooms || "",
    parking_spaces: initialData?.parking_spaces || "",
    features: initialData?.features || [],
    description: initialData?.description || "",
    project_id: initialData?.project_id || "",
    status: initialData?.status || "AVAILABLE",
  });

  const handleChange = (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) => {
    const { name, value, type } = e.target;
    setFormData(prev => ({
      ...prev,
      [name]: type === "checkbox" ? (e.target as HTMLInputElement).checked : value,
    }));
    setFeedback(null);
  };

  const handleCheckboxChange = (feature: string, checked: boolean) => {
    setFormData(prev => ({
      ...prev,
      features: checked
        ? [...prev.features, feature]
        : prev.features.filter((f: string) => f !== feature),
    }));
  };

  const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setFeedback(null);
    setLoading(true);

    const submitData = new FormData();
    Object.entries(formData).forEach(([key, value]) => {
      if (value !== "" && value !== undefined && value !== null) {
        if (key === "features") {
          submitData.append(key, JSON.stringify(value));
        } else {
          submitData.append(key, String(value));
        }
      }
    });

    try {
      const result = await createProperty(submitData);
      if (result.ok) {
        setFeedback({ tone: "ok", message: "Propiedad creada correctamente" });
        setTimeout(() => router.push(`/propiedades/${result.property.id}`), 1500);
      } else {
        setFeedback({ tone: "error", message: result.error });
      }
    } catch (e) {
      setFeedback({ tone: "error", message: e instanceof Error ? e.message : "Error desconocido" });
    } finally {
      setLoading(false);
    }
  };

  const handleImageUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !propertyId) return;

    setUploadingImage(true);
    setFeedback(null);
    
    try {
      const result = await uploadPropertyImage(propertyId, file);
      if (result.ok) {
        // Refresh images list
        const res = await fetch(`/api/proxy/properties/${propertyId}/images`);
        const data = await res.json();
        setImages(data.images || []);
        setFeedback({ tone: "ok", message: "Imagen subida correctamente" });
      } else {
        setFeedback({ tone: "error", message: result.error });
      }
    } catch (e) {
      setFeedback({ tone: "error", message: e instanceof Error ? e.message : "Error subiendo imagen" });
    } finally {
      setUploadingImage(false);
      e.target.value = "";
    }
  };

  const handleDeleteImage = async (filename: string) => {
    if (!propertyId) return;
    try {
      const res = await fetch(`/api/proxy/properties/${propertyId}/images/${filename}`, {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
      });
      if (res.ok) {
        setImages(prev => prev.filter(f => f !== filename));
        setFeedback({ tone: "ok", message: "Imagen eliminada" });
      }
    } catch (e) {
      setFeedback({ tone: "error", message: "Error eliminando imagen" });
    }
  };

  const handleSetCover = async (filename: string) => {
    if (!propertyId) return;
    try {
      const res = await fetch(`/api/proxy/properties/${propertyId}/images/${filename}/cover`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
      });
      if (res.ok) {
        const data = await res.json();
        setImages(data.images);
        setFeedback({ tone: "ok", message: "Portada actualizada" });
      }
    } catch (e) {
      setFeedback({ tone: "error", message: "Error cambiando portada" });
    }
  };

  const handleReorder = async (newOrder: string[]) => {
    if (!propertyId) return;
    try {
      const res = await fetch(`/api/proxy/properties/${propertyId}/images/reorder`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ filenames: newOrder }),
      });
      if (res.ok) {
        const data = await res.json();
        setImages(data.images);
        setFeedback({ tone: "ok", message: "Orden actualizado" });
      }
    } catch (e) {
      setFeedback({ tone: "error", message: "Error reordenando" });
    }
  };

  const isEditing = mode === "edit";

  return (
    <div className="property-form-container">
      <ActionToast feedback={feedback} onClose={() => setFeedback(null)} />
      {feedback?.tone === "error" && <ErrorBanner title="Error" message={feedback.message} />}

      <form onSubmit={handleSubmit} className="property-form" noValidate>
        <section className="card form-section" aria-labelledby="basic-info-heading">
          <header className="card-head">
            <h2 id="basic-info-heading" className="section-title">
              <Icon name="info" size={18} /> Información básica
            </h2>
          </header>
          <div className="card-body form-grid">
            <Input
              label="Título *"
              name="title"
              value={formData.title}
              onChange={handleChange}
              placeholder="Ej: Casa familiar 3 habitaciones cerca del centro"
              required
              maxLength={200}
            />
            <Select
              label="Tipo de propiedad *"
              name="property_type"
              value={formData.property_type}
              onChange={handleChange}
              options={PROPERTY_TYPES.map(t => ({ value: t, label: t.charAt(0).toUpperCase() + t.slice(1) }))}
              required
            />
            <Select
              label="Operación *"
              name="operation"
              value={formData.operation}
              onChange={handleChange}
              options={OPERATIONS.map(o => ({ value: o, label: o === "SALE" ? "Venta" : "Arriendo" }))}
              required
            />
            <Input
              label="Precio *"
              name="price"
              type="number"
              step="0.01"
              min="0.01"
              value={formData.price}
              onChange={handleChange}
              placeholder="0.00"
              required
            />
            <Select
              label="Moneda"
              name="currency"
              value={formData.currency}
              onChange={handleChange}
              options={[{ value: "COP", label: "COP (Pesos Colombianos)" }]}
            />
          </div>
        </section>

        <section className="card form-section" aria-labelledby="location-heading">
          <header className="card-head">
            <h2 id="location-heading" className="section-title">
              <Icon name="map-pin" size={18} /> Ubicación
            </h2>
          </header>
          <div className="card-body form-grid">
            <Input
              label="Ciudad *"
              name="city"
              value={formData.city}
              onChange={handleChange}
              placeholder="Ej: Carepa"
              required
              maxLength={80}
            />
            <Input
              label="Barrio / Sector"
              name="neighborhood"
              value={formData.neighborhood}
              onChange={handleChange}
              placeholder="Ej: El Centro"
              maxLength={120}
            />
            <Input
              label="Dirección"
              name="address"
              value={formData.address}
              onChange={handleChange}
              placeholder="Ej: Calle 45 #23-10"
              maxLength={240}
            />
          </div>
        </section>

        <section className="card form-section" aria-labelledby="characteristics-heading">
          <header className="card-head">
            <h2 id="characteristics-heading" className="section-title">
              <Icon name="home" size={18} /> Características
            </h2>
          </header>
          <div className="card-body form-grid">
            <Input
              label="Área (m²)"
              name="area_m2"
              type="number"
              step="0.01"
              min="0"
              value={formData.area_m2}
              onChange={handleChange}
              placeholder="Ej: 120"
            />
            <Input
              label="Habitaciones"
              name="bedrooms"
              type="number"
              min="0"
              max="99"
              value={formData.bedrooms}
              onChange={handleChange}
              placeholder="Ej: 3"
            />
            <Input
              label="Baños"
              name="bathrooms"
              type="number"
              min="0"
              max="99"
              value={formData.bathrooms}
              onChange={handleChange}
              placeholder="Ej: 2"
            />
            <Input
              label="Parqueaderos"
              name="parking_spaces"
              type="number"
              min="0"
              max="99"
              value={formData.parking_spaces}
              onChange={handleChange}
              placeholder="Ej: 1"
            />
          </div>
        </section>

        <section className="card form-section" aria-labelledby="features-heading">
          <header className="card-head">
            <h2 id="features-heading" className="section-title">
              <Icon name="tag" size={18} /> Comodidades
            </h2>
          </header>
          <div className="card-body">
            <CheckboxGroup
              name="features"
              options={FEATURES}
              value={formData.features}
              onChange={handleCheckboxChange}
              columns={3}
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
              placeholder="Describe la propiedad, sus acabados, entorno, cercanías..."
              rows={5}
            />
          </div>
        </section>

        {isEditing && (
          <section className="card form-section" aria-labelledby="status-heading">
            <header className="card-head">
              <h2 id="status-heading" className="section-title">
                <Icon name="toggle" size={18} /> Estado comercial
              </h2>
            </header>
            <div className="card-body">
              <Select
                label="Estado"
                name="status"
                value={formData.status}
                onChange={handleChange}
                options={[
                  { value: "AVAILABLE", label: "Disponible" },
                  { value: "RESERVED", label: "Reservada" },
                  { value: "SOLD", label: "Vendida" },
                  { value: "INACTIVE", label: "Inactiva" },
                ]}
              />
            </div>
          </section>
        )}

        {propertyId && (
          <section className="card form-section" aria-labelledby="images-heading">
            <header className="card-head">
              <h2 id="images-heading" className="section-title">
                <Icon name="image" size={18} /> Imágenes
              </h2>
            </header>
            <div className="card-body">
              <div className="image-upload">
                <label className="btn btn-secondary image-upload-label">
                  <Icon name="upload" size={16} />
                  <span>Subir imágenes</span>
                  <input
                    type="file"
                    accept="image/jpeg,image/png,image/webp"
                    multiple
                    onChange={handleImageUpload}
                    disabled={uploadingImage}
                    style={{ display: "none" }}
                  />
                </label>
                {uploadingImage && <span className="uploading">Subiendo...</span>}
              </div>

              {images.length > 0 && (
                <div className="image-gallery" role="list" aria-label="Galería de imágenes">
                  {images.map((filename, index) => (
                    <div key={filename} className="image-item" role="listitem">
                      <img
                        src={`/api/proxy/properties/${propertyId}/images/${filename}`}
                        alt={`Imagen ${index + 1}`}
                        loading="lazy"
                        width={200}
                        height={150}
                      />
                      <div className="image-actions">
                        {index !== 0 && (
                          <Button
                            type="button"
                            variant="ghost"
                            size="sm"
                            onClick={() => handleSetCover(filename)}
                            aria-label={`Establecer como portada`}
                          >
                            <Icon name="star" size={14} />
                          </Button>
                        )}
                        <Button
                          type="button"
                          variant="danger"
                          size="sm"
                          onClick={() => handleDeleteImage(filename)}
                          aria-label={`Eliminar imagen`}
                        >
                          <Icon name="trash" size={14} />
                        </Button>
                      </div>
                      {index === 0 && (
                        <span className="cover-badge">Portada</span>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </section>
        )}

        <footer className="form-footer">
          <Link href="/propiedades" className="btn btn-secondary">
            <Icon name="x" size={16} />
            Cancelar
          </Link>
          <Button type="submit" loading={loading} className="btn-primary">
            {loading ? "Guardando..." : isEditing ? "Actualizar" : "Crear propiedad"}
            <Icon name="save" size={16} />
          </Button>
        </footer>
      </form>

      {isEditing && propertyId && (
        <ConfirmDialog
          open={showDeleteConfirm}
          onConfirm={async () => {
            const res = await fetch(`/api/proxy/properties/${propertyId}`, {
              method: "DELETE",
              headers: { "Content-Type": "application/json" },
            });
            if (res.ok) {
              router.push("/propiedades");
            } else {
              setFeedback({ tone: "error", message: "Error eliminando propiedad" });
            }
            setShowDeleteConfirm(false);
          }}
          onCancel={() => setShowDeleteConfirm(false)}
          title="Eliminar propiedad"
          description="Esta acción no se puede deshacer. Se eliminarán la propiedad, sus imágenes y cualquier cita asociada."
          danger={true}
        />
      )}
    </div>
  );
}