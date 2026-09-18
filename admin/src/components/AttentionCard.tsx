import Link from "next/link";
import { Icon } from "./icons";

export interface AttentionItem {
  tone: "danger" | "warn";
  label: string;
  href: string;
  detail?: string;
  count?: number;
}

/**
 * Tira de pendientes derivados 100% de datos reales del backend.
 * Solo se renderiza cuando hay algo que atender.
 */
export function AttentionCard({ items }: { items: AttentionItem[] }) {
  if (items.length === 0) return null;
  const danger = items.some((i) => i.tone === "danger");
  return (
    <section
      className={`attention${danger ? " danger" : ""}`}
      aria-label="Pendientes que requieren atención"
    >
      <div className="attention-head">
        <Icon name="alert" size={13} />
        Requiere atención
      </div>
      <ul className="attention-list">
        {items.map((it) => (
          <li className="attention-item" key={`${it.href}:${it.label}`}>
            <span className={`dot dot-${it.tone}`} aria-hidden="true" />
            <span>
              <Link href={it.href}>{it.label}</Link>
              {it.detail && <span className="muted"> — {it.detail}</span>}
            </span>
            {typeof it.count === "number" && (
              <span className="att-count" aria-label={`${it.count} en total`}>
                {it.count}
              </span>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
