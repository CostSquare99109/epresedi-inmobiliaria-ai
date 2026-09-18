"use server";

import { cookies } from "next/headers";
import { revalidatePath } from "next/cache";

const API_BASE = process.env.API_BASE_URL ?? "http://127.0.0.1:8000";
const VALID_ROLES = ["superadmin", "admin", "editor", "asesor"] as const;

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

export type UserActionResult =
  | { ok: true; user?: any }
  | { ok: false; error: string };

export async function createUser(
  formData: FormData
): Promise<UserActionResult> {
  const email = formData.get("email") as string;
  const name = formData.get("name") as string;
  const password = formData.get("password") as string;
  const role = formData.get("role") as string;

  if (!email || !email.includes("@")) {
    return { ok: false, error: "Email inválido" };
  }
  if (!name || name.trim().length === 0) {
    return { ok: false, error: "El nombre es obligatorio" };
  }
  if (name.length > 160) {
    return { ok: false, error: "El nombre no puede exceder 160 caracteres" };
  }
  if (!password || password.length < 8) {
    return { ok: false, error: "La contraseña debe tener al menos 8 caracteres" };
  }
  if (!VALID_ROLES.includes(role as any)) {
    return { ok: false, error: `Rol inválido. Válidos: ${VALID_ROLES.join(", ")}` };
  }

  try {
    const user = await apiFetch("/admin-users", {
      method: "POST",
      body: JSON.stringify({ email: email.trim().toLowerCase(), name: name.trim(), password, role }),
    });
    revalidatePath("/usuarios");
    return { ok: true, user };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) };
  }
}

export async function updateUser(
  id: string,
  formData: FormData
): Promise<UserActionResult> {
  const data: Record<string, any> = {};

  const name = formData.get("name") as string;
  if (name !== null && name !== "") {
    if (name.length > 160) {
      return { ok: false, error: "El nombre no puede exceder 160 caracteres" };
    }
    data.name = name.trim();
  }

  const role = formData.get("role") as string;
  if (role !== null && role !== "") {
    if (!VALID_ROLES.includes(role as any)) {
      return { ok: false, error: `Rol inválido. Válidos: ${VALID_ROLES.join(", ")}` };
    }
    data.role = role;
  }

  const isActive = formData.get("is_active") as string;
  if (isActive !== null && isActive !== "") {
    data.is_active = isActive === "true";
  }

  const password = formData.get("password") as string;
  if (password !== null && password !== "") {
    if (password.length < 8) {
      return { ok: false, error: "La contraseña debe tener al menos 8 caracteres" };
    }
    data.password = password;
  }

  if (Object.keys(data).length === 0) {
    return { ok: false, error: "No hay cambios para guardar" };
  }

  try {
    const user = await apiFetch(`/admin-users/${id}`, {
      method: "PATCH",
      body: JSON.stringify(data),
    });
    revalidatePath("/usuarios");
    return { ok: true, user };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) };
  }
}

export async function deleteUser(id: string): Promise<UserActionResult> {
  try {
    await apiFetch(`/admin-users/${id}`, {
      method: "DELETE",
    });
    revalidatePath("/usuarios");
    return { ok: true };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) };
  }
}