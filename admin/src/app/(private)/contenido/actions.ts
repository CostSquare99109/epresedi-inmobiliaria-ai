"use server";

import { cookies } from "next/headers";
import { revalidatePath } from "next/cache";

const API_BASE = process.env.API_BASE_URL ?? "http://127.0.0.1:8000";

async function getAuthHeaders(): Promise<HeadersInit> {
  const cookieStore = await cookies();
  const accessToken = cookieStore.get("admin_access_token")?.value;
  const serviceToken = process.env.ADMIN_SERVICE_TOKEN ?? "";

  if (accessToken) {
    return { "Authorization": `Bearer ${accessToken}`, "Content-Type": "application/json" };
  }
  if (serviceToken) {
    return { "X-Admin-Token": serviceToken, "Content-Type": "application/json" };
  }
  return { "Content-Type": "application/json" };
}

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const authHeaders = await getAuthHeaders();
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { ...authHeaders, ...(init?.headers ?? {}) },
    cache: "no-store",
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(`API ${res.status} en ${path}: ${detail.slice(0, 200)}`);
  }
  return (await res.json()) as T;
}

export type CmsContentActionResult =
  | { ok: true; content?: any }
  | { ok: false; error: string };

export async function createCmsContent(
  formData: FormData
): Promise<CmsContentActionResult> {
  const key = formData.get("key") as string;
  const type = formData.get("type") as string;
  const value = formData.get("value") as string || "";
  const label = formData.get("label") as string;
  const description = formData.get("description") as string || "";
  const group = formData.get("group") as string || "general";
  const is_public = formData.get("is_public") === "true";

  if (!key || key.trim().length === 0) {
    return { ok: false, error: "La clave es obligatoria" };
  }
  if (key.length > 100) {
    return { ok: false, error: "La clave no puede exceder 100 caracteres" };
  }
  if (!label || label.trim().length === 0) {
    return { ok: false, error: "La etiqueta es obligatoria" };
  }
  if (label.length > 200) {
    return { ok: false, error: "La etiqueta no puede exceder 200 caracteres" };
  }
  const validTypes = ["text", "html", "json", "image", "number", "boolean"];
  if (!validTypes.includes(type)) {
    return { ok: false, error: `Tipo inválido: ${validTypes.join(", ")}` };
  }

  try {
    const content = await apiFetch("/cms-content", {
      method: "POST",
      body: JSON.stringify({ key: key.trim(), type, value, label: label.trim(), description, group, is_public }),
    });
    revalidatePath("/contenido");
    return { ok: true, content };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) };
  }
}

export async function updateCmsContent(
  id: string,
  formData: FormData
): Promise<CmsContentActionResult> {
  const data: Record<string, any> = {};

  const type = formData.get("type") as string;
  if (type !== null && type !== "") {
    const validTypes = ["text", "html", "json", "image", "number", "boolean"];
    if (!validTypes.includes(type)) {
      return { ok: false, error: `Tipo inválido: ${validTypes.join(", ")}` };
    }
    data.type = type;
  }

  const value = formData.get("value") as string;
  if (value !== null && value !== undefined) {
    data.value = value;
  }

  const label = formData.get("label") as string;
  if (label !== null && label !== "") {
    if (label.length > 200) {
      return { ok: false, error: "La etiqueta no puede exceder 200 caracteres" };
    }
    data.label = label.trim();
  }

  const description = formData.get("description") as string;
  if (description !== null && description !== "") {
    data.description = description;
  }

  const group = formData.get("group") as string;
  if (group !== null && group !== "") {
    data.group = group;
  }

  const is_public = formData.get("is_public") as string;
  if (is_public !== null && is_public !== "") {
    data.is_public = is_public === "true";
  }

  if (Object.keys(data).length === 0) {
    return { ok: false, error: "No hay cambios para guardar" };
  }

  try {
    const content = await apiFetch(`/cms-content/${id}`, {
      method: "PATCH",
      body: JSON.stringify(data),
    });
    revalidatePath("/contenido");
    return { ok: true, content };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) };
  }
}

export async function deleteCmsContent(id: string): Promise<CmsContentActionResult> {
  try {
    await apiFetch(`/cms-content/${id}`, {
      method: "DELETE",
    });
    revalidatePath("/contenido");
    return { ok: true };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) };
  }
}