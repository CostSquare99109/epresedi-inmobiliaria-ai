import { Icon, type IconName } from "./icons";

interface EmptyStateProps {
  icon?: IconName;
  title: string;
  description: string;
  action?: React.ReactNode;
  bordered?: boolean;
}

export function EmptyState({
  icon = "check",
  title,
  description,
  action,
  bordered = false,
}: EmptyStateProps) {
  return (
    <div className={`empty${bordered ? " bordered" : ""}`}>
      <span className="empty-icon" aria-hidden="true">
        <Icon name={icon} size={26} />
      </span>
      <p className="empty-title">{title}</p>
      <p className="empty-desc">{description}</p>
      {action && <div className="empty-action">{action}</div>}
    </div>
  );
}