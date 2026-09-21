"use client";

interface DeleteButtonProps {
  name: string;
  href: string;
  ariaLabel: string;
}

export function DeleteButton({ name, href, ariaLabel }: DeleteButtonProps) {
  return (
    <button
      type="button"
      className="btn btn-ghost btn-danger-ghost btn-sm"
      onClick={() => {
        if (confirm(`¿Eliminar el proyecto "${name}"? Esta acción no se puede deshacer.`)) {
          window.location.href = href;
        }
      }}
      aria-label={ariaLabel}
    >
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <polyline points="3 6 5 6 21 6"></polyline>
        <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
      </svg>
    </button>
  );
}