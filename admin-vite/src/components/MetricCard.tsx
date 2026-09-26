import { Link } from "react-router-dom";
import { Icon, type IconName } from "./icons";

interface MetricCardProps {
  title: string;
  value: string | number;
  hint?: string;
  tone?: "success" | "warn" | "danger" | "neutral";
  icon?: IconName;
  to?: string;
}

export function MetricCard({ title, value, hint, tone = "neutral", icon, to }: MetricCardProps) {
  const className = `stat-card tone-${tone}`;
  const content = (
    <>
      {icon && (
        <span className={`stat-icon tone-${tone}`} aria-hidden="true">
          <Icon name={icon} size={20} />
        </span>
      )}
      <span className="stat-text">
        <span className="stat-v">{value}</span>
        <span className="stat-l">{title}</span>
        {hint && <span className="stat-hint">{hint}</span>}
      </span>
    </>
  );
  if (to) {
    return (
      <Link className={className} to={to}>
        {content}
      </Link>
    );
  }
  return <div className={className}>{content}</div>;
}