"use client";

import { useState, useEffect } from "react";
import Image from "next/image";
import { Icon } from "@/components/icons";
import { reorderPropertyImages, setPropertyCoverImage, deletePropertyImage, uploadPropertyImage } from "../actions";

interface PropertyImageGalleryProps {
  propertyId: string;
  onImagesChange: () => void;
}

export function PropertyImageGallery({ propertyId, onImagesChange }: PropertyImageGalleryProps) {
  const [images, setImages] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [dragOverIndex, setDragOverIndex] = useState<number | null>(null);

  useEffect(() => {
    loadImages();
  }, [propertyId]);

  const loadImages = async () => {
    try {
      const res = await fetch(`/api/proxy/properties/${propertyId}/images`);
      if (res.ok) {
        const data = await res.json();
        setImages(data.images || []);
      }
    } catch (e) {
      console.error("Error loading images:", e);
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
        setImages(prev => prev.filter(f => f !== filename));
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
      const result = await reorderPropertyImages(propertyId, images);
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
      <div className="image-gallery-skeleton" aria-label="Cargando imágenes">
        <div className="skeleton-image" />
        <div className="skeleton-image" />
        <div className="skeleton-image" />
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
          {images.map((filename, index) => (
            <div
              key={filename}
              className={`image-item ${index === 0 ? "is-cover" : ""} ${dragOverIndex === index ? "drag-over" : ""}`}
              role="listitem"
              draggable
              onDragStart={e => handleDragStart(e, index)}
              onDragOver={e => handleDragOver(e, index)}
              onDragLeave={handleDragLeave}
              onDrop={e => handleDrop(e, index)}
              onDragEnd={handleDragEnd}
            >
              <div className="image-wrapper">
                <Image
                  src={`/api/proxy/properties/${propertyId}/images/${filename}`}
                  alt={`Imagen ${index + 1}`}
                  width={300}
                  height={200}
                  className="image-thumb"
                  loading="lazy"
                />
                {index === 0 && (
                  <span className="cover-badge">
                    <Icon name="star" size={12} /> Portada
                  </span>
                )}
              </div>
              <div className="image-controls">
                {index !== 0 && (
                  <button
                    type="button"
                    className="icon-btn"
                    onClick={() => handleSetCover(filename)}
                    title="Establecer como portada"
                    aria-label="Establecer como portada"
                  >
                    <Icon name="star" size={16} />
                  </button>
                )}
                <button
                  type="button"
                  className="icon-btn danger"
                  onClick={() => handleDelete(filename)}
                  title="Eliminar"
                  aria-label="Eliminar imagen"
                >
                  <Icon name="trash" size={16} />
                </button>
              </div>
              <div className="image-index">{index + 1}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}