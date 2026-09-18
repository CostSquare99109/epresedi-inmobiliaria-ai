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

export type SettingsActionResult =
  | { ok: true; updated: string[] }
  | { ok: false; error: string };

export async function updateSettings(
  settings: Record<string, any>
): Promise<SettingsActionResult> {
  try {
    const result = await apiFetch<{ updated: string[] }>("/settings", {
      method: "PUT",
      body: JSON.stringify({ settings }),
    });
    revalidatePath("/ajustes");
    return { ok: true, updated: result.updated };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) };
  }
}