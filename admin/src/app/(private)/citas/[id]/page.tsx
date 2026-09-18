import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { backend, type AppointmentDTO } from "@/lib/backend";
import { PageHeader } from "@/components/PageHeader";
import { CitaDetail } from "./CitaDetail";

interface PageProps {
  params: Promise<{ id: string }>;
}

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { id } = await params;
  try {
    const cita = await backend<AppointmentDTO>(`/appointments/${id}`);
    return { title: `Cita ${cita.id.slice(0, 8)}...` };
  } catch {
    return { title: "Cita no encontrada" };
  }
}

export default async function CitaDetalle({ params }: PageProps) {
  const { id } = await params;
  let cita: AppointmentDTO | null = null;
  let error = "";

  try {
    cita = await backend<AppointmentDTO>(`/appointments/${id}`);
  } catch (e) {
    error = e instanceof Error ? e.message : "Error cargando cita";
  }

  if (!cita) {
    notFound();
  }

  return (
    <>
      <PageHeader
        title="Detalle de cita"
        description={`Cita para propiedad ${cita.property_id} · ${new Date(cita.scheduled_at).toLocaleString()}`}
      />
      <CitaDetail cita={cita} error={error} />
    </>
  );
}