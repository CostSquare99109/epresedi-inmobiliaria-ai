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
  // Documentos · RAG
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

/** Etiquetas en español para los intents del orquestador. */
const INTENT_LABELS: Record<string, string> = {
  SEARCH_PROPERTY: "Búsqueda de propiedades",
  PROPERTY_DETAILS: "Detalle de propiedad",
  PROPERTY_IMAGES: "Imágenes de propiedad",
  COMPARE_PROPERTIES: "Comparación de propiedades",
  PROPERTY_DOCUMENT_QUESTION: "Pregunta sobre documento",
  PRICE_QUERY: "Consulta de precio",
  LOCATION_QUERY: "Consulta de ubicación",
  SAVE_PROPERTY: "Guardar propiedad",
  REMOVE_PROPERTY: "Quitar de favoritos",
  SAVE_SEARCH: "Guardar búsqueda",
  LIST_SAVED_SEARCHES: "Búsquedas guardadas",
  SCHEDULE_VISIT: "Agendar visita",
  CANCEL_APPOINTMENT: "Cancelar cita",
  CONTACT_AGENT: "Contactar agente",
  FINANCING_QUESTION: "Consulta de financiación",
  SELL_PROPERTY: "Vender propiedad",
  RENT_PROPERTY: "Alquilar propiedad",
  GENERAL_FAQ: "Pregunta general",
  GREETING: "Saludo",
  UNKNOWN: "Sin clasificar",
};

export function intentLabel(intent: string): string {
  return INTENT_LABELS[intent] ?? intent;
}

/** Operaciones de inmueble en español. */
const OPERATION_LABELS: Record<string, string> = {
  SALE: "Venta",
  RENT: "Arriendo",
  LEASE: "Arriendo",
};

export function operationLabel(operation: string): string {
  return OPERATION_LABELS[operation] ?? operation;
}
