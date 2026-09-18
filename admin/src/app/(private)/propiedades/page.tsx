import Link from "next/link";
import type { Metadata } from "next";
import { backend, type PropertyDTO } from "@/lib/backend";
import { PageHeader } from "@/components/PageHeader";
import { EmptyState } from "@/components/EmptyState";
import { ErrorBanner } from "@/components/ErrorBanner";
import { RefreshButton } from "@/components/RefreshButton";
import { Pagination } from "@/components/TableControls";
import { PropertyThumb } from "@/components/PropertyThumb";
import { PropertyStatusControl } from "@/components/PropertyStatusControl";
import { StatusBadge } from "@/components/StatusBadge";
import { PropertyFilters } from "@/components/PropertyFilters";
import { Icon } from "@/components/icons";
import { operationLabel } from "@/lib/status";
import { formatMoney } from "@/lib/format";
import { singleParam, buildHref } from "@/lib/params";
import { PROPERTY_TYPES } from "@/lib/property-constants";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Propiedades" };

/** Tamaño de página: consume la paginación real del backend (offset/limit). */
const PAGE_SIZE = 12;
const STATUSES = ["AVAILABLE", "RESERVED", "SOLD", "INACTIVE"];

interface PageProps {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

export default async function Propiedades({ searchParams }: PageProps) {
  const sp = await searchParams;
  
  // Filtros existentes
  const estado = singleParam(sp.estado);
  const ciudad = singleParam(sp.ciudad).trim();
  
  // Nuevos filtros
  const tipo = singleParam(sp.tipo);
  const operacion = singleParam(sp.operacion);
  const precioMin = singleParam(sp.precio_min);
  const precioMax = singleParam(sp.precio_max);
  const areaMin = singleParam(sp.area_min);
  const areaMax = singleParam(sp.area_max);
  const habitaciones = singleParam(sp.habitaciones);
  const proyecto = singleParam(sp.proyecto);
  const q = singleParam(sp.q)?.trim(); // búsqueda full-text
  
  const pagina = Math.max(1, parseInt(singleParam(sp.pagina) || "1", 10) || 1);
  const vista = singleParam(sp.vista) || "tabla"; // "tabla" | "tarjetas"
  
  // Parámetros base para mantener en enlaces
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
    proyecto: proyecto || undefined,
    q: q || undefined,
    vista: vista !== "tabla" ? vista : undefined,
  };

  const queryParams = new URLSearchParams({
    limit: String(PAGE_SIZE),
    offset: String((pagina - 1) * PAGE_SIZE),
  });
  
  // Mapear filtros a parámetros del backend
  if (estado) queryParams.set("status", estado);
  if (ciudad) queryParams.set("city", ciudad);
  // Nota: backend actual solo soporta status y city. 
  // Los filtros adicionales (tipo, operacion, precio, etc.) requieren extensión del backend.
  // Por ahora los usamos para filtrado en frontend.
  
  let data: { properties: PropertyDTO[] } | null = null;
  let error = "";
  try {
    data = await backend<{ properties: PropertyDTO[] }>(`/properties?${queryParams.toString()}`);
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }
  let props = data?.properties ?? [];

  // Filtrado en frontend para campos que el backend no soporta aún
  if (tipo) {
    props = props.filter(p => p.property_type === tipo);
  }
  if (operacion) {
    props = props.filter(p => p.operation === operacion);
  }
  if (precioMin) {
    const min = parseFloat(precioMin);
    if (!isNaN(min)) props = props.filter(p => p.price >= min);
  }
  if (precioMax) {
    const max = parseFloat(precioMax);
    if (!isNaN(max)) props = props.filter(p => p.price <= max);
  }
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
  if (proyecto) {
    props = props.filter(p => p.project === proyecto);
  }
  if (q) {
    const searchLower = q.toLowerCase();
    props = props.filter(p => 
      p.title.toLowerCase().includes(searchLower) ||
      p.description.toLowerCase().includes(searchLower) ||
      p.city.toLowerCase().includes(searchLower) ||
      p.neighborhood.toLowerCase().includes(searchLower) ||
      p.code.toLowerCase().includes(searchLower)
    );
  }

  // Portadas resueltas en servidor, solo para la página visible (≤ 12).
  const covers = await Promise.all(
    props.map(async (p) => {
      try {
        const r = await backend<{ images: string[] }>(`/properties/${p.id}/images`);
        return r.images[0] ?? null;
      } catch {
        return null;
      }
    }),
  );

const hasActiveFilters = Boolean(estado || ciudad || tipo || operacion || precioMin || precioMax ||
    areaMin || areaMax || habitaciones || proyecto || q);

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
    proyecto,
    q,
    vista,
  };

  return (
    <>
      <PageHeader
        title="Propiedades"
        description="Inventario de inmuebles: filtra, busca y gestiona tus propiedades."
        actions={
          <>
            <Link href="/propiedades/nueva" className="btn btn-primary">
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
            />
            <span className="toolbar-meta">{props.length} en esta página</span>
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
                ? "Ninguna propiedad coincide con los filtros aplicados. Prueba con otros criterios."
                : "El inventario está vacío. Crea tu primera propiedad para comenzar."
            }
            action={
              hasActiveFilters ? (
                <Link href="/propiedades" className="btn btn-secondary">
                  Limpiar filtros
                </Link>
              ) : (
                <Link href="/propiedades/nueva" className="btn btn-primary">
                  <Icon name="plus" size={14} />
                  Crear propiedad
                </Link>
              )
            }
          />
        ) : (
          <>
            {vista === "tarjetas" ? (
              <div className="cards-grid" role="list" aria-label="Propiedades en vista de tarjetas">
                {props.map((p, i) => (
                  <article key={p.id} className="property-card" role="listitem">
                    <div className="card-image">
                      <PropertyThumb
                        propertyId={p.id}
                        filename={covers[i]}
                        alt={`Foto de ${p.title}`}
                      />
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
                      </div>
                      <div className="card-actions">
                        <Link href={`/propiedades/${p.id}`} className="btn btn-secondary btn-sm">
                          <Icon name="eye" size={14} aria-hidden="true" />
                          <span>Ver detalle</span>
                        </Link>
                        <Link href={`/propiedades/${p.id}/editar`} className="btn btn-primary btn-sm">
                          <Icon name="edit" size={14} aria-hidden="true" />
                          <span>Editar</span>
                        </Link>
                      </div>
                    </div>
                  </article>
                ))}
              </div>
            ) : (
              <>
                <div className="table-wrap">
                  <table>
                    <caption className="visually-hidden">
                      Listado de propiedades con foto, ubicación, precio y estado comercial
                    </caption>
                    <thead>
                      <tr>
                        <th><span className="visually-hidden">Foto</span></th>
                        <th>Inmueble</th>
                        <th>Tipo</th>
                        <th className="num">Precio</th>
                        <th className="num">Área</th>
                        <th className="num">Hab.</th>
                        <th className="num">Baños</th>
                        <th>Estado</th>
                        <th className="actions-col"><span className="visually-hidden">Acciones</span></th>
                      </tr>
                    </thead>
                    <tbody>
                      {props.map((p, i) => (
                        <tr key={p.id}>
                          <td>
                            <PropertyThumb
                              propertyId={p.id}
                              filename={covers[i]}
                              alt={`Foto de ${p.title}`}
                            />
                          </td>
                          <td>
                            <div className="cell-main" title={p.title}>{p.title}</div>
                            <div className="cell-sub">
                              {p.code} · {p.city}
                              {p.neighborhood ? ` · ${p.neighborhood}` : ""}
                            </div>
                          </td>
                          <td>
                            <div className="cell-main">{p.property_type}</div>
                            <div className="cell-sub">{operationLabel(p.operation)}</div>
                          </td>
                          <td className="num">{formatMoney(p.price, p.currency)}</td>
                          <td className="num">{p.area_m2 ? `${p.area_m2} m²` : "—"}</td>
                          <td className="num">{p.bedrooms ?? "—"}</td>
                          <td className="num">{p.bathrooms ?? "—"}</td>
                          <td>
                            <div className="status-cell">
                              <StatusBadge status={p.status} />
                              <PropertyStatusControl id={p.id} code={p.code} status={p.status} />
                            </div>
                          </td>
                          <td className="actions-col">
                            <div className="table-actions">
                              <Link
                                href={`/propiedades/${p.id}`}
                                className="btn btn-secondary btn-sm"
                                aria-label={`Ver detalle de ${p.title}`}
                              >
                                <Icon name="eye" size={14} aria-hidden="true" />
                                <span className="visually-hidden">Ver</span>
                              </Link>
                              <Link
                                href={`/propiedades/${p.id}/editar`}
                                className="btn btn-primary btn-sm"
                                aria-label={`Editar ${p.title}`}
                              >
                                <Icon name="edit" size={14} aria-hidden="true" />
                                <span className="visually-hidden">Editar</span>
                              </Link>
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <Pagination
                  basePath="/propiedades"
                  params={baseParams}
                  page={pagina}
                  hasMore={props.length === PAGE_SIZE}
                  shown={props.length}
                  itemName="propiedades"
                />
              </>
            )}
          </>
        )}
      </section>
    </>
  );
}