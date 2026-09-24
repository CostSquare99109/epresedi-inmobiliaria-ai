/** Metadatos de estado: etiqueta en español + tono visual. */

export type Tone = "success" | "warn" | "danger" | "neutral" | "idle";

interface StatusMeta {
  label: string;
  tone: Tone;
}

const STATUS_META: Record<string, StatusMeta> = {
  // Propiedades
  AVAILABLE: { label: "Disponible", tone: "success" },
  RESERVED: { label: "Reservada", tone: "warn" },
  SOLD: { label: "Vendida", tone: "neutral" },
  INACTIVE: { label: "Inactiva", tone: "idle" },
  // Estados genéricos de procesamiento
  READY: { label: "Listo", tone: "success" },
  PROCESSING: { label: "Procesando", tone: "warn" },
  PENDING: { label: "Pendiente", tone: "warn" },
  FAILED: { label: "Falló", tone: "danger" },
  ERROR: { label: "Error", tone: "danger" },
  // Leads (enum real: NEW, CONTACTED, INTERESTED, VISIT_SCHEDULED, NEGOTIATION, CLOSED, LOST)
  NEW: { label: "Nuevo", tone: "neutral" },
  CONTACTED: { label: "Contactado", tone: "warn" },
  INTERESTED: { label: "Interesado", tone: "warn" },
  VISIT_SCHEDULED: { label: "Visita agendada", tone: "success" },
  NEGOTIATION: { label: "Negociación", tone: "warn" },
  CLOSED: { label: "Cerrado", tone: "success" },
  LOST: { label: "Perdido", tone: "danger" },
  // Citas (enum real: REQUESTED, CONFIRMED, CANCELLED, COMPLETED)
  REQUESTED: { label: "Solicitada", tone: "warn" },
  CONFIRMED: { label: "Confirmada", tone: "success" },
  CANCELLED: { label: "Cancelada", tone: "danger" },
  COMPLETED: { label: "Realizada", tone: "neutral" },
  // Roles y sistema
  ok: { label: "OK", tone: "success" },
  USER: { label: "Usuario", tone: "neutral" },
  ASSISTANT: { label: "Asistente", tone: "idle" },
};

export function statusMeta(status: string): StatusMeta {
  return STATUS_META[status] ?? { label: status, tone: "neutral" };
}

/** Orden canónico de la barra de distribución de inventario. */
export const INVENTORY_ORDER = ["AVAILABLE", "RESERVED", "SOLD", "INACTIVE"];

/** Operaciones de inmueble en español. */
const OPERATION_LABELS: Record<string, string> = {
  SALE: "Venta",
  RENT: "Arriendo",
  LEASE: "Arriendo",
};

export function operationLabel(operation: string): string {
  return OPERATION_LABELS[operation] ?? operation;
}

export const LEAD_STATUSES = [
  { value: "NEW", label: "Nuevo" },
  { value: "CONTACTED", label: "Contactado" },
  { value: "INTERESTED", label: "Interesado" },
  { value: "VISIT_SCHEDULED", label: "Visita agendada" },
  { value: "NEGOTIATION", label: "Negociación" },
  { value: "CLOSED", label: "Cerrado" },
  { value: "LOST", label: "Perdido" },
] as const;

export const APPOINTMENT_STATUSES = [
  "REQUESTED",
  "CONFIRMED",
  "CANCELLED",
  "COMPLETED",
] as const;