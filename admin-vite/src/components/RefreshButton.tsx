"use client";

import { Icon } from "./icons";
import { Button } from "./ui/Button";

interface RefreshButtonProps {
  label?: string;
  onClick?: () => void;
}

export function RefreshButton({ label = "Recargar", onClick }: RefreshButtonProps) {
  return (
    <Button
      type="button"
      variant="ghost"
      onClick={onClick ?? (() => window.location.reload())}
      icon={<Icon name="refresh" size={14} />}
      iconPosition="left"
      title={label}
    >
      {label}
    </Button>
  );
}