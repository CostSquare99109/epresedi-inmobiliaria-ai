import { Icon } from "./icons";

interface AttentionCardProps {
  title: string;
  items: { label: string; count: number; href?: string }[];
  tone?: "warn" | "danger";
}

export function AttentionCard({ title, items, tone = "warn" }: AttentionCardProps) {
  return (
    <div className={`attention${tone === "danger" ? " danger" : ""}`}>
      <div className="attention-head">
        <Icon name={tone === "danger" ? "alert" : "alert"} size={14} />
        <span>{title}</span>
      </div>
      <ul className="attention-list">
        {items.map((item, i) => (
          <li key={i} className="attention-item">
            <span className="dot" style={{ background: tone === "danger" ? "var(--danger)" : "var(--warn)" }} />
            {item.href ? (
              <a href={item.href}>{item.label}</a>
            ) : (
              <span>{item.label}</span>
            )}
            <span className="att-count">{item.count}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}