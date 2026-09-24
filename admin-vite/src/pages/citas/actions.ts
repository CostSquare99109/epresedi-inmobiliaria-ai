"use client";

import { backend } from "../../api/client";

const APPOINTMENT_STATUSES = ["REQUESTED", "CONFIRMED", "CANCELLED", "COMPLETED"] as const;

export type AppointmentActionResult =
  | { ok: true; appointment?: any }
  | { ok: false; error: string };

export async function createAppointment(
  formData: FormData
): Promise<AppointmentActionResult> {
  const property_id = formData.get("property_id") as string;
  const lead_id = formData.get("lead_id") as string || undefined;
  const scheduled_at = formData.get("scheduled_at") as string;
  const duration_minutes = parseInt(formData.get("duration_minutes") as string || "60", 10);
  const notes = formData.get("notes") as string || "";

  if (!property_id || !scheduled_at) {
    return { ok: false, error: "Propiedad y fecha/hora son obligatorios" };
  }

  try {
    const appointment = await backend("/appointments", {
      method: "POST",
      body: JSON.stringify({
        property_id,
        lead_id,
        scheduled_at,
        duration_minutes,
        notes,
      }),
    });
    return { ok: true, appointment };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) };
  }
}

export async function cancelAppointment(
  id: string
): Promise<AppointmentActionResult> {
  try {
    await backend(`/appointments/${id}`, {
      method: "DELETE",
    });
    return { ok: true };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) };
  }
}

export async function updateAppointment(
  id: string,
  formData: FormData
): Promise<AppointmentActionResult> {
  const data: Record<string, any> = {};
  
  const status = formData.get("status") as string;
  if (status && APPOINTMENT_STATUSES.includes(status as any)) {
    data.status = status;
  }
  
  const notes = formData.get("notes") as string;
  if (notes !== undefined) {
    data.notes = notes;
  }
  
  const scheduled_at = formData.get("scheduled_at") as string;
  if (scheduled_at) {
    data.scheduled_at = scheduled_at;
  }
  
  const duration_minutes = formData.get("duration_minutes") as string;
  if (duration_minutes) {
    data.duration_minutes = parseInt(duration_minutes, 10);
  }

  if (Object.keys(data).length === 0) {
    return { ok: false, error: "No hay cambios para guardar" };
  }

  try {
    const appointment = await backend(`/appointments/${id}`, {
      method: "PATCH",
      body: JSON.stringify(data),
    });
    return { ok: true, appointment };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) };
  }
}

export async function rescheduleAppointment(
  id: string,
  newScheduledAt: string,
  notes: string = ""
): Promise<AppointmentActionResult> {
  try {
    await backend(`/appointments/${id}`, {
      method: "DELETE",
    });
    
    const original = await backend<{ property_id: string; lead_id: string | null }>(`/appointments/${id}`);
    
    const appointment = await backend("/appointments", {
      method: "POST",
      body: JSON.stringify({
        property_id: original.property_id,
        lead_id: original.lead_id,
        scheduled_at: newScheduledAt,
        duration_minutes: 60,
        notes: notes || "Reprogramada",
      }),
    });
    
    return { ok: true, appointment };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) };
  }
}

export async function getPropertySlots(
  propertyId: string,
  days: number = 14
): Promise<{ ok: true; slots: any[] } | { ok: false; error: string }> {
  try {
    const res = await backend<{ slots: any[] }>(`/properties/${propertyId}/slots?days=${days}`);
    return { ok: true, slots: res.slots };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) };
  }
}