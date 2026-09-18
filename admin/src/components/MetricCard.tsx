import Link from "next/link";
import { Icon } from "./icons";

interface MetricCardProps {
  label: string;
  value: number | string;
  href?: string;
  hint?: string;
  tone?: "success" | "warn" | "danger" | "neutral";
}

/** Métrica principal de la página. Link opcional → acción de profundización. */
export function MetricCard({ label, value, href, hint, tone }: MetricCardProps) {
  const cls = `stat-card${tone ? ` tone-${tone}` : ""}`;
  const inner = (
    <>
      <div className="stat-v">{value}</div>
      <div className="stat-l">{label}</div>
      {hint && href && (
        <span className="stat-hint">
          {hint}
          <Icon name="chevron-right" size={12} />
        </span>
      )}
    </>
  );
  if (href) {
    return (
      <Link href={href} className={cls} aria-label={`${label}: ${value}`}>
        {inner}
      </Link>
    );
  }
  return <div className={cls}>{inner}</div>;
}
