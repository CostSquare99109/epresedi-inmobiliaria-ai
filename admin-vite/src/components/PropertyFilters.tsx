"use client";

import { useState } from "react";
import { useNavigate, useSearchParams, Link } from "react-router-dom";
import { Icon } from "@/components/icons";
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
    q: string;
  };
  baseParams: Record<string, string | undefined>;
  hasActiveFilters: boolean;
  STATUSES: string[];
  statusCounts?: Record<string, number> | null;
}

export function PropertyFilters({
  initialFilters,
  baseParams,
  STATUSES,
  statusCounts,
}: PropertyFiltersProps) {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [showAdvancedFilters, setShowAdvancedFilters] = useState(false);

  function navigateWithParams(overrides: Record<string, string | undefined>) {
    const currentParams: Record<string, string | undefined> = {};
    for (const [key, value] of searchParams.entries()) {
      currentParams[key] = value;
    }
    const href = buildHref("/propiedades", currentParams, overrides);
    navigate(href);
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
            <Link
              key={opt.value || "__all"}
              to={href}
              className={`filter-tab${active ? " active" : ""}`}
              aria-current={active ? "true" : undefined}
            >
              {opt.label}
              {statusCounts && typeof statusCounts[opt.value] === "number" && (
                <span className="count">{statusCounts[opt.value]}</span>
              )}
            </Link>
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

      <form method="get" action="/propiedades" role="search" className="search-form search-bar">
        <span className="search-field">
          <Icon name="search" size={14} />
          <input
            type="search"
            name="q"
            defaultValue={initialFilters.q}
            placeholder="Buscar propiedades…"
            aria-label="Búsqueda general"
            className="search-input"
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

      <div
        className={`advanced-filters${showAdvancedFilters ? " open" : ""}`}
        aria-label="Filtros avanzados"
        style={{ display: showAdvancedFilters ? "block" : "none" }}
      >
        <div className="advanced-filters-header">
          <button
            type="button"
            className="advanced-filters-toggle"
            onClick={() => setShowAdvancedFilters(!showAdvancedFilters)}
            aria-expanded={showAdvancedFilters}
            aria-controls="advanced-filters-content"
          >
            <Icon name="sliders" size={16} />
            Filtros avanzados
          </button>
          {showAdvancedFilters && (
            <button
              type="button"
              className="advanced-filters-close"
              onClick={() => setShowAdvancedFilters(false)}
              aria-label="Cerrar filtros avanzados"
            >
              <Icon name="x" size={16} />
            </button>
          )}
        </div>
        <div
          id="advanced-filters-content"
          className="advanced-filters-grid"
          role="region"
          aria-label="Contenido de filtros avanzados"
        >
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
      </div>
    </div>
  );
}