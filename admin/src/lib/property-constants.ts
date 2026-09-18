export const PROPERTY_TYPES = [
  "casa",
  "apartamento",
  "lote",
  "local",
  "oficina",
  "finca",
  "proyecto",
] as const;

export const OPERATIONS = ["SALE", "RENT"] as const;

export const FEATURES = [
  "garaje",
  "piscina",
  "jardin",
  "terraza",
  "balcon",
  "ascensor",
  "vigilancia",
  "amoblado",
  "mascotas",
  "cocina integral",
  "patio",
  "closet",
  "deposito",
  "chimenea",
  "jacuzzi",
  "gimnasio",
  "vista",
  "esquinero",
  "alto trafico",
  "nacimiento de agua",
  "potrero",
];

export const PROPERTY_STATUSES = [
  { value: "AVAILABLE", label: "Disponible" },
  { value: "RESERVED", label: "Reservada" },
  { value: "SOLD", label: "Vendida" },
  { value: "INACTIVE", label: "Inactiva" },
] as const;

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
  { value: "REQUESTED", label: "Solicitada" },
  { value: "CONFIRMED", label: "Confirmada" },
  { value: "CANCELLED", label: "Cancelada" },
  { value: "COMPLETED", label: "Realizada" },
] as const;