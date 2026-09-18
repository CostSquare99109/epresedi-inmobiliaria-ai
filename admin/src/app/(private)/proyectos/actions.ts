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

export type ProjectActionResult =
  | { ok: true; project?: any }
  | { ok: false; error: string };

export async function createProject(
  formData: FormData
): Promise<ProjectActionResult> {
  const name = formData.get("name") as string;
  const description = formData.get("description") as string || "";
  const city = formData.get("city") as string || "";

  if (!name || name.trim().length === 0) {
    return { ok: false, error: "El nombre es obligatorio" };
  }
  if (name.length > 160) {
    return { ok: false, error: "El nombre no puede exceder 160 caracteres" };
  }
  if (description.length > 5000) {
    return { ok: false, error: "La descripción no puede exceder 5000 caracteres" };
  }
  if (city.length > 80) {
    return { ok: false, error: "La ciudad no puede exceder 80 caracteres" };
  }

  try {
    const project = await apiFetch("/projects", {
      method: "POST",
      body: JSON.stringify({ name: name.trim(), description, city }),
    });
    revalidatePath("/proyectos");
    return { ok: true, project };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) };
  }
}

export async function updateProject(
  id: string,
  formData: FormData
): Promise<ProjectActionResult> {
  const data: Record<string, any> = {};

  const name = formData.get("name") as string;
  if (name !== null && name !== "") {
    if (name.length > 160) {
      return { ok: false, error: "El nombre no puede exceder 160 caracteres" };
    }
    data.name = name.trim();
  }

  const description = formData.get("description") as string;
  if (description !== null && description !== "") {
    if (description.length > 5000) {
      return { ok: false, error: "La descripción no puede exceder 5000 caracteres" };
    }
    data.description = description;
  }

  const city = formData.get("city") as string;
  if (city !== null && city !== "") {
    if (city.length > 80) {
      return { ok: false, error: "La ciudad no puede exceder 80 caracteres" };
    }
    data.city = city;
  }

  if (Object.keys(data).length === 0) {
    return { ok: false, error: "No hay cambios para guardar" };
  }

  try {
    const project = await apiFetch(`/projects/${id}`, {
      method: "PATCH",
      body: JSON.stringify(data),
    });
    revalidatePath("/proyectos");
    return { ok: true, project };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) };
  }
}

export async function deleteProject(id: string): Promise<ProjectActionResult> {
  try {
    await apiFetch(`/projects/${id}`, {
      method: "DELETE",
    });
    revalidatePath("/proyectos");
    return { ok: true };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) };
  }
}