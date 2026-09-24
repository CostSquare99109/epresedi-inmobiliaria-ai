"use client";

import { backend, PROXY } from "../../api/client";
import {
  FLOOR_OFFER_FULL,
  normalizeFloorOfferType,
  normalizeOfferedFloors,
  validateFloorOffer,
} from "../../lib/floors";

const VALID_STATUSES = ["AVAILABLE", "RESERVED", "SOLD", "INACTIVE"] as const;
const VALID_TYPES = ["casa", "apartamento", "lote", "local", "oficina", "finca", "proyecto"] as const;
const VALID_OPERATIONS = ["SALE", "RENT"] as const;
const VALID_SERVICES = ["incluye", "no_incluye"] as const;

export type PropertyActionResult =
  | { ok: true; property?: any }
  | { ok: false; error: string };

export type VisitingHourInterval = {
  start: string; // HH:MM
  end: string;   // HH:MM
};

export type VisitingHour = {
  weekday: number;
  is_closed: boolean;
  intervals: VisitingHourInterval[];
};

export type PropertyFormData = {
  title: string;
  property_type: string;
  operation: string;
  price: number;
  currency?: string;
  city: string;
  neighborhood?: string;
  address?: string;
  street?: string;
  street_number?: string;
  descriptive_location?: string;
  nomenclatura?: string;
  area_m2?: number;
  bedrooms?: number;
  bedrooms_description?: string;
  bathrooms?: number;
  bathrooms_description?: string;
  living_room_description?: string;
  laundry_area_description?: string;
  parking_spaces?: number;
  has_parking?: boolean;
  parking_description?: string;
  rent_price?: number;
  services_included?: string;
  visiting_hours?: VisitingHour[];
  floors?: number;
  floor_offer_type?: string;
  offered_floors?: number[];
  has_kitchen?: boolean;
  has_living_room?: boolean;
  has_laundry_area?: boolean;
  features?: string[];
  description?: string;
  branch_id?: string;
  status?: string;
};

function validatePropertyData(data: PropertyFormData): string | null {
  if (!data.title || data.title.trim().length === 0) {
    return "El título es obligatorio";
  }
  if (data.title.length > 200) {
    return "El título no puede exceder 200 caracteres";
  }
  if (!VALID_TYPES.includes(data.property_type as any)) {
    return `Tipo de propiedad inválido. Válidos: ${VALID_TYPES.join(", ")}`;
  }
  if (!VALID_OPERATIONS.includes(data.operation as any)) {
    return `Operación inválida. Válidas: ${VALID_OPERATIONS.join(", ")}`;
  }
  if (typeof data.price !== "number" || !Number.isFinite(data.price) || data.price <= 0) {
    return "El precio debe ser un número mayor a 0";
  }
  if (data.price > 999999999999.99) {
    return "El precio excede el máximo permitido";
  }
  if (!data.city || data.city.trim().length === 0) {
    return "La ciudad es obligatoria";
  }
  if (data.city.length > 80) {
    return "La ciudad no puede exceder 80 caracteres";
  }
  if (data.neighborhood && data.neighborhood.length > 120) {
    return "El barrio no puede exceder 120 caracteres";
  }
  if (data.address && data.address.length > 240) {
    return "La dirección no puede exceder 240 caracteres";
  }
  if (data.nomenclatura && data.nomenclatura.length > 240) {
    return "La nomenclatura no puede exceder 240 caracteres";
  }
  if (data.area_m2 !== undefined && (data.area_m2 < 0 || data.area_m2 > 99999999.99)) {
    return "Área inválida";
  }
  if (data.bedrooms !== undefined && (data.bedrooms < 0 || data.bedrooms > 99)) {
    return "Habitaciones inválidas";
  }
  if (data.bathrooms !== undefined && (data.bathrooms < 0 || data.bathrooms > 99)) {
    return "Baños inválidos";
  }
  if (data.parking_spaces !== undefined && (data.parking_spaces < 0 || data.parking_spaces > 99)) {
    return "Parqueaderos inválidos";
  }
  if (data.floors !== undefined && (data.floors < 1 || data.floors > 99)) {
    return "Número de pisos inválido: debe estar entre 1 y 99";
  }
  const floorError = validateFloorOffer(
    data.floors ?? null,
    data.floor_offer_type ?? FLOOR_OFFER_FULL,
    data.offered_floors ?? []
  );
  if (floorError) {
    return floorError;
  }
  // En venta siempre se ofrece la propiedad completa (la UI ni lo pregunta).
  if (
    data.operation === "SALE" &&
    (normalizeFloorOfferType(data.floor_offer_type ?? FLOOR_OFFER_FULL) !== FLOOR_OFFER_FULL ||
      normalizeOfferedFloors(data.offered_floors ?? []).length > 0)
  ) {
    return "En venta se ofrece la propiedad completa";
  }
  if (data.rent_price !== undefined && (data.rent_price < 0 || data.rent_price > 999999999999.99)) {
    return "Precio de alquiler inválido";
  }
  if (data.services_included && !VALID_SERVICES.includes(data.services_included as any)) {
    return `Servicios públicos inválido. Válidos: ${VALID_SERVICES.join(", ")}`;
  }
  if (data.status && !VALID_STATUSES.includes(data.status as any)) {
    return `Estado inválido. Válidos: ${VALID_STATUSES.join(", ")}`;
  }
  if (data.visiting_hours) {
    for (const day of data.visiting_hours) {
      if (day.weekday < 0 || day.weekday > 6) {
        return "Día de la semana inválido en horarios de visita";
      }
      if (!day.is_closed && day.intervals) {
        for (const interval of day.intervals) {
          if (!isValidTime(interval.start) || !isValidTime(interval.end)) {
            return "Formato de hora inválido en horarios de visita (use HH:MM)";
          }
          if (!isTimeBefore(interval.start, interval.end)) {
            return "La hora de inicio debe ser anterior a la hora de fin en horarios de visita";
          }
        }
      }
    }
  }
  return null;
}

function isValidTime(time: string): boolean {
  return /^([01]\d|2[0-3]):([0-5]\d)$/.test(time);
}

function isTimeBefore(start: string, end: string): boolean {
  const [sh, sm] = start.split(":").map(Number);
  const [eh, em] = end.split(":").map(Number);
  return sh * 60 + sm < eh * 60 + em;
}

export async function createProperty(
  formData: FormData
): Promise<PropertyActionResult> {
  const rawData: PropertyFormData = {
    title: formData.get("title") as string,
    property_type: formData.get("property_type") as string,
    operation: formData.get("operation") as string,
    price: parseFloat(formData.get("price") as string),
    currency: (formData.get("currency") as string) || "COP",
    city: formData.get("city") as string,
    neighborhood: (formData.get("neighborhood") as string) || "",
    address: (formData.get("address") as string) || "",
    street: (formData.get("street") as string) || "",
    street_number: (formData.get("street_number") as string) || "",
    descriptive_location: (formData.get("descriptive_location") as string) || "",
    nomenclatura: (formData.get("nomenclatura") as string) || "",
    area_m2: formData.get("area_m2") ? parseFloat(formData.get("area_m2") as string) : undefined,
    bedrooms: formData.get("bedrooms") ? parseInt(formData.get("bedrooms") as string, 10) : undefined,
    bedrooms_description: formData.get("bedrooms_description") as string || "",
    bathrooms: formData.get("bathrooms") ? parseInt(formData.get("bathrooms") as string, 10) : undefined,
    bathrooms_description: formData.get("bathrooms_description") as string || "",
    living_room_description: formData.get("living_room_description") as string || "",
    laundry_area_description: formData.get("laundry_area_description") as string || "",
    parking_spaces: formData.get("parking_spaces") ? parseInt(formData.get("parking_spaces") as string, 10) : undefined,
    has_parking: formData.get("has_parking") === "true",
    parking_description: formData.get("parking_description") as string || "",
    rent_price: formData.get("rent_price") ? parseFloat(formData.get("rent_price") as string) : undefined,
    services_included: (formData.get("services_included") as string) || "no_incluye",
    visiting_hours: formData.get("visiting_hours") ? JSON.parse(formData.get("visiting_hours") as string) : [],
    floors: formData.get("floors") ? parseInt(formData.get("floors") as string, 10) : undefined,
    floor_offer_type: normalizeFloorOfferType((formData.get("floor_offer_type") as string) || FLOOR_OFFER_FULL),
    offered_floors: formData.get("offered_floors")
      ? normalizeOfferedFloors(JSON.parse(formData.get("offered_floors") as string))
      : [],
    has_kitchen: formData.get("has_kitchen") === "true",
    has_living_room: formData.get("has_living_room") === "true",
    has_laundry_area: formData.get("has_laundry_area") === "true",
    features: formData.get("features") ? JSON.parse(formData.get("features") as string) : [],
    description: (formData.get("description") as string) || "",
    branch_id: formData.get("branch_id") as string || undefined,
    status: (formData.get("status") as string) || "AVAILABLE",
  };

  // Precio único según operación: en arriendo el precio ES el canon mensual.
  if (rawData.operation === "RENT" && rawData.rent_price === undefined) {
    rawData.rent_price = rawData.price;
  }

  const validationError = validatePropertyData(rawData);
  if (validationError) {
    return { ok: false, error: validationError };
  }

  try {
    const property = await backend("/properties", {
      method: "POST",
      body: JSON.stringify(rawData),
    });
    return { ok: true, property };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) };
  }
}

export async function updateProperty(
  id: string,
  formData: FormData
): Promise<PropertyActionResult> {
  const rawData: Partial<PropertyFormData> = {};

  const fields = [
    "title", "property_type", "operation", "price", "currency", "city",
    "neighborhood", "address", "street", "street_number", "descriptive_location",
    "nomenclatura", "area_m2", "bedrooms", "bedrooms_description", "bathrooms",
    "bathrooms_description", "living_room_description", "laundry_area_description",
    "parking_spaces", "has_parking", "parking_description", "rent_price",
    "services_included", "visiting_hours", "floors", "floor_offer_type", "offered_floors",
    "has_kitchen", "has_living_room",
    "has_laundry_area", "features", "description", "branch_id", "status"
  ];

  for (const field of fields) {
    const value = formData.get(field);
    if (value !== null && value !== "") {
      if (field === "price" || field === "area_m2" || field === "rent_price") {
        (rawData as any)[field] = parseFloat(value as string);
      } else if (field === "bedrooms" || field === "bathrooms" || field === "parking_spaces" || field === "floors") {
        (rawData as any)[field] = parseInt(value as string, 10);
      } else if (field === "features" || field === "visiting_hours" || field === "offered_floors") {
        (rawData as any)[field] = JSON.parse(value as string);
      } else if (field === "has_parking" || field === "has_kitchen" || field === "has_living_room" || field === "has_laundry_area") {
        (rawData as any)[field] = value === "true";
      } else {
        (rawData as any)[field] = value;
      }
    }
  }

  if (rawData.title && rawData.title.length > 200) {
    return { ok: false, error: "El título no puede exceder 200 caracteres" };
  }
  if (rawData.property_type && !VALID_TYPES.includes(rawData.property_type as any)) {
    return { ok: false, error: `Tipo inválido: ${VALID_TYPES.join(", ")}` };
  }
  if (rawData.operation && !VALID_OPERATIONS.includes(rawData.operation as any)) {
    return { ok: false, error: `Operación inválida: ${VALID_OPERATIONS.join(", ")}` };
  }
  if (rawData.price !== undefined && (!Number.isFinite(rawData.price) || rawData.price <= 0 || rawData.price > 999999999999.99)) {
    return { ok: false, error: "Precio inválido" };
  }
  if (rawData.rent_price !== undefined && (!Number.isFinite(rawData.rent_price) || rawData.rent_price <= 0 || rawData.rent_price > 999999999999.99)) {
    return { ok: false, error: "Precio de alquiler inválido" };
  }
  if (rawData.city !== undefined && (!rawData.city || rawData.city.length > 80)) {
    return { ok: false, error: "Ciudad inválida" };
  }
  if (rawData.services_included && !VALID_SERVICES.includes(rawData.services_included as any)) {
    return { ok: false, error: `Servicios inválido: ${VALID_SERVICES.join(", ")}` };
  }
  if (rawData.status && !VALID_STATUSES.includes(rawData.status as any)) {
    return { ok: false, error: `Estado inválido: ${VALID_STATUSES.join(", ")}` };
  }
  if (rawData.visiting_hours) {
    for (const day of rawData.visiting_hours) {
      if (day.weekday < 0 || day.weekday > 6) {
        return { ok: false, error: "Día de la semana inválido en horarios de visita" };
      }
      if (!day.is_closed && day.intervals) {
        for (const interval of day.intervals) {
          if (!isValidTime(interval.start) || !isValidTime(interval.end)) {
            return { ok: false, error: "Formato de hora inválido en horarios de visita (use HH:MM)" };
          }
          if (!isTimeBefore(interval.start, interval.end)) {
            return { ok: false, error: "La hora de inicio debe ser anterior a la hora de fin en horarios de visita" };
          }
        }
      }
    }
  }
  if (
    rawData.floors !== undefined ||
    rawData.floor_offer_type !== undefined ||
    rawData.offered_floors !== undefined
  ) {
    const floorError = validateFloorOffer(
      rawData.floors ?? null,
      rawData.floor_offer_type ?? FLOOR_OFFER_FULL,
      rawData.offered_floors ?? []
    );
    if (floorError) {
      // En edición el total puede venir del registro guardado: solo se valida
      // la coherencia de lo enviado (el backend revalida contra lo guardado).
      const needsTotal = floorError === "Indica el número total de pisos para ofertar pisos específicos";
      const sendsOffered =
        Array.isArray(rawData.offered_floors) && rawData.offered_floors.length > 0;
      if (!(needsTotal && rawData.floors === undefined && sendsOffered)) {
        return { ok: false, error: floorError };
      }
    }
  }
  if (rawData.operation === "SALE") {
    const offer = rawData.floor_offer_type ?? FLOOR_OFFER_FULL;
    const offered = rawData.offered_floors ?? [];
    if (offer !== FLOOR_OFFER_FULL || offered.length > 0) {
      return { ok: false, error: "En venta se ofrece la propiedad completa" };
    }
  }
  // El backend revalida contra los valores guardados.
  try {
    const property = await backend(`/properties/${id}`, {
      method: "PATCH",
      body: JSON.stringify(rawData),
    });
    return { ok: true, property };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) };
  }
}

export async function deleteProperty(id: string): Promise<PropertyActionResult> {
  try {
    await backend(`/properties/${id}`, {
      method: "DELETE",
    });
    return { ok: true };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) };
  }
}

export async function updatePropertyStatus(
  id: string,
  next: string,
): Promise<PropertyActionResult> {
  if (!VALID_STATUSES.includes(next as (typeof VALID_STATUSES)[number])) {
    return { ok: false, error: `Estado no válido: ${next}` };
  }
  try {
    await backend(`/properties/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ status: next }),
    });
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) };
  }
  return { ok: true };
}

export async function deletePropertyImage(
  propertyId: string,
  filename: string
): Promise<PropertyActionResult> {
  try {
    await backend(`/properties/${propertyId}/images/${filename}`, {
      method: "DELETE",
    });
    return { ok: true };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) };
  }
}

export async function reorderPropertyImages(
  propertyId: string,
  filenames: string[]
): Promise<PropertyActionResult> {
  try {
    await backend(`/properties/${propertyId}/images/reorder`, {
      method: "PATCH",
      body: JSON.stringify({ filenames }),
    });
    return { ok: true };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) };
  }
}

export async function setPropertyCoverImage(
  propertyId: string,
  filename: string
): Promise<PropertyActionResult> {
  try {
    await backend(`/properties/${propertyId}/images/${filename}/cover`, {
      method: "PATCH",
    });
    return { ok: true };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) };
  }
}

export async function updatePropertyImageMetadata(
  propertyId: string,
  filename: string,
  name: string,
  description: string
): Promise<PropertyActionResult> {
  try {
    await backend(`/properties/${propertyId}/images/${filename}`, {
      method: "PATCH",
      body: JSON.stringify({ name, description }),
    });
    return { ok: true };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) };
  }
}

export async function uploadPropertyImage(
  propertyId: string,
  file: File,
  name = "",
  description = "",
  group = "general",
  extraName = ""
): Promise<PropertyActionResult> {
  try {
    const formData = new FormData();
    formData.append("file", file);
    if (name) formData.append("name", name);
    if (description) formData.append("description", description);
    if (group) formData.append("group", group);
    if (extraName) formData.append("extra_name", extraName);

    const res = await fetch(`${PROXY}/properties/${propertyId}/images`, {
      method: "POST",
      body: formData,
    });

    if (!res.ok) {
      const detail = await res.text().catch(() => "");
      throw new Error(`API ${res.status}: ${detail.slice(0, 200)}`);
    }

    const data = await res.json().catch(() => ({}));
    return { ok: true, property: data };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) };
  }
}