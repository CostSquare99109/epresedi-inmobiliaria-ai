interface LoadingStateProps {
  rows?: number;
  label?: string;
  /** rows: filas tipo tabla · blocks: bloques tipo tarjetas */
  variant?: "rows" | "blocks";
}

export function LoadingState({
  rows = 4,
  label = "Cargando información…",
  variant = "rows",
}: LoadingStateProps) {
  return (
    <div
      className="loading-block"
      role="status"
      aria-label={label}
    >
      {Array.from({ length: rows }, (_, i) => (
        <div
          className={`skeleton ${variant === "rows" ? "skeleton-row" : "skeleton-block"}`}
          key={i}
        />
      ))}
    </div>
  );
}
