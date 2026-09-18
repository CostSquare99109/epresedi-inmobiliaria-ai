"use client";

import { useEffect, useId, useRef } from "react";
import { Icon } from "./icons";

interface ConfirmDialogProps {
  open: boolean;
  title: string;
  description: string;
  confirmLabel?: string;
  cancelLabel?: string;
  danger?: boolean;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

/**
 * Diálogo de confirmación accesible: focus inicial en la acción segura,
 * Escape para cerrar, aria-describedby y restauración del focus.
 */
export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel = "Confirmar",
  cancelLabel = "Cancelar",
  danger = false,
  busy = false,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const confirmRef = useRef<HTMLButtonElement>(null);
  const restoreRef = useRef<HTMLElement | null>(null);
  const descId = useId();

  useEffect(() => {
    if (!open) return;
    restoreRef.current = document.activeElement as HTMLElement | null;
    (danger ? cancelRef : confirmRef).current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !busy) {
        onCancel();
        return;
      }
      // Focus trap: Tab cíclico entre los botones del diálogo (sin foco fuera).
      if (e.key === "Tab" && dialogRef.current) {
        const focusables = Array.from(
          dialogRef.current.querySelectorAll<HTMLElement>(
            "button:not([disabled])",
          ),
        );
        if (focusables.length === 0) return;
        const first = focusables[0];
        const last = focusables[focusables.length - 1];
        const active = document.activeElement;
        const inside = dialogRef.current.contains(active);
        if (e.shiftKey && (active === first || !inside)) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && active === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      restoreRef.current?.focus?.();
    };
  }, [open, busy, onCancel, danger]);

  if (!open) return null;

  return (
    <div
      className="dialog-overlay"
      onClick={() => {
        if (!busy) onCancel();
      }}
    >
      <div
        ref={dialogRef}
        className="dialog"
        role="alertdialog"
        aria-modal="true"
        aria-label={title}
        aria-describedby={descId}
        tabIndex={-1}
        onClick={(e) => e.stopPropagation()}
      >
        <p className="dialog-title">{title}</p>
        <p className="dialog-desc" id={descId}>
          {description}
        </p>
        <div className="dialog-actions">
          <button
            type="button"
            ref={cancelRef}
            className="btn btn-secondary"
            onClick={onCancel}
            disabled={busy}
          >
            {cancelLabel}
          </button>
          <button
            type="button"
            ref={confirmRef}
            className={`btn ${danger ? "btn-danger" : "btn-primary"}`}
            onClick={onConfirm}
            disabled={busy}
          >
            {busy ? "Procesando…" : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
