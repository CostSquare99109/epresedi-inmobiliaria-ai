/** Modelo de pisos: total físico vs. parte ofertada (textos humanos para la UI). */

export const FLOOR_OFFER_FULL = "full_property";
export const FLOOR_OFFER_SINGLE = "single_floor";
export const FLOOR_OFFER_MULTIPLE = "multiple_floors";
export const FLOOR_OFFER_PARTIAL = "partial";

export type FloorOfferType =
  | typeof FLOOR_OFFER_FULL
  | typeof FLOOR_OFFER_SINGLE
  | typeof FLOOR_OFFER_MULTIPLE
  | typeof FLOOR_OFFER_PARTIAL;

export const FLOOR_OFFER_TYPES: FloorOfferType[] = [
  FLOOR_OFFER_FULL,
  FLOOR_OFFER_SINGLE,
  FLOOR_OFFER_MULTIPLE,
  FLOOR_OFFER_PARTIAL,
];

export const FLOOR_OFFER_LABELS: Record<FloorOfferType, string> = {
  [FLOOR_OFFER_FULL]: "Toda la propiedad",
  [FLOOR_OFFER_SINGLE]: "Piso completo",
  [FLOOR_OFFER_MULTIPLE]: "Varios pisos",
  [FLOOR_OFFER_PARTIAL]: "Parte de la propiedad",
};

/**
 * La UI solo pregunta dos cosas: "Toda la propiedad" o escoger los pisos a
 * arrendar (uno o varios). El mapeo a los tipos del backend es automático:
 * 1 piso escogido -> single_floor, 2+ -> multiple_floors.
 */
export type FloorUiChoice = "full" | "floors" | "partial";

export function floorChoiceOptions(includePartial: boolean): { value: string; label: string }[] {
  const options = [
    { value: "full" satisfies FloorUiChoice, label: "Toda la propiedad" },
    { value: "floors" satisfies FloorUiChoice, label: "Escoger pisos" },
  ];
  if (includePartial) {
    options.push({ value: "partial" satisfies FloorUiChoice, label: FLOOR_OFFER_LABELS[FLOOR_OFFER_PARTIAL] });
  }
  return options;
}

/** De tipo backend a opción visible (partial solo sobrevive al editar legados). */
export function uiChoiceFromOffer(offer: unknown): FloorUiChoice {
  const normalized = normalizeFloorOfferType(offer);
  if (normalized === FLOOR_OFFER_FULL) return "full";
  if (normalized === FLOOR_OFFER_PARTIAL) return "partial";
  return "floors";
}

/** De cantidad escogida a tipo backend: 1 -> piso completo, 2+ -> varios. */
export function offerFromSelection(count: number): FloorOfferType {
  return count === 1 ? FLOOR_OFFER_SINGLE : FLOOR_OFFER_MULTIPLE;
}

export const MAX_FLOORS = 99;

export function normalizeFloorOfferType(value: unknown): FloorOfferType {
  return typeof value === "string" &&
    (FLOOR_OFFER_TYPES as string[]).includes(value)
    ? (value as FloorOfferType)
    : FLOOR_OFFER_FULL;
}

export function normalizeOfferedFloors(value: unknown): number[] {
  if (value === null || value === undefined) return [];
  const items = Array.isArray(value) ? value : [value];
  const out: number[] = [];
  for (const item of items) {
    const n = typeof item === "number" ? item : parseInt(String(item), 10);
    if (!Number.isInteger(n)) continue;
    out.push(n);
  }
  return [...new Set(out)].sort((a, b) => a - b);
}

/** Opciones dinámicas "Piso 1..N" según el número total de pisos. */
export function floorOptions(totalFloors: number | null | undefined): { value: string; label: string }[] {
  const n = typeof totalFloors === "number" ? Math.floor(totalFloors) : NaN;
  if (!Number.isInteger(n) || n < 1) return [];
  const cap = Math.min(n, MAX_FLOORS);
  return Array.from({ length: cap }, (_, i) => ({
    value: String(i + 1),
    label: `Piso ${i + 1}`,
  }));
}

/** Elimina selecciones inválidas cuando cambia el número total de pisos. */
export function pruneOfferedFloors(offered: number[], totalFloors: number | null | undefined): number[] {
  if (totalFloors === null || totalFloors === undefined) return [...offered];
  const n = typeof totalFloors === "number" ? totalFloors : parseInt(String(totalFloors), 10);
  if (!Number.isInteger(n) || n < 1) return [...offered];
  return offered.filter((p) => p >= 1 && p <= n);
}

/** Validación compartida (creación y edición). Devuelve mensaje en español o null. */
export function validateFloorOffer(
  floors: number | null | undefined | "",
  offerType: unknown,
  offeredFloors: unknown
): string | null {
  const offer = normalizeFloorOfferType(offerType);
  const offered = normalizeOfferedFloors(offeredFloors);
  const hasTotal = floors !== null && floors !== undefined && floors !== "";
  let total: number | null = null;
  if (hasTotal) {
    const n = typeof floors === "number" ? floors : parseInt(String(floors), 10);
    if (!Number.isInteger(n) || n < 1 || n > MAX_FLOORS) {
      return `Número de pisos inválido: debe estar entre 1 y ${MAX_FLOORS}`;
    }
    total = n;
  }
  for (const p of offered) {
    if (!Number.isInteger(p) || p < 1 || p > MAX_FLOORS) {
      return `Piso ofertado inválido: Piso ${p} (debe estar entre 1 y ${MAX_FLOORS})`;
    }
  }
  if (offer === FLOOR_OFFER_FULL) {
    if (offered.length > 0) return "Propiedad completa no requiere seleccionar pisos individuales";
    return null;
  }
  if (offer === FLOOR_OFFER_PARTIAL) {
    if (offered.length > 0) {
      return "Parte de la propiedad no usa selección de pisos: describe la unidad en la descripción";
    }
    return null;
  }
  if (total === null) {
    return "Indica el número total de pisos para ofertar pisos específicos";
  }
  const tooHigh = offered.find((p) => p > (total as number));
  if (tooHigh !== undefined) {
    return `Piso ${tooHigh} no existe: la propiedad tiene ${total} ${total === 1 ? "piso" : "pisos"}`;
  }
  if (offer === FLOOR_OFFER_SINGLE) {
    if (offered.length !== 1) return "Piso completo requiere seleccionar exactamente un piso";
    return null;
  }
  if (offered.length < 1) return "Varios pisos requiere seleccionar al menos un piso";
  return null;
}

/** "2 pisos · Piso 1" para detalle y listados. */
export function formatFloorsDisplay(
  floors: number | null | undefined,
  offerType: unknown,
  offeredFloors: unknown,
  operation?: string
): string | null {
  const offer = normalizeFloorOfferType(offerType);
  const offered = normalizeOfferedFloors(offeredFloors);
  if (floors === null || floors === undefined) {
    return offer === FLOOR_OFFER_FULL ? null : FLOOR_OFFER_LABELS[offer];
  }
  const base = `${floors} ${floors === 1 ? "piso" : "pisos"}`;
  const isRent = operation === "RENT" || operation === "LEASE";
  const verb = isRent ? "se arriendan" : "se venden";

  if (offer === FLOOR_OFFER_FULL) return `${base} · ${FLOOR_OFFER_LABELS[FLOOR_OFFER_FULL]}`;
  if (offer === FLOOR_OFFER_PARTIAL) return `${base} · ${FLOOR_OFFER_LABELS[FLOOR_OFFER_PARTIAL]}`;
  if (offer === FLOOR_OFFER_SINGLE && offered.length === 1) return `${base} · Piso ${offered[0]} (${verb})`;
  if (offered.length > 0) {
    const many = offered.length === 1 ? "Piso" : "Pisos";
    return `${base} · ${many} ${offered.join(" y ")} (${verb})`;
  }
  return `${base} · ${FLOOR_OFFER_LABELS[offer]}`;
}
