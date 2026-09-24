
import { ButtonHTMLAttributes, forwardRef } from "react";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "primary" | "secondary" | "ghost" | "danger";
  size?: "sm" | "md" | "lg";
  loading?: boolean;
  icon?: React.ReactNode;
  iconPosition?: "left" | "right";
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ variant = "primary", size = "md", loading = false, icon, iconPosition = "right", children, disabled, className = "", ...props }, ref) => {
    const baseClasses = "btn";
    const variantClasses = `btn-${variant}`;
    const sizeClasses = `btn-${size}`;
    const loadingClasses = loading ? "btn-loading" : "";
    
    return (
      <button
        ref={ref}
        className={`${baseClasses} ${variantClasses} ${sizeClasses} ${loadingClasses} ${className}`}
        disabled={disabled || loading}
        {...props}
      >
        {loading && <span className="btn-spinner" aria-hidden="true" />}
        {!loading && iconPosition === "left" && icon && <span className="btn-icon-left">{icon}</span>}
        <span className="btn-text">{children}</span>
        {!loading && iconPosition === "right" && icon && <span className="btn-icon-right">{icon}</span>}
      </button>
    );
  }
);

Button.displayName = "Button";