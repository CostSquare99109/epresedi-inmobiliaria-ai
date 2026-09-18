import { statusMeta } from "@/lib/status";

export function StatusBadge({ status }: { status: string }) {
  const meta = statusMeta(status);
  return (
    <span className={`badge tone-${meta.tone}`}>
      <span className="badge-dot" aria-hidden="true" />
      {meta.label}
    </span>
  );
}
