"use client";

import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { Link } from "react-router-dom";
import { backend, type PropertyDTO } from "../../api/client";
import { deleteProperty } from "./actions";
import { PageHeader } from "../../components/PageHeader";
import { LoadingState } from "../../components/LoadingState";
import { PropertyImageGallery } from "./PropertyImageGallery";
import { PropertyStatusControl } from "../../components/PropertyStatusControl";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { ErrorBanner } from "../../components/ErrorBanner";
import { ActionToast, type Feedback } from "../../components/ActionToast";
import { Icon } from "../../components/icons";
import { formatMoney } from "../../lib/format";
import { statusMeta, operationLabel } from "../../lib/status";
import { formatFloorsDisplay } from "../../lib/floors";

interface PropertyDetailProps {
  property: PropertyDTO;
  error: string;
}

function PropertyDetailView({ property, error }: PropertyDetailProps) {
  const navigate = useNavigate();
  const [feedback, setFeedback] = useState<Feedback | null>(null);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);

  const handleDelete = async () => {
    try {
      const result = await deleteProperty(property.id);
      if (result.ok) {
        navigate("/propiedades");
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
                onImagesChange={() => navigate(0)}
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
                    {property.street && <div><dt>Calle</dt><dd>{property.street}</dd></div>}
                    {property.street_number && <div><dt>Número</dt><dd>{property.street_number}</dd></div>}
                    {property.nomenclatura && <div><dt>Nomenclatura</dt><dd>{property.nomenclatura}</dd></div>}
                    {property.descriptive_location && <div><dt>Cómo llegar</dt><dd>{property.descriptive_location}</dd></div>}
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
                    {(() => {
                      const display = formatFloorsDisplay(
                        property.floors, property.floor_offer_type, property.offered_floors, property.operation
                      );
                      return display ? <div><dt>Pisos</dt><dd>{display}</dd></div> : null;
                    })()}
                    {property.bedrooms !== null && <div><dt>Habitaciones</dt><dd>{property.bedrooms}</dd></div>}
                    {property.bedrooms_description && <div><dt>Detalle habitaciones</dt><dd>{property.bedrooms_description}</dd></div>}
                    {property.bathrooms !== null && <div><dt>Baños</dt><dd>{property.bathrooms}</dd></div>}
                    {property.bathrooms_description && <div><dt>Detalle baños</dt><dd>{property.bathrooms_description}</dd></div>}
                    {property.living_room_description && <div><dt>Sala</dt><dd>{property.living_room_description}</dd></div>}
                    {property.laundry_area_description && <div><dt>Zona de lavado</dt><dd>{property.laundry_area_description}</dd></div>}
                    {property.has_parking !== undefined && <div><dt>Parqueadero</dt><dd>{property.has_parking ? "Sí" : "No"}</dd></div>}
                    {property.parking_description && <div><dt>Detalle parqueadero</dt><dd>{property.parking_description}</dd></div>}
                    {property.parking_spaces !== null && <div><dt>Parqueaderos (cant.)</dt><dd>{property.parking_spaces}</dd></div>}
                    {property.has_kitchen !== undefined && <div><dt>Cocina</dt><dd>{property.has_kitchen ? "Sí" : "No"}</dd></div>}
                    {property.has_living_room !== undefined && <div><dt>Sala</dt><dd>{property.has_living_room ? "Sí" : "No"}</dd></div>}
                    {property.has_laundry_area !== undefined && <div><dt>Zona de lavado</dt><dd>{property.has_laundry_area ? "Sí" : "No"}</dd></div>}
                    {property.branch && <div><dt>Sede</dt><dd>{property.branch}</dd></div>}
                  </dl>
                </section>

                {property.rent_price !== undefined && property.rent_price !== null && (
                  <section className="info-section">
                    <h2 className="info-heading">
                      <Icon name="dollar-sign" size={16} />
                      Precio de Alquiler
                    </h2>
                    <dl className="info-list">
                      <div><dt>Precio mensual</dt><dd>{formatMoney(property.rent_price, property.currency)}</dd></div>
                      {property.services_included && <div><dt>Servicios públicos</dt><dd>{property.services_included === "incluye" ? "Incluye" : "No incluye"}</dd></div>}
                    </dl>
                  </section>
                )}

                {property.visiting_hours && property.visiting_hours.length > 0 && (
                  <section className="info-section">
                    <h2 className="info-heading">
                      <Icon name="calendar" size={16} />
                      Horarios de Visita
                    </h2>
                    <div className="visiting-hours-display">
                      {property.visiting_hours.map((day: any) => (
                        !day.is_closed && day.intervals && day.intervals.length > 0 && (
                          <div key={day.weekday} className="visiting-day-display">
                            <strong>{["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"][day.weekday]}:</strong>
                            <span>
                              {day.intervals.map((interval: any) => `${interval.start}–${interval.end}`).join(", ")}
                            </span>
                          </div>
                        )
                      ))}
                    </div>
                  </section>
                )}

                {property.features.length > 0 && (
                  <section className="info-section">
                    <h2 className="info-heading">
                      <Icon name="tag" size={16} />
                      Extras y características adicionales
                    </h2>
                    <ul className="features-list">
                      {property.features.map((f) => (
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
                  <Link to={`/propiedades/${property.id}/editar`} className="action-item">
                    <Icon name="edit" size={14} />
                    Editar propiedad
                  </Link>
                  <button
                    type="button"
                    className="action-item action-danger"
                    onClick={() => setShowDeleteConfirm(true)}
                  >
                    <Icon name="trash" size={14} />
                    Eliminar propiedad
                  </button>
                  <Link to="/propiedades" className="action-item">
                    <Icon name="arrow-left" size={14} />
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

export function PropiedadDetallePage() {
  const params = useParams();
  const [property, setProperty] = useState<PropertyDTO | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      try {
        const prop = await backend<PropertyDTO>(`/properties/${params.id}`);
        setProperty(prop);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Error cargando propiedad");
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [params.id]);

  if (loading) {
    return (
      <>
        <PageHeader title="Cargando..." description="Obteniendo datos de la propiedad" />
        <div className="card">
          <div className="card-body">
            <LoadingState rows={6} label="Cargando propiedad…" variant="blocks" />
          </div>
        </div>
      </>
    );
  }

  if (!property) {
    return (
      <>
        <PageHeader title="Error" />
        <ErrorBanner message={error || "Propiedad no encontrada"} />
      </>
    );
  }

  return (
    <>
      <PageHeader
        title={property.title}
        description={`${property.code} · ${property.property_type} · ${property.operation === "SALE" ? "Venta" : "Arriendo"} · ${property.city}`}
      />
      <PropertyDetailView property={property} error={error} />
    </>
  );
}