"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import Image from "next/image";
import { updatePropertyStatus, deleteProperty, deletePropertyImage, reorderPropertyImages, setPropertyCoverImage, uploadPropertyImage } from "../actions";
import { PropertyImageGallery } from "./PropertyImageGallery";
import { PropertyStatusControl } from "@/components/PropertyStatusControl";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { ErrorBanner } from "@/components/ErrorBanner";
import { ActionToast, type Feedback } from "@/components/ActionToast";
import { Icon } from "@/components/icons";
import { formatMoney } from "@/lib/format";
import { statusMeta, operationLabel } from "@/lib/status";

interface PropertyDetailProps {
  property: {
    id: string;
    code: string;
    title: string;
    property_type: string;
    operation: string;
    price: number;
    currency: string;
    city: string;
    neighborhood: string;
    address: string;
    area_m2: number | null;
    bedrooms: number | null;
    bathrooms: number | null;
    parking_spaces: number | null;
    status: string;
    features: string[];
    description: string;
    project: string | null;
    latitude: number | null;
    longitude: number | null;
  };
  error: string;
}

export function PropertyDetail({ property, error }: PropertyDetailProps) {
  const router = useRouter();
  const [feedback, setFeedback] = useState<Feedback | null>(null);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [statusLoading, setStatusLoading] = useState(false);

  const handleStatusChange = async (newStatus: string) => {
    setStatusLoading(true);
    try {
      const result = await updatePropertyStatus(property.id, newStatus);
      if (result.ok) {
        setFeedback({ tone: "ok", message: `${property.code} actualizada a «${statusMeta(newStatus).label}».` });
        router.refresh();
      } else {
        setFeedback({ tone: "error", message: `No se pudo actualizar: ${result.error}` });
      }
    } catch (e) {
      setFeedback({ tone: "error", message: "Error actualizando estado" });
    } finally {
      setStatusLoading(false);
    }
  };

  const handleDelete = async () => {
    try {
      const result = await deleteProperty(property.id);
      if (result.ok) {
        router.push("/propiedades");
      } else {
        setFeedback({ tone: "error", message: result.error });
      }
    } catch (e) {
      setFeedback({ tone: "error", message: "Error eliminando propiedad" });
    }
    setShowDeleteConfirm(false);
  };

  const status = statusMeta(property.status);

  return (
    <div className="property-detail">
      <ActionToast feedback={feedback} onClose={() => setFeedback(null)} />
      {error && <ErrorBanner message={error} />}

      <section className="card" aria-labelledby="detail-heading">
        <header className="card-head">
          <div className="detail-header">
            <div>
              <h1 id="detail-heading" className="detail-title">{property.title}</h1>
              <div className="detail-meta">
                <span className="detail-code">{property.code}</span>
                <span className="detail-type">{property.property_type}</span>
                <span className="detail-operation">{operationLabel(property.operation)}</span>
              </div>
            </div>
            <div className="detail-price">{formatMoney(property.price, property.currency)}</div>
          </div>
        </header>

        <div className="card-body">
          <div className="detail-grid">
            <div className="detail-main">
              <PropertyImageGallery
                propertyId={property.id}
                onImagesChange={() => router.refresh()}
              />

              <div className="detail-info">
                <section className="info-section">
                  <h2 className="info-heading">
                    <Icon name="map-pin" size={16} />
                    Ubicación
                  </h2>
                  <dl className="info-list">
                    <div><dt>Ciudad</dt><dd>{property.city}</dd></div>
                    {property.neighborhood && <div><dt>Barrio</dt><dd>{property.neighborhood}</dd></div>}
                    {property.address && <div><dt>Dirección</dt><dd>{property.address}</dd></div>}
                    {property.latitude && property.longitude && (
                      <div>
                        <dt>Coordenadas</dt>
                        <dd>{property.latitude.toFixed(6)}, {property.longitude.toFixed(6)}</dd>
                      </div>
                    )}
                  </dl>
                </section>

                <section className="info-section">
                  <h2 className="info-heading">
                    <Icon name="home" size={16} />
                    Características
                  </h2>
                  <dl className="info-list">
                    {property.area_m2 && <div><dt>Área</dt><dd>{property.area_m2} m²</dd></div>}
                    {property.bedrooms !== null && <div><dt>Habitaciones</dt><dd>{property.bedrooms}</dd></div>}
                    {property.bathrooms !== null && <div><dt>Baños</dt><dd>{property.bathrooms}</dd></div>}
                    {property.parking_spaces !== null && <div><dt>Parqueaderos</dt><dd>{property.parking_spaces}</dd></div>}
                    {property.project && <div><dt>Proyecto</dt><dd>{property.project}</dd></div>}
                  </dl>
                </section>

                {property.features.length > 0 && (
                  <section className="info-section">
                    <h2 className="info-heading">
                      <Icon name="tag" size={16} />
                      Comodidades
                    </h2>
                    <ul className="features-list">
                      {property.features.map(f => (
                        <li key={f}><Icon name="check" size={14} /> {f}</li>
                      ))}
                    </ul>
                  </section>
                )}

                {property.description && (
                  <section className="info-section">
                    <h2 className="info-heading">
                      <Icon name="file-text" size={16} />
                      Descripción
                    </h2>
                    <p className="description-text">{property.description}</p>
                  </section>
                )}
              </div>
            </div>

            <aside className="detail-sidebar">
              <div className="card sticky-sidebar">
                <header className="card-head">
                  <h2 className="section-title">Estado comercial</h2>
                </header>
                <div className="card-body">
                  <div className="status-display">
                    <span className={`status-badge status-${status.tone}`}>{status.label}</span>
                    <PropertyStatusControl
                      id={property.id}
                      code={property.code}
                      status={property.status}
                    />
                  </div>
                </div>
              </div>

              <div className="card sticky-sidebar">
                <header className="card-head">
                  <h2 className="section-title">Acciones</h2>
                </header>
                <div className="card-body action-list">
                  <Link href={`/propiedades/${property.id}/editar`} className="action-item">
                    <Icon name="edit" size={16} />
                    Editar propiedad
                  </Link>
                  <button
                    type="button"
                    className="action-item action-danger"
                    onClick={() => setShowDeleteConfirm(true)}
                  >
                    <Icon name="trash" size={16} />
                    Eliminar propiedad
                  </button>
                  <Link href="/propiedades" className="action-item">
                    <Icon name="arrow-left" size={16} />
                    Volver al listado
                  </Link>
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
        title="Eliminar propiedad"
        description={`Se eliminará "${property.title}" (${property.code}), sus imágenes y cualquier cita asociada. Esta acción no se puede deshacer.`}
        danger
        confirmLabel="Eliminar"
      />
    </div>
  );
}