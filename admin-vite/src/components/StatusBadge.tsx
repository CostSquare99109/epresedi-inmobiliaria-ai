import { statusMeta } from "../lib/status";

interface StatusBadgeProps {
  status: string;
  className?: string;
}

export function StatusBadge({ status, className = "" }: StatusBadgeProps) {
  const meta = statusMeta(status);
  return (
    <span className={`badge tone-${meta.tone} ${className}`}>
      <span className="badge-dot" />
      {meta.label}
    </span>
  );
}