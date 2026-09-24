import { Link } from "react-router-dom";
import { Icon } from "./icons";
import { buildHref } from "../lib/params";

export interface FilterOption {
  value: string;
  label: string;
  count?: number;
}

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
            to={href}
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
            to={buildHref(basePath, params, { pagina: page - 1 })}
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
            to={buildHref(basePath, params, { pagina: page + 1 })}
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