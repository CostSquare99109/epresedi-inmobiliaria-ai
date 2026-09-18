"use client";

import { useState, useTransition } from "react";
import { statusMeta } from "@/lib/status";
import { ConfirmDialog } from "./ConfirmDialog";
import { ActionToast, type Feedback } from "./ActionToast";
import { updatePropertyStatus } from "@/app/propiedades/actions";

const STATUSES = ["AVAILABLE", "RESERVED", "SOLD", "INACTIVE"];

/**
 * Control de estado comercial de una propiedad (isla de cliente).
 * Toda mutación pasa por Server Action + confirmación explícita.
 */
export function PropertyStatusControl({
  id,
  code,
  status,
}: {
  id: string;
  code: string;
  status: string;
}) {
  const [value, setValue] = useState(status);
  const [pending, start] = useTransition();
  const [confirming, setConfirming] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<Feedback | null>(null);

  function requestChange(next: string) {
    if (next === value || pending) return;
    setConfirming(next);
  }

  function confirm() {
    if (!confirming) return;
    const next = confirming;
    setConfirming(null);
    start(async () => {
      const res = await updatePropertyStatus(id, next);
      if (res.ok) {
        setValue(next);
        setFeedback({
          tone: "ok",
          message: `${code} actualizada a «${statusMeta(next).label}».`,
        });
      } else {
        setFeedback({
          tone: "error",
          message: `No se pudo actualizar ${code}: ${res.error}`,
        });
      }
    });
  }

  return (
    <>
      <select
        className="select-sm"
        value={value}
        disabled={pending}
        onChange={(e) => requestChange(e.target.value)}
        aria-label={`Cambiar estado de ${code}`}
      >
        {STATUSES.map((s) => (
          <option key={s} value={s}>
            {statusMeta(s).label}
          </option>
        ))}
      </select>
      <ConfirmDialog
        open={confirming !== null}
        title="¿Cambiar el estado de la propiedad?"
        description={
          confirming
            ? `«${code}» pasará de «${statusMeta(value).label}» a «${statusMeta(confirming).label}». Este cambio afecta la búsqueda pública del asistente.`
            : ""
        }
        confirmLabel="Cambiar estado"
        busy={pending}
        onConfirm={confirm}
        onCancel={() => setConfirming(null)}
      />
      <ActionToast feedback={feedback} onClose={() => setFeedback(null)} />
    </>
  );
}
