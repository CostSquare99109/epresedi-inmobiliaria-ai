"use server";

import { cookies } from "next/headers";
import { revalidatePath } from "next/cache";
import { NextResponse } from "next/server";

export async function logoutAction(): Promise<{ ok: true } | { ok: false; error: string }> {
  try {
    const cookieStore = await cookies();
    const accessToken = cookieStore.get("admin_access_token")?.value;
    const refreshToken = cookieStore.get("admin_refresh_token")?.value;

    if (accessToken) {
      const res = await fetch(`${process.env.API_BASE_URL ?? "http://127.0.0.1:8000"}/auth/logout`, {
        method: "POST",
        headers: { "Authorization": `Bearer ${accessToken}` },
      });
      if (!res.ok) {
        console.warn("Backend logout failed:", await res.text());
      }
    }

    const response = NextResponse.json({ ok: true });
    response.cookies.set("admin_access_token", "", { path: "/", maxAge: 0 });
    response.cookies.set("admin_refresh_token", "", { path: "/", maxAge: 0 });
    
    revalidatePath("/");
    return { ok: true };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) };
  }
}

export async function getCurrentUser(): Promise<{ ok: true; user: any } | { ok: false; error: string }> {
  try {
    const cookieStore = await cookies();
    const accessToken = cookieStore.get("admin_access_token")?.value;
    
    if (!accessToken) {
      return { ok: false, error: "No autenticado" };
    }

    const res = await fetch(`${process.env.API_BASE_URL ?? "http://127.0.0.1:8000"}/auth/me`, {
      headers: { "Authorization": `Bearer ${accessToken}` },
    });

    if (!res.ok) {
      return { ok: false, error: "Token inválido" };
    }

    const data = await res.json();
    return { ok: true, user: data.user };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) };
  }
}