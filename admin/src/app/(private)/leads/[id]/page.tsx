import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { backend, type LeadDTO } from "@/lib/backend";
import { PageHeader } from "@/components/PageHeader";
import { LeadDetail } from "./LeadDetail";

interface PageProps {
  params: Promise<{ id: string }>;
}

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { id } = await params;
  try {
    const lead = await backend<LeadDTO>(`/leads/${id}`);
    return { title: `${lead.name} (${lead.status})` };
  } catch {
    return { title: "Lead no encontrado" };
  }
}

export default async function LeadDetalle({ params }: PageProps) {
  const { id } = await params;
  let lead: LeadDTO | null = null;
  let error = "";

  try {
    lead = await backend<LeadDTO>(`/leads/${id}`);
  } catch (e) {
    error = e instanceof Error ? e.message : "Error cargando lead";
  }

  if (!lead) {
    notFound();
  }

  return (
    <>
      <PageHeader
        title={lead.name}
        description={`Lead ${lead.status} · ${lead.phone} · ${lead.budget ? `$${lead.budget.toLocaleString()}` : "Sin presupuesto"}`}
      />
      <LeadDetail lead={lead} error={error} />
    </>
  );
}