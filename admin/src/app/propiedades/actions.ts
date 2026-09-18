"use server";

import { revalidatePath } from "next/cache";
import { backend } from "@/lib/backend";

const VALID_STATUSES = ["AVAILABLE", "RESERVED", "SOLD", "INACTIVE"] as const;

export type PropertyActionResult =
  | { ok: true }
  | { ok: false; error: string };

/**
 * Server Action: actualiza el estado comercial de una propiedad.
 * El X-Admin-Token se inyecta server-side; nunca llega al navegador.
 */
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
  return { ok: true };
}
