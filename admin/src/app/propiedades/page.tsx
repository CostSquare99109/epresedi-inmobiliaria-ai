import Link from "next/link";
import type { Metadata } from "next";
import { backend, type PropertyDTO } from "@/lib/backend";
import { PageHeader } from "@/components/PageHeader";
import { EmptyState } from "@/components/EmptyState";
import { ErrorBanner } from "@/components/ErrorBanner";
import { RefreshButton } from "@/components/RefreshButton";
import { FilterTabs, Pagination } from "@/components/TableControls";
import { PropertyThumb } from "@/components/PropertyThumb";
import { PropertyStatusControl } from "@/components/PropertyStatusControl";
import { StatusBadge } from "@/components/StatusBadge";
import { Icon } from "@/components/icons";
import { operationLabel, statusMeta } from "@/lib/status";
import { formatMoney } from "@/lib/format";
import { singleParam } from "@/lib/params";

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
  const estado = singleParam(sp.estado);
  const ciudad = singleParam(sp.ciudad).trim();
  const pagina = Math.max(1, parseInt(singleParam(sp.pagina) || "1", 10) || 1);
  const params: Record<string, string | undefined> = {
    estado: estado || undefined,
    ciudad: ciudad || undefined,
  };

  const q = new URLSearchParams({
    limit: String(PAGE_SIZE),
    offset: String((pagina - 1) * PAGE_SIZE),
  });
  if (estado) q.set("status", estado);
  if (ciudad) q.set("city", ciudad);

  let data: { properties: PropertyDTO[] } | null = null;
  let error = "";
  try {
    data = await backend<{ properties: PropertyDTO[] }>(`/properties?${q.toString()}`);
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }
  const props = data?.properties ?? [];

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

  return (
    <>
      <PageHeader
        title="Propiedades"
        description="Inventario de inmuebles: filtra por estado o ciudad, recorre el listado y actualiza la disponibilidad comercial."
        actions={<RefreshButton label="Recargar" />}
      />

      <section className="card" aria-label="Listado de propiedades">
        <div className="card-head">
          <div className="toolbar">
            <div className="toolbar-filters">
              <FilterTabs
                basePath="/propiedades"
                params={params}
                paramName="estado"
                current={estado}
                options={[
                  { value: "", label: "Todos" },
                  ...STATUSES.map((s) => ({ value: s, label: statusMeta(s).label })),
                ]}
                ariaLabel="Filtrar por estado"
              />
              <form method="get" action="/propiedades" role="search" className="search-form">
                <span className="search-field">
                  <Icon name="search" size={14} />
                  <input
                    type="search"
                    name="ciudad"
                    defaultValue={ciudad}
                    placeholder="Filtrar por ciudad…"
                    aria-label="Filtrar por ciudad"
                  />
                </span>
                {estado && <input type="hidden" name="estado" value={estado} />}
                <button type="submit" className="btn btn-secondary">
                  Buscar
                </button>
              </form>
            </div>
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
              estado || ciudad
                ? "Ninguna propiedad coincide con los filtros aplicados. Prueba con otro estado o ciudad."
                : "El inventario está vacío. Carga las propiedades desde la API de administración y aparecerán aquí automáticamente."
            }
            action={
              estado || ciudad ? (
                <Link href="/propiedades" className="btn btn-secondary">
                  Quitar filtros
                </Link>
              ) : undefined
            }
          />
        ) : (
          <>
            <div className="table-wrap">
              <table>
                <caption className="visually-hidden">
                  Listado de propiedades con foto, ubicación, precio y estado comercial
                </caption>
                <thead>
                  <tr>
                    <th>
                      <span className="visually-hidden">Foto</span>
                    </th>
                    <th>Inmueble</th>
                    <th>Tipo</th>
                    <th className="num">Precio</th>
                    <th className="num">Área</th>
                    <th className="num">Hab.</th>
                    <th>Estado</th>
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
                        <div className="cell-main">{p.title}</div>
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
                      <td>
                        <div className="status-cell">
                          <StatusBadge status={p.status} />
                          <PropertyStatusControl id={p.id} code={p.code} status={p.status} />
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pagination
              basePath="/propiedades"
              params={params}
              page={pagina}
              hasMore={props.length === PAGE_SIZE}
              shown={props.length}
              itemName="propiedades"
            />
          </>
        )}
      </section>
    </>
  );
}
