/** Server-side client for the internal API. Uses JWT from cookies (Server Actions) or service token fallback. */

import { cookies } from "next/headers";
import type {
  PropertyDTO,
  DocumentDTO,
  LeadDTO,
  AppointmentDTO,
  AiEventDTO,
  ConversationDTO,
  HealthDTO,
  ProjectDTO,
  AdminUserDTO,
  AuditLogDTO,
  CmsContentDTO,
  SystemSettingDTO,
} from "./types";

export type {
  PropertyDTO,
  DocumentDTO,
  LeadDTO,
  AppointmentDTO,
  AiEventDTO,
  ConversationDTO,
  HealthDTO,
  ProjectDTO,
  AdminUserDTO,
  AuditLogDTO,
  CmsContentDTO,
  SystemSettingDTO,
};

export function apiBaseUrl(): string {
  return (process.env.API_BASE_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");
}

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

export async function backend<T>(path: string, init?: RequestInit): Promise<T> {
  const authHeaders = await getAuthHeaders();
  const res = await fetch(`${apiBaseUrl()}${path}`, {
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