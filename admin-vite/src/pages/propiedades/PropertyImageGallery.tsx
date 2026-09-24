"use client";

import { useState, useEffect } from "react";
import { Icon } from "../../components/icons";
import {
  reorderPropertyImages,
  setPropertyCoverImage,
  deletePropertyImage,
  uploadPropertyImage,
  updatePropertyImageMetadata,
} from "./actions";

interface PropertyImageGalleryProps {
  propertyId: string;
  onImagesChange: () => void;
}

interface ImageData {
  filename: string;
  name: string;
  description: string;
  isCover: boolean;
  sortOrder: number;
  group: string;
  group_label: string;
  extra_name: string;
}

export function PropertyImageGallery({ propertyId, onImagesChange }: PropertyImageGalleryProps) {
  const [images, setImages] = useState<ImageData[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [dragOverIndex, setDragOverIndex] = useState<number | null>(null);
  const [editingIndex, setEditingIndex] = useState<number | null>(null);
  const [editName, setEditName] = useState("");
  const [editDescription, setEditDescription] = useState("");

  useEffect(() => {
    loadImages();
  }, [propertyId]);

  const loadImages = async () => {
    try {
      const res = await fetch(`/api/properties/${propertyId}`);
      if (res.ok) {
        const data = await res.json();
        if (data.images && Array.isArray(data.images)) {
          setImages(
            data.images.map((img: any, idx: number) => ({
              filename: img.filename,
              name: img.name || "",
              description: img.description || "",
              isCover: img.is_cover || idx === 0,
              sortOrder: img.sort_order || idx,
              group: img.group || "general",
              group_label: img.group_label || img.group || "general",
              extra_name: img.extra_name || "",
            }))
          );
        } else {
          setImages([]);
        }
      }
    } catch (e) {
      console.error("Error loading images:", e);
      setImages([]);
    } finally {
      setLoading(false);
    }
  };

  const handleImageUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || []);
    if (files.length === 0) return;

    setUploading(true);
    for (const file of files) {
      try {
        const result = await uploadPropertyImage(propertyId, file);
        if (!result.ok) {
          alert(result.error);
        }
      } catch (e) {
        alert("Error subiendo imagen");
      }
    }
    await loadImages();
    onImagesChange();
    setUploading(false);
    e.target.value = "";
  };

  const handleDelete = async (filename: string) => {
    if (!confirm(`¿Eliminar la imagen ${filename}?`)) return;
    try {
      const result = await deletePropertyImage(propertyId, filename);
      if (result.ok) {
        setImages((prev) => prev.filter((f) => f.filename !== filename));
        onImagesChange();
      } else {
        alert(result.error);
      }
    } catch (e) {
      alert("Error eliminando imagen");
    }
  };

  const handleSetCover = async (filename: string) => {
    try {
      const result = await setPropertyCoverImage(propertyId, filename);
      if (result.ok) {
        await loadImages();
        onImagesChange();
      } else {
        alert(result.error);
      }
    } catch (e) {
      alert("Error cambiando portada");
    }
  };

  const startEdit = (index: number) => {
    const img = images[index];
    setEditingIndex(index);
    setEditName(img.name);
    setEditDescription(img.description);
  };

  const saveEdit = async (index: number) => {
    const img = images[index];
    try {
      const result = await updatePropertyImageMetadata(propertyId, img.filename, editName, editDescription);
      if (result.ok) {
        setImages((prev) =>
          prev.map((im, i) => (i === index ? { ...im, name: editName, description: editDescription } : im))
        );
        setEditingIndex(null);
        onImagesChange();
      } else {
        alert(result.error);
      }
    } catch (e) {
      alert("Error guardando cambios");
    }
  };

  const cancelEdit = () => {
    setEditingIndex(null);
    setEditName("");
    setEditDescription("");
  };

  const handleDragStart = (e: React.DragEvent, index: number) => {
    e.dataTransfer.setData("text/plain", index.toString());
    e.dataTransfer.effectAllowed = "move";
    setDragging(true);
  };

  const handleDragOver = (e: React.DragEvent, index: number) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    setDragOverIndex(index);
  };

  const handleDragLeave = () => {
    setDragOverIndex(null);
  };

  const handleDrop = (e: React.DragEvent, index: number) => {
    e.preventDefault();
    const fromIndex = parseInt(e.dataTransfer.getData("text/plain"), 10);
    if (fromIndex !== index) {
      const newImages = [...images];
      const [removed] = newImages.splice(fromIndex, 1);
      newImages.splice(index, 0, removed);
      setImages(newImages);
    }
    setDragging(false);
    setDragOverIndex(null);
  };

  const handleDragEnd = () => {
    setDragging(false);
    setDragOverIndex(null);
  };

  const saveOrder = async () => {
    try {
      const filenames = images.map((img) => img.filename);
      const result = await reorderPropertyImages(propertyId, filenames);
      if (result.ok) {
        onImagesChange();
      } else {
        alert(result.error);
        await loadImages(); // Revert on error
      }
    } catch (e) {
      alert("Error guardando orden");
      await loadImages();
    }
  };

  if (loading) {
    return (
      <div className="image-gallery-section">
        <div className="gallery-header">
          <h3 className="gallery-title">
            <Icon name="image" size={16} />
            Galería de imágenes
          </h3>
        </div>
        <div className="image-gallery-skeleton" aria-label="Cargando imágenes">
          <div className="skeleton-image" />
          <div className="skeleton-image" />
          <div className="skeleton-image" />
        </div>
      </div>
    );
  }

  return (
    <div className="image-gallery-section">
      <div className="gallery-header">
        <h3 className="gallery-title">
          <Icon name="image" size={16} />
          Galería de imágenes
        </h3>
        <div className="gallery-actions">
          <label className="btn btn-secondary btn-sm">
            <Icon name="upload" size={14} />
            Subir
            <input
              type="file"
              accept="image/jpeg,image/png,image/webp"
              multiple
              onChange={handleImageUpload}
              disabled={uploading}
              style={{ display: "none" }}
            />
          </label>
          {images.length > 1 && (
            <button
              className="btn btn-primary btn-sm"
              onClick={saveOrder}
              disabled={!dragging}
            >
              <Icon name="save" size={14} />
              Guardar orden
            </button>
          )}
        </div>
      </div>

      {images.length === 0 ? (
        <div className="gallery-empty">
          <Icon name="image" size={48} />
          <p>No hay imágenes. Sube la primera para que sea la portada.</p>
        </div>
      ) : (
        <div
          className={`image-gallery ${dragging ? "dragging" : ""}`}
          role="list"
          aria-label="Galería de imágenes de la propiedad"
        >
          {images.map((img, index) => (
            <div
              key={img.filename}
              className={`image-item ${img.isCover ? "is-cover" : ""} ${dragOverIndex === index ? "drag-over" : ""} ${editingIndex === index ? "editing" : ""}`}
              role="listitem"
              draggable={editingIndex === null}
              onDragStart={e => handleDragStart(e, index)}
              onDragOver={e => handleDragOver(e, index)}
              onDragLeave={handleDragLeave}
              onDrop={e => handleDrop(e, index)}
              onDragEnd={handleDragEnd}
            >
              <div className="image-wrapper">
                <img
                  src={`/api/properties/${propertyId}/images/${img.filename}`}
                  alt={`Imagen ${index + 1}`}
                  width={300}
                  height={200}
                  className="image-thumb"
                  loading="lazy"
                />
                {img.isCover && (
                  <span className="cover-badge">
                    <Icon name="star" size={12} /> Portada
                  </span>
                )}
              </div>

              {editingIndex === index ? (
                <div className="image-edit-form">
                  <div className="edit-field">
                    <label className="form-label">Nombre</label>
                    <input
                      type="text"
                      value={editName}
                      onChange={(e) => setEditName(e.target.value)}
                      placeholder="Ej: Sala principal"
                      className="form-input"
                      autoFocus
                    />
                  </div>
                  <div className="edit-field">
                    <label className="form-label">Descripción</label>
                    <input
                      type="text"
                      value={editDescription}
                      onChange={(e) => setEditDescription(e.target.value)}
                      placeholder="Ej: Sala amplia con iluminación natural..."
                      className="form-input"
                    />
                  </div>
                  <div className="edit-actions">
                    <button type="button" className="btn btn-primary btn-sm" onClick={() => saveEdit(index)}>
                      <Icon name="check" size={14} /> Guardar
                    </button>
                    <button type="button" className="btn btn-secondary btn-sm" onClick={cancelEdit}>
                      <Icon name="x" size={14} /> Cancelar
                    </button>
                  </div>
                </div>
              ) : (
                <>
                  <div className="image-meta-display">
                    {(img.group_label || img.group) && img.group !== "general" && (
                      <div className="meta-group">
                        {img.group === "extra" && img.extra_name
                          ? img.extra_name
                          : img.group_label || img.group}
                      </div>
                    )}
                    {img.name && <div className="meta-name">{img.name}</div>}
                    {img.description && <div className="meta-description">{img.description}</div>}
                  </div>
                  <div className="image-controls">
                    <button
                      type="button"
                      className="icon-btn"
                      onClick={() => startEdit(index)}
                      title="Editar metadata"
                      aria-label="Editar metadata"
                    >
                      <Icon name="edit" size={16} />
                    </button>
                    {!img.isCover && (
                      <button
                        type="button"
                        className="icon-btn"
                        onClick={() => handleSetCover(img.filename)}
                        title="Establecer como portada"
                        aria-label="Establecer como portada"
                      >
                        <Icon name="star" size={16} />
                      </button>
                    )}
                    <button
                      type="button"
                      className="icon-btn danger"
                      onClick={() => handleDelete(img.filename)}
                      title="Eliminar"
                      aria-label="Eliminar imagen"
                    >
                      <Icon name="trash" size={16} />
                    </button>
                  </div>
                  <div className="image-index">{index + 1}</div>
                </>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}