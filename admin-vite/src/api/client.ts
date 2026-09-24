/** Cliente HTTP del navegador hacia el backend FastAPI a través del proxy same-origin `/api`.

El JWT viaja como cookie httponly (`admin_access_token`) que el backend acepta
(`require_admin_user` lee el header Bearer o la cookie). El token nunca está
expuesto al JavaScript del navegador; el navegador lo adjunta automáticamente
a cada request same-origin y el proxy de Vite lo reenvía a FastAPI.
 */

export const PROXY = "/api";

/** Re-export de los DTOs compartidos para que las páginas importen tipos
 *  y cliente HTTP desde un único módulo (`../../api/client`). */
export type {
  AppointmentDTO,
  HealthDTO,
  LeadDTO,
  PropertyDTO,
  TimeInterval,
  VisitingHour,
} from "../lib/types";

export class ApiError extends Error {
  status: number;
  constructor(status: number, path: string, detail: string) {
    super(`API ${status} en ${path}: ${detail.slice(0, 200)}`);
    this.status = status;
    this.name = "ApiError";
  }
}

export async function backend<T>(path: string, init?: RequestInit): Promise<T> {
  // Los cuerpos JSON (string) deben viajar con `Content-Type: application/json`.
  // Sin esta cabecera el navegador envía `text/plain` y FastAPI no parsea el
  // cuerpo como JSON: el endpoint recibe un string en lugar de un objeto y
  // responde 422 (`model_attributes_type`). Solo se fija cuando el cuerpo es
  // un string y el llamador no definió ya un Content-Type (p. ej. FormData
  // gestiona su propio boundary y no debe tocarse).
  const headers = new Headers(init?.headers);
  if (typeof init?.body === "string" && init.body.length > 0 && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const res = await fetch(`${PROXY}${path}`, {
    ...init,
    headers,
    cache: "no-store",
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new ApiError(res.status, path, detail.slice(0, 200));
  }
  return (await res.json()) as T;
}