"use server";

import { cookies } from "next/headers";
import { revalidatePath } from "next/cache";
import { backend } from "@/lib/backend";

const VALID_STATUSES = ["AVAILABLE", "RESERVED", "SOLD", "INACTIVE"] as const;
const VALID_TYPES = ["casa", "apartamento", "lote", "local", "oficina", "finca", "proyecto"] as const;
const VALID_OPERATIONS = ["SALE", "RENT"] as const;

export type PropertyActionResult =
  | { ok: true; property?: any }
  | { ok: false; error: string };

export type PropertyFormData = {
  title: string;
  property_type: string;
  operation: string;
  price: number;
  currency?: string;
  city: string;
  neighborhood?: string;
  address?: string;
  area_m2?: number;
  bedrooms?: number;
  bathrooms?: number;
  parking_spaces?: number;
  features?: string[];
  description?: string;
  project_id?: string;
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
  if (typeof data.price !== "number" || data.price <= 0) {
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
  if (data.status && !VALID_STATUSES.includes(data.status as any)) {
    return `Estado inválido. Válidos: ${VALID_STATUSES.join(", ")}`;
  }
  return null;
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
    neighborhood: formData.get("neighborhood") as string,
    address: formData.get("address") as string,
    area_m2: formData.get("area_m2") ? parseFloat(formData.get("area_m2") as string) : undefined,
    bedrooms: formData.get("bedrooms") ? parseInt(formData.get("bedrooms") as string, 10) : undefined,
    bathrooms: formData.get("bathrooms") ? parseInt(formData.get("bathrooms") as string, 10) : undefined,
    parking_spaces: formData.get("parking_spaces") ? parseInt(formData.get("parking_spaces") as string, 10) : undefined,
    features: formData.get("features") ? JSON.parse(formData.get("features") as string) : [],
    description: formData.get("description") as string,
    project_id: formData.get("project_id") as string || undefined,
    status: (formData.get("status") as string) || "AVAILABLE",
  };

  const validationError = validatePropertyData(rawData);
  if (validationError) {
    return { ok: false, error: validationError };
  }

  try {
    const property = await backend("/properties", {
      method: "POST",
      body: JSON.stringify(rawData),
    });
    revalidatePath("/propiedades");
    revalidatePath("/");
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
    "neighborhood", "address", "area_m2", "bedrooms", "bathrooms",
    "parking_spaces", "features", "description", "project_id", "status"
  ];
  
  for (const field of fields) {
    const value = formData.get(field);
    if (value !== null && value !== "") {
      if (field === "price" || field === "area_m2") {
        (rawData as any)[field] = parseFloat(value as string);
      } else if (field === "bedrooms" || field === "bathrooms" || field === "parking_spaces") {
        (rawData as any)[field] = parseInt(value as string, 10);
      } else if (field === "features") {
        (rawData as any)[field] = JSON.parse(value as string);
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
  if (rawData.price !== undefined && (rawData.price <= 0 || rawData.price > 999999999999.99)) {
    return { ok: false, error: "Precio inválido" };
  }
  if (rawData.city !== undefined && (!rawData.city || rawData.city.length > 80)) {
    return { ok: false, error: "Ciudad inválida" };
  }
  if (rawData.status && !VALID_STATUSES.includes(rawData.status as any)) {
    return { ok: false, error: `Estado inválido: ${VALID_STATUSES.join(", ")}` };
  }

  try {
    const property = await backend(`/properties/${id}`, {
      method: "PATCH",
      body: JSON.stringify(rawData),
    });
    revalidatePath("/propiedades");
    revalidatePath("/");
    revalidatePath(`/propiedades/${id}`);
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
    revalidatePath("/propiedades");
    revalidatePath("/");
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
  revalidatePath("/propiedades");
  revalidatePath("/");
  revalidatePath(`/propiedades/${id}`);
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
    revalidatePath("/propiedades");
    revalidatePath("/");
    revalidatePath(`/propiedades/${propertyId}`);
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
    revalidatePath("/propiedades");
    revalidatePath("/");
    revalidatePath(`/propiedades/${propertyId}`);
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
    revalidatePath("/propiedades");
    revalidatePath("/");
    revalidatePath(`/propiedades/${propertyId}`);
    return { ok: true };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) };
  }
}

export async function uploadPropertyImage(
  propertyId: string,
  file: File
): Promise<PropertyActionResult> {
  try {
    const formData = new FormData();
    formData.append("file", file);
    
    const cookieStore = await cookies();
    const accessToken = cookieStore.get("admin_access_token")?.value;
    const serviceToken = process.env.ADMIN_SERVICE_TOKEN ?? "";
    
    const headers: HeadersInit = {};
    if (accessToken) {
      headers["Authorization"] = `Bearer ${accessToken}`;
    } else if (serviceToken) {
      headers["X-Admin-Token"] = serviceToken;
    }
    
    const res = await fetch(`${process.env.API_BASE_URL ?? "http://127.0.0.1:8000"}/properties/${propertyId}/images`, {
      method: "POST",
      headers,
      body: formData,
    });
    
    if (!res.ok) {
      const detail = await res.text().catch(() => "");
      throw new Error(`API ${res.status}: ${detail.slice(0, 200)}`);
    }
    
    revalidatePath("/propiedades");
    revalidatePath("/");
    revalidatePath(`/propiedades/${propertyId}`);
    return { ok: true };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) };
  }
}

export async function patchLead(
  id: string,
  data: any
): Promise<PropertyActionResult> {
  try {
    const lead = await backend(`/leads/${id}`, {
      method: "PATCH",
      body: JSON.stringify(data),
    });
    revalidatePath("/leads");
    revalidatePath(`/leads/${id}`);
    return { ok: true, property: lead };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) };
  }
}