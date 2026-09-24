/** Constantes para el dominio de propiedades. */

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

export const SERVICES_INCLUDED = [
  { value: "incluye", label: "Incluye servicios" },
  { value: "no_incluye", label: "No incluye servicios" },
] as const;

export const WEEKDAYS = [
  { value: 0, name: "Lunes", short: "Lun" },
  { value: 1, name: "Martes", short: "Mar" },
  { value: 2, name: "Miércoles", short: "Mié" },
  { value: 3, name: "Jueves", short: "Jue" },
  { value: 4, name: "Viernes", short: "Vie" },
  { value: 5, name: "Sábado", short: "Sáb" },
  { value: 6, name: "Domingo", short: "Dom" },
] as const;