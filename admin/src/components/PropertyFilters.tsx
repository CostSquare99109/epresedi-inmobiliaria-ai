"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Icon } from "./icons";
import { buildHref } from "@/lib/params";
import { PROPERTY_TYPES } from "@/lib/property-constants";
import { statusMeta } from "@/lib/status";

interface PropertyFiltersProps {
  initialFilters: {
    estado: string;
    ciudad: string;
    tipo: string;
    operacion: string;
    precioMin: string;
    precioMax: string;
    areaMin: string;
    areaMax: string;
    habitaciones: string;
    proyecto: string;
    q: string;
    vista: string;
  };
  baseParams: Record<string, string | undefined>;
  hasActiveFilters: boolean;
  STATUSES: string[];
}

export function PropertyFilters({
  initialFilters,
  baseParams,
  hasActiveFilters,
  STATUSES,
}: PropertyFiltersProps) {
  const router = useRouter();
  const searchParams = useSearchParams();

  function navigateWithParams(overrides: Record<string, string | undefined>) {
    const currentParams: Record<string, string | undefined> = {};
    for (const [key, value] of searchParams.entries()) {
      currentParams[key] = value;
    }
    const href = buildHref("/propiedades", currentParams, overrides);
    router.push(href);
  }

  return (
    <div className="toolbar-filters">
      <div className="filter-tabs" role="navigation" aria-label="Filtrar por estado">
        {[
          { value: "", label: "Todos" },
          ...STATUSES.map((s) => ({ value: s, label: statusMeta(s).label })),
        ].map((opt) => {
          const active = initialFilters.estado === opt.value;
          const href = buildHref("/propiedades", baseParams, {
            estado: opt.value || undefined,
            pagina: undefined,
          });
          return (
            <a
              key={opt.value || "__all"}
              href={href}
              className={`filter-tab${active ? " active" : ""}`}
              aria-current={active ? "true" : undefined}
            >
              {opt.label}
            </a>
          );
        })}
      </div>

      <select
        name="tipo"
        value={initialFilters.tipo}
        onChange={(e) => navigateWithParams({ tipo: e.target.value || undefined })}
        aria-label="Filtrar por tipo"
        className="inline-select"
      >
        <option value="">Todos los tipos</option>
        {PROPERTY_TYPES.map((t) => (
          <option key={t} value={t}>
            {t.charAt(0).toUpperCase() + t.slice(1)}
          </option>
        ))}
      </select>

      <select
        name="operacion"
        value={initialFilters.operacion}
        onChange={(e) => navigateWithParams({ operacion: e.target.value || undefined })}
        aria-label="Filtrar por operación"
        className="inline-select"
      >
        <option value="">Todas las operaciones</option>
        <option value="SALE">Venta</option>
        <option value="RENT">Arriendo</option>
      </select>

      <form method="get" action="/propiedades" role="search" className="search-form">
        <span className="search-field">
          <Icon name="search" size={14} />
          <input
            type="search"
            name="q"
            defaultValue={initialFilters.q}
            placeholder="Buscar por título, descripción, ciudad, barrio, código…"
            aria-label="Búsqueda general"
          />
        </span>
        {Object.entries(baseParams)
          .filter(([key, value]) => value && key !== "q")
          .map(([key, value]) => (
            <input key={key} type="hidden" name={key} value={value} />
          ))}
        <button type="submit" className="btn btn-secondary">
          Buscar
        </button>
      </form>

      <details className="advanced-filters" aria-label="Filtros avanzados">
        <summary>
          <Icon name="sliders" size={16} />
          Filtros avanzados
        </summary>
        <div className="advanced-filters-grid">
          <div className="filter-group">
            <label htmlFor="precio_min">Precio mín.</label>
            <input
              type="number"
              id="precio_min"
              name="precio_min"
              step="1000000"
              min="0"
              defaultValue={initialFilters.precioMin}
              placeholder="Ej: 100000000"
              onChange={(e) => navigateWithParams({ precio_min: e.target.value || undefined })}
            />
          </div>
          <div className="filter-group">
            <label htmlFor="precio_max">Precio máx.</label>
            <input
              type="number"
              id="precio_max"
              name="precio_max"
              step="1000000"
              min="0"
              defaultValue={initialFilters.precioMax}
              placeholder="Ej: 500000000"
              onChange={(e) => navigateWithParams({ precio_max: e.target.value || undefined })}
            />
          </div>
          <div className="filter-group">
            <label htmlFor="area_min">Área mín. (m²)</label>
            <input
              type="number"
              id="area_min"
              name="area_min"
              step="1"
              min="0"
              defaultValue={initialFilters.areaMin}
              placeholder="Ej: 50"
              onChange={(e) => navigateWithParams({ area_min: e.target.value || undefined })}
            />
          </div>
          <div className="filter-group">
            <label htmlFor="area_max">Área máx. (m²)</label>
            <input
              type="number"
              id="area_max"
              name="area_max"
              step="1"
              min="0"
              defaultValue={initialFilters.areaMax}
              placeholder="Ej: 300"
              onChange={(e) => navigateWithParams({ area_max: e.target.value || undefined })}
            />
          </div>
          <div className="filter-group">
            <label htmlFor="habitaciones">Habitaciones mín.</label>
            <select
              id="habitaciones"
              name="habitaciones"
              defaultValue={initialFilters.habitaciones}
              onChange={(e) => navigateWithParams({ habitaciones: e.target.value || undefined })}
            >
              <option value="">Cualquiera</option>
              <option value="1">1+</option>
              <option value="2">2+</option>
              <option value="3">3+</option>
              <option value="4">4+</option>
              <option value="5">5+</option>
            </select>
          </div>
        </div>
      </details>

      <div className="toolbar-view">
        <div className="view-switcher" role="group" aria-label="Cambiar vista">
          <button
            type="button"
            className={`view-btn${initialFilters.vista === "tarjetas" ? " active" : ""}`}
            onClick={() => navigateWithParams({ vista: "tarjetas" })}
            aria-pressed={initialFilters.vista === "tarjetas"}
            aria-label="Vista de tarjetas"
          >
            <Icon name="dashboard" size={16} aria-hidden="true" />
            <span>Tarjetas</span>
          </button>
          <button
            type="button"
            className={`view-btn${initialFilters.vista === "tabla" ? " active" : ""}`}
            onClick={() => navigateWithParams({ vista: "tabla" })}
            aria-pressed={initialFilters.vista === "tabla"}
            aria-label="Vista de tabla"
          >
            <Icon name="list" size={16} aria-hidden="true" />
            <span>Tabla</span>
          </button>
        </div>
      </div>
    </div>
  );
}