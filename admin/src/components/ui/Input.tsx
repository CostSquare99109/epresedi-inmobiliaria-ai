"use client";

import { InputHTMLAttributes, forwardRef } from "react";

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string;
  error?: string;
  hint?: string;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ label, error, hint, className = "", id, ...props }, ref) => {
    const inputId = id || label.toLowerCase().replace(/\s+/g, "-");
    const errorId = `${inputId}-error`;
    const hintId = `${inputId}-hint`;
    
    return (
      <div className={`form-field ${error ? "has-error" : ""} ${className}`}>
        <label htmlFor={inputId} className="form-label">
          {label}
        </label>
        <input
          ref={ref}
          id={inputId}
          className="form-input"
          aria-invalid={error ? "true" : "false"}
          aria-describedby={`${error ? errorId : ""} ${hint ? hintId : ""}`.trim() || undefined}
          {...props}
        />
        {error && <p id={errorId} className="form-error" role="alert">{error}</p>}
        {hint && !error && <p id={hintId} className="form-hint">{hint}</p>}
      </div>
    );
  }
);

Input.displayName = "Input";