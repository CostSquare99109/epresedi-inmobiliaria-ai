import { Link } from "react-router-dom";
import { Icon, type IconName } from "./icons";

interface MetricCardProps {
  title: string;
  value: string | number;
  hint?: string;
  tone?: "success" | "warn" | "danger" | "neutral";
  icon?: IconName;
  href?: string;
}

export function MetricCard({ title, value, hint, tone = "neutral", icon, href }: MetricCardProps) {
  const className = `stat-card tone-${tone}`;
  const content = (
    <>
      {icon && <Icon name={icon} size={18} />}
      <span className="stat-v">{value}</span>
      <span className="stat-l">{title}</span>
      {hint && <span className="stat-hint">{hint}</span>}
    </>
  );
  if (href) {
    return (
      <Link className={className} to={href}>
        {content}
      </Link>
    );
  }
  return <div className={className}>{content}</div>;
}