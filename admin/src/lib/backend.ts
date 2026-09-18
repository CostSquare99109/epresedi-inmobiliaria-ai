/** Server-side client for the internal API. Injects X-Admin-Token from env. */

export function adminHeaders(): HeadersInit {
  const token = process.env.ADMIN_TOKEN ?? "";
  return { "X-Admin-Token": token, "Content-Type": "application/json" };
}

export function apiBaseUrl(): string {
  return (process.env.API_BASE_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");
}

export async function backend<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${apiBaseUrl()}${path}`, {
    ...init,
    headers: { ...adminHeaders(), ...(init?.headers ?? {}) },
    cache: "no-store",
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(`API ${res.status} en ${path}: ${detail.slice(0, 200)}`);
  }
  return (await res.json()) as T;
}

export interface PropertyDTO {
  id: string;
  code: string;
  title: string;
  property_type: string;
  operation: string;
  price: number;
  currency: string;
  city: string;
  neighborhood: string;
  area_m2: number | null;
  bedrooms: number | null;
  bathrooms: number | null;
  parking_spaces: number | null;
  status: string;
  features: string[];
  project: string | null;
}

export interface DocumentDTO {
  id: string;
  title: string;
  filename: string;
  document_type: string;
  status: string;
  version: number;
  chunk_count: number;
  error: string;
  processed_at: string | null;
}

export interface LeadDTO {
  id: string;
  user_id: number;
  name: string;
  phone: string;
  status: string;
  budget: number | null;
  created_at: string;
}

export interface AppointmentDTO {
  id: string;
  property_id: string;
  lead_id: string | null;
  scheduled_at: string;
  status: string;
}

export interface AiEventDTO {
  id: number;
  request_id: string;
  user_id: number | null;
  intent: string;
  model: string;
  tools: { tool: string; ok: boolean }[];
  latency_ms: number;
  status: string;
  created_at: string;
}

export interface ConversationDTO {
  id: string;
  user_id: number;
  summary: string;
  recent: { role: string; content: string }[];
}

export interface HealthDTO {
  ok: boolean;
  checks: Record<string, boolean>;
  errors: Record<string, string>;
}
