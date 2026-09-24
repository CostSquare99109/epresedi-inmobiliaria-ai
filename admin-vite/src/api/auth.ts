/** Autenticación del panel (mismo flujo que el panel Next.js).

LOGIN  → POST /auth/login (vía proxy) → el backend responde 200 con el JWT y
         setea las cookies httponly `admin_access_token` + `admin_refresh_token`
         (samesite=lax, secure solo en producción).
SESIÓN → GET /auth/me con la cookie → user + permisos.
EXPIRA → 401 → la capa de rutas protegidas redirige a /login?redirect=…
LOGOUT → POST /auth/logout → el backend borra las cookies y audita la acción.
 */

import { backend, PROXY } from "./client";

export interface CurrentUser {
  id: string;
  email: string;
  name: string;
  role: string;
  is_active: boolean;
}

export interface LoginResult {
  ok: boolean;
  detail?: string;
}

export async function login(email: string, password: string): Promise<LoginResult> {
  const res = await fetch(`${PROXY}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  const data = (await res.json().catch(() => ({}))) as { detail?: string };
  if (!res.ok) {
    return { ok: false, detail: data.detail || "Credenciales inválidas" };
  }
  return { ok: true };
}

export async function logout(): Promise<void> {
  // El backend revoca la sesión, audita la acción y borra las cookies httponly.
  // Si el token ya expiró la llamada responde 401 sin tocar cookies; la capa de
  // rutas protegidas enviará igualmente al usuario a /login en el próximo /me.
  await fetch(`${PROXY}/auth/logout`, { method: "POST", cache: "no-store" }).catch(() => undefined);
}

export async function getCurrentUser(): Promise<{ ok: true; user: CurrentUser } | { ok: false; error: string }> {
  try {
    const data = await backend<{ user: CurrentUser }>("/auth/me");
    return { ok: true, user: data.user };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : "No autenticado" };
  }
}