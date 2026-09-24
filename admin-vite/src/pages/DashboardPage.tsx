"use client";

import { useEffect, useState } from "react";
import { RefreshButton } from "../components/RefreshButton";
import { backend } from "../api/client";
import { PageHeader } from "../components/PageHeader";
import { ErrorBanner } from "../components/ErrorBanner";
import { MetricCard } from "../components/MetricCard";
import { AttentionCard } from "../components/AttentionCard";

export function DashboardPage() {
  const [stats, setStats] = useState<{
    properties: number;
    leads: number;
    appointments: number;
  } | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      try {
        const [props, leads, appts] = await Promise.all([
          backend<{ count?: number; total?: number }>("/properties?limit=1"),
          backend<{ count?: number; total?: number }>("/leads?limit=1"),
          backend<{ count?: number; total?: number }>("/appointments?limit=1"),
        ]);
        setStats({
          properties: props.total ?? props.count ?? 0,
          leads: leads.total ?? leads.count ?? 0,
          appointments: appts.total ?? appts.count ?? 0,
        });
      } catch (e) {
        setError(e instanceof Error ? e.message : "Error cargando dashboard");
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  if (loading) {
    return (
      <>
        <PageHeader title="Panel general" description="Resumen del estado del negocio" />
        <div className="stat-row">
          <MetricCard title="Propiedades" value="—" />
          <MetricCard title="Leads" value="—" />
          <MetricCard title="Citas" value="—" />
        </div>
      </>
    );
  }

  if (error) {
    return (
      <>
        <PageHeader title="Panel general" description="Resumen del estado del negocio" />
        <ErrorBanner message={error} />
      </>
    );
  }

  return (
    <>
      <PageHeader
        title="Panel general"
        description="Resumen del estado del negocio"
        actions={<RefreshButton />}
      />

      <div className="stat-row">
        <MetricCard title="Propiedades" value={stats?.properties ?? 0} href="/propiedades" icon="building" tone="success" />
        <MetricCard title="Leads" value={stats?.leads ?? 0} href="/leads" icon="user-plus" tone="warn" />
        <MetricCard title="Citas" value={stats?.appointments ?? 0} href="/citas" icon="calendar" tone="success" />
      </div>

      <AttentionCard
        title="Requieren atención"
        items={[
          { label: "Propiedades sin imágenes", count: 0, href: "/propiedades" },
          { label: "Leads sin contacto", count: 0, href: "/leads" },
          { label: "Citas pendientes", count: 0, href: "/citas" },
        ]}
      />
    </>
  );
}