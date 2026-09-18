"use client";

import { TextareaHTMLAttributes, forwardRef } from "react";

interface TextareaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  label: string;
  error?: string;
  hint?: string;
}

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(
  ({ label, error, hint, className = "", id, ...props }, ref) => {
    const textareaId = id || label.toLowerCase().replace(/\s+/g, "-");
    const errorId = `${textareaId}-error`;
    const hintId = `${textareaId}-hint`;
    
    return (
      <div className={`form-field ${error ? "has-error" : ""} ${className}`}>
        <label htmlFor={textareaId} className="form-label">
          {label}
        </label>
        <textarea
          ref={ref}
          id={textareaId}
          className="form-textarea"
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

Textarea.displayName = "Textarea";