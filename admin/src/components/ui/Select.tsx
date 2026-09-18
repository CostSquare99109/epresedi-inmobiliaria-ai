"use client";

import { SelectHTMLAttributes, forwardRef } from "react";

interface SelectOption {
  value: string;
  label: string;
}

interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement> {
  label: string;
  options: SelectOption[];
  error?: string;
  hint?: string;
}

export const Select = forwardRef<HTMLSelectElement, SelectProps>(
  ({ label, options, error, hint, className = "", id, ...props }, ref) => {
    const selectId = id || label.toLowerCase().replace(/\s+/g, "-");
    const errorId = `${selectId}-error`;
    const hintId = `${selectId}-hint`;
    
    return (
      <div className={`form-field ${error ? "has-error" : ""} ${className}`}>
        <label htmlFor={selectId} className="form-label">
          {label}
        </label>
        <select
          ref={ref}
          id={selectId}
          className="form-select"
          aria-invalid={error ? "true" : "false"}
          aria-describedby={`${error ? errorId : ""} ${hint ? hintId : ""}`.trim() || undefined}
          {...props}
        >
          {props.required ? null : <option value="">Seleccionar...</option>}
          {options.map(opt => (
            <option key={opt.value} value={opt.value}>{opt.label}</option>
          ))}
        </select>
        {error && <p id={errorId} className="form-error" role="alert">{error}</p>}
        {hint && !error && <p id={hintId} className="form-hint">{hint}</p>}
      </div>
    );
  }
);

Select.displayName = "Select";