"use client";

import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { backend, PROXY, type PropertyDTO } from "../../api/client";
import { PageHeader } from "../../components/PageHeader";
import { EmptyState } from "../../components/EmptyState";
import { ErrorBanner } from "../../components/ErrorBanner";
import { RefreshButton } from "../../components/RefreshButton";
import { Pagination } from "../../components/TableControls";
import { StatusBadge } from "../../components/StatusBadge";
import { PropertyFilters } from "../../components/PropertyFilters";
import { Icon } from "../../components/icons";
import { operationLabel } from "../../lib/status";
import { formatMoney } from "../../lib/format";
import { formatFloorsDisplay } from "../../lib/floors";
import { singleParam } from "../../lib/params";

const PAGE_SIZE = 12;
const STATUSES = ["AVAILABLE", "RESERVED", "SOLD", "INACTIVE"];

export function PropiedadesPage() {
  const [searchParams] = useSearchParams();
  const sp: Record<string, string | undefined> = Object.fromEntries(searchParams.entries());
  
  const estado = singleParam(sp.estado);
  const ciudad = singleParam(sp.ciudad).trim();
  const tipo = singleParam(sp.tipo);
  const operacion = singleParam(sp.operacion);
  const precioMin = singleParam(sp.precio_min);
  const precioMax = singleParam(sp.precio_max);
  const areaMin = singleParam(sp.area_min);
  const areaMax = singleParam(sp.area_max);
  const habitaciones = singleParam(sp.habitaciones);
  const q = singleParam(sp.q)?.trim();
  const pagina = Math.max(1, parseInt(singleParam(sp.pagina) || "1", 10) || 1);

  const baseParams: Record<string, string | undefined> = {
    estado: estado || undefined,
    ciudad: ciudad || undefined,
    tipo: tipo || undefined,
    operacion: operacion || undefined,
    precio_min: precioMin || undefined,
    precio_max: precioMax || undefined,
    area_min: areaMin || undefined,
    area_max: areaMax || undefined,
    habitaciones: habitaciones || undefined,
    q: q || undefined,
  };

  const queryParams = new URLSearchParams({
    limit: String(PAGE_SIZE),
    offset: String((pagina - 1) * PAGE_SIZE),
  });

  if (estado) queryParams.set("status", estado);
  if (ciudad) queryParams.set("city", ciudad);
  if (tipo) queryParams.set("property_type", tipo);
  if (operacion) queryParams.set("operation", operacion);
  if (precioMin) queryParams.set("min_price", precioMin);
  if (precioMax) queryParams.set("max_price", precioMax);
  if (q) queryParams.set("q", q);

  const [data, setData] = useState<{ properties: PropertyDTO[]; total: number } | null>(null);
  const [error, setError] = useState("");
  const [covers, setCovers] = useState<(string | null)[]>([]);
  const [statusCounts, setStatusCounts] = useState<Record<string, number> | null>(null);
  const [, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      setLoading(true);
      setError("");
      try {
        const result = await backend<{ properties: PropertyDTO[]; total: number }>(
          `/properties/admin?${queryParams.toString()}`
        );
        setData(result);

        // Load covers
        const coversResult = await Promise.all(
          result.properties.map(async (p) => {
            try {
              const r = await backend<{ images: string[] }>(`/properties/${p.id}/images`);
              return r.images[0] ?? null;
            } catch {
              return null;
            }
          })
        );
        setCovers(coversResult);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [queryParams.toString()]);

  // Contadores por estado para los chips (respetan los demás filtros activos)
  const countKey = [ciudad, tipo, operacion, precioMin, precioMax, areaMin, areaMax, habitaciones, q].join("|");
  useEffect(() => {
    async function loadCounts() {
      const base = new URLSearchParams({ limit: "1", offset: "0" });
      if (ciudad) base.set("city", ciudad);
      if (tipo) base.set("property_type", tipo);
      if (operacion) base.set("operation", operacion);
      if (precioMin) base.set("min_price", precioMin);
      if (precioMax) base.set("max_price", precioMax);
      if (q) base.set("q", q);
      try {
        const entries = await Promise.all(
          ["", ...STATUSES].map(async (s) => {
            const qp = new URLSearchParams(base);
            if (s) qp.set("status", s);
            const r = await backend<{ total: number }>(`/properties/admin?${qp.toString()}`);
            return [s, r.total] as const;
          })
        );
        setStatusCounts(Object.fromEntries(entries));
      } catch {
        setStatusCounts(null);
      }
    }
    loadCounts();
  }, [countKey]);

  let props = data?.properties ?? [];

  // Client-side filters not supported by the backend yet
  if (areaMin) {
    const min = parseFloat(areaMin);
    if (!isNaN(min)) props = props.filter(p => p.area_m2 !== null && p.area_m2 >= min);
  }
  if (areaMax) {
    const max = parseFloat(areaMax);
    if (!isNaN(max)) props = props.filter(p => p.area_m2 !== null && p.area_m2 <= max);
  }
  if (habitaciones) {
    const hab = parseInt(habitaciones, 10);
    if (!isNaN(hab)) props = props.filter(p => p.bedrooms !== null && p.bedrooms >= hab);
  }

  const total = data?.total ?? 0;
  const hasMore = pagina * PAGE_SIZE < total;

  const hasActiveFilters = Boolean(estado || ciudad || tipo || operacion || precioMin || precioMax ||
    areaMin || areaMax || habitaciones || q);

  const initialFilters = {
    estado,
    ciudad,
    tipo,
    operacion,
    precioMin,
    precioMax,
    areaMin,
    areaMax,
    habitaciones,
    q,
  };

  return (
    <>
      <PageHeader
        title="Propiedades"
        description="Inventario de inmuebles: filtra, busca y gestiona tus propiedades."
        actions={
          <>
            <Link to="/propiedades/nueva" className="btn btn-primary">
              <Icon name="plus" size={16} />
              Nueva propiedad
            </Link>
            <RefreshButton label="Recargar" />
          </>
        }
      />

      <section className="card" aria-label="Listado de propiedades">
        <div className="card-head">
          <div className="toolbar">
            <PropertyFilters
              initialFilters={initialFilters}
              baseParams={baseParams}
              hasActiveFilters={hasActiveFilters}
              STATUSES={STATUSES}
              statusCounts={statusCounts}
            />
            <span className="toolbar-meta">{total === 1 ? "1 propiedad" : `${total} propiedades`}</span>
          </div>
        </div>

        {error ? (
          <div className="card-body">
            <ErrorBanner message={error} />
          </div>
        ) : props.length === 0 ? (
          <EmptyState
            icon="building"
            title="Sin propiedades"
            description={
              hasActiveFilters
                ? "Sin resultados para estos filtros. Ajusta los criterios o límpialos."
                : "Aún no hay propiedades en el inventario."
            }
            action={
              hasActiveFilters ? (
                <Link to="/propiedades" className="btn btn-secondary">
                  Limpiar filtros
                </Link>
              ) : (
                <Link to="/propiedades/nueva" className="btn btn-primary">
                  <Icon name="plus" size={14} />
                  Nueva propiedad
                </Link>
              )
            }
          />
        ) : (
          <>
            <div className="cards-grid" role="list" aria-label="Propiedades">
              {props.map((p, i) => (
                <article key={p.id} className="property-card" role="listitem">
                  <div className="card-image">
                    {covers[i] ? (
                      <img
                        src={`${PROXY}/properties/${p.id}/images/${covers[i]}`}
                        alt={`Foto de ${p.title}`}
                        loading="lazy"
                        decoding="async"
                      />
                    ) : (
                      <span className="card-image-fallback">
                        <Icon name="building" size={22} />
                      </span>
                    )}
                    <div className="card-status-overlay">
                      <StatusBadge status={p.status} />
                    </div>
                  </div>
                  <div className="card-content">
                    <h3 className="card-title" title={p.title}>{p.title}</h3>
                    <p className="card-code">
                      <span>{p.code}</span>
                      <span className="sep" aria-hidden="true">·</span>
                      <span>{p.city}{p.neighborhood ? `, ${p.neighborhood}` : ""}</span>
                    </p>
                    <p className="card-meta">
                      <span>{p.property_type}</span>
                      <span className="sep" aria-hidden="true">·</span>
                      <span>{operationLabel(p.operation)}</span>
                    </p>
                    <p className="card-price">{formatMoney(p.price, p.currency)}</p>
                    <div className="card-features">
                      {p.area_m2 && (
                        <span className="card-feature">
                          <Icon name="expand" size={12} aria-hidden="true" />
                          <span>{p.area_m2} m²</span>
                        </span>
                      )}
                      {p.bedrooms && (
                        <span className="card-feature">
                          <Icon name="bed" size={12} aria-hidden="true" />
                          <span>{p.bedrooms} hab</span>
                        </span>
                      )}
                      {p.bathrooms && (
                        <span className="card-feature">
                          <Icon name="bath" size={12} aria-hidden="true" />
                          <span>{p.bathrooms} baños</span>
                        </span>
                      )}
                      {p.parking_spaces && (
                        <span className="card-feature">
                          <Icon name="car" size={12} aria-hidden="true" />
                          <span>{p.parking_spaces} park.</span>
                        </span>
                      )}
                      {formatFloorsDisplay(p.floors, p.floor_offer_type, p.offered_floors, p.operation) && (
                        <span className="card-feature">
                          <Icon name="building" size={12} aria-hidden="true" />
                          <span>{formatFloorsDisplay(p.floors, p.floor_offer_type, p.offered_floors, p.operation)}</span>
                        </span>
                      )}
                    </div>
                    <div className="card-actions">
                      <Link to={`/propiedades/${p.id}`} className="btn btn-secondary btn-sm">
                        <Icon name="eye" size={14} aria-hidden="true" />
                        <span>Ver detalle</span>
                      </Link>
                      <Link to={`/propiedades/${p.id}/editar`} className="btn btn-primary btn-sm">
                        <Icon name="edit" size={14} aria-hidden="true" />
                        <span>Editar</span>
                      </Link>
                    </div>
                  </div>
                </article>
              ))}
            </div>
            <Pagination
              basePath="/propiedades"
              params={baseParams}
              page={pagina}
              hasMore={hasMore}
              shown={props.length}
              itemName="propiedades"
            />
          </>
        )}
      </section>
    </>
  );
}