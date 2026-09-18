"use client";

import { useEffect } from "react";
import { Icon } from "./icons";

export interface Feedback {
  tone: "ok" | "error";
  message: string;
}

/** Toast de feedback para operaciones realizadas desde el cliente. */
export function ActionToast({
  feedback,
  onClose,
}: {
  feedback: Feedback | null;
  onClose: () => void;
}) {
  useEffect(() => {
    if (!feedback) return;
    const t = setTimeout(onClose, 6000);
    return () => clearTimeout(t);
  }, [feedback, onClose]);

  if (!feedback) return null;
  const error = feedback.tone === "error";
  return (
    <div
      className={`action-toast${error ? " error" : ""}`}
      role={error ? "alert" : "status"}
    >
      <Icon name={error ? "alert" : "check"} size={15} />
      <span>{feedback.message}</span>
      <button
        type="button"
        className="toast-close"
        onClick={onClose}
        aria-label="Cerrar aviso"
      >
        <Icon name="x" size={14} />
      </button>
    </div>
  );
}
