import Link from "next/link";
import { Icon } from "./icons";
import { buildHref } from "@/lib/params";

export interface FilterOption {
  /** "" = todos */
  value: string;
  label: string;
  count?: number;
}

/**
 * Navegación por filtros con deep links (Server Component, cero JS):
 * cada tab es un Link que preserva el resto de params y reinicia la página.
 */
export function FilterTabs({
  basePath,
  params,
  paramName,
  current,
  options,
  ariaLabel,
}: {
  basePath: string;
  params: Record<string, string | undefined>;
  paramName: string;
  current: string;
  options: FilterOption[];
  ariaLabel: string;
}) {
  return (
    <div className="filter-tabs" role="navigation" aria-label={ariaLabel}>
      {options.map((opt) => {
        const active = current === opt.value;
        const href = buildHref(basePath, params, {
          [paramName]: opt.value || undefined,
          pagina: undefined,
        });
        return (
          <Link
            key={opt.value || "__all"}
            href={href}
            className={`filter-tab${active ? " active" : ""}`}
            aria-current={active ? "true" : undefined}
          >
            {opt.label}
            {typeof opt.count === "number" && (
              <span className="count">{opt.count}</span>
            )}
          </Link>
        );
      })}
    </div>
  );
}

/**
 * Paginación real sobre la paginación del backend (offset/limit).
 * Solo muestra «Siguiente» cuando la página actual vino llena.
 */
export function Pagination({
  basePath,
  params,
  page,
  hasMore,
  shown,
  itemName = "resultados",
}: {
  basePath: string;
  params: Record<string, string | undefined>;
  page: number;
  hasMore: boolean;
  shown: number;
  itemName?: string;
}) {
  return (
    <div className="pagination">
      <span className="page-info">
        {shown === 0
          ? `Sin ${itemName} en esta página`
          : `Página ${page} · ${shown} ${itemName}`}
        {hasMore ? " (hay más)" : ""}
      </span>
      <div className="page-btns">
        {page > 1 ? (
          <Link
            className="page-btn"
            href={buildHref(basePath, params, { pagina: page - 1 })}
            rel="prev"
          >
            <Icon name="chevron-left" size={13} />
            Anterior
          </Link>
        ) : (
          <span className="page-btn disabled" aria-disabled="true">
            <Icon name="chevron-left" size={13} />
            Anterior
          </span>
        )}
        {hasMore ? (
          <Link
            className="page-btn"
            href={buildHref(basePath, params, { pagina: page + 1 })}
            rel="next"
          >
            Siguiente
            <Icon name="chevron-right" size={13} />
          </Link>
        ) : (
          <span className="page-btn disabled" aria-disabled="true">
            Siguiente
            <Icon name="chevron-right" size={13} />
          </span>
        )}
      </div>
    </div>
  );
}
