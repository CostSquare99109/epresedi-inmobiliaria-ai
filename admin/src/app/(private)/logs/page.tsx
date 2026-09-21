import type { Metadata } from "next";
import { backend, type AiEventDTO } from "@/lib/backend";
import { PageHeader } from "@/components/PageHeader";
import { StatusBadge } from "@/components/StatusBadge";
import { EmptyState } from "@/components/EmptyState";
import { ErrorBanner } from "@/components/ErrorBanner";
import { RefreshButton } from "@/components/RefreshButton";
import { FilterTabs } from "@/components/TableControls";
import { intentLabel } from "@/lib/status";
import { formatDateTime } from "@/lib/format";
import { singleParam } from "@/lib/params";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Logs IA" };

interface PageProps {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

export default async function Logs({ searchParams }: PageProps) {
  const sp = await searchParams;
  const estado = singleParam(sp.estado);
  const intento = singleParam(sp.intento);

  let events: AiEventDTO[] = [];
  let error = "";
  try {
    const body = await backend<{ events: AiEventDTO[] }>("/ai-events?limit=80");
    events = body.events;
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  const isOk = (e: AiEventDTO) => e.status.startsWith("ok");
  const okCount = events.filter(isOk).length;
  const failCount = events.length - okCount;
  const avgLatency = events.length
    ? Math.round(events.reduce((acc, e) => acc + e.latency_ms, 0) / events.length)
    : 0;

  const intents = [...new Set(events.map((e) => e.intent))].map((i) => ({
    value: i,
    label: intentLabel(i),
    count: events.filter((e) => e.intent === i).length,
  }));
  intents.sort((a, b) => b.count - a.count || a.label.localeCompare(b.label));

  let visible = events;
  if (estado === "ok") visible = visible.filter(isOk);
  else if (estado === "error") visible = visible.filter((e) => !isOk(e));
  if (intento) visible = visible.filter((e) => e.intent === intento);

  return (
    <>
      <PageHeader
        title="Logs IA"
        description="Auditoría del orquestador: cada evento permite reconstruir intención → herramientas → latencia de la respuesta."
        actions={<RefreshButton />}
      />

      {error && <ErrorBanner message={error} />}

      {!error && (
        <section className="card" aria-label="Auditoría de eventos de IA">
          <div className="card-head">
            <div className="toolbar">
              <div className="toolbar-filters">
                <FilterTabs
                  basePath="/logs"
                  params={intento ? { intento } : {}}
                  paramName="estado"
                  current={estado}
                  options={[
                    { value: "", label: "Todos", count: events.length },
                    { value: "ok", label: "Exitosos", count: okCount },
                    { value: "error", label: "Con error", count: failCount },
                  ]}
                  ariaLabel="Filtrar por resultado"
                />
                <form method="get" action="/logs" role="search">
                  {estado && <input type="hidden" name="estado" value={estado} />}
                  <select
                    name="intento"
                    defaultValue={intento}
                    aria-label="Filtrar por intención"
                  >
                    <option value="">Todas las intenciones</option>
                    {intents.map((i) => (
                      <option key={i.value} value={i.value}>
                        {i.label} ({i.count})
                      </option>
                    ))}
                  </select>
                  <button type="submit" className="btn btn-secondary">
                    Filtrar
                  </button>
                </form>
              </div>
              <span className="toolbar-meta">
                Latencia media {avgLatency} ms · {visible.length} evento{visible.length === 1 ? "" : "s"}
              </span>
            </div>
          </div>

          {visible.length === 0 ? (
            <EmptyState
              bordered
              icon="list"
              title="Sin eventos que coincidan"
              description="No hay eventos de IA con los filtros aplicados. Cada interacción del asistente genera un evento auditable aquí."
              action={
                estado || intento ? (
                  <a href="/logs" className="btn btn-secondary">
                    Quitar filtros
                  </a>
                ) : undefined
              }
            />
          ) : (
            <div className="table-wrap">
              <table>
                <caption className="visually-hidden">
                  Eventos del orquestador con fecha, intención, herramientas y latencia
                </caption>
                <thead>
                  <tr>
                    <th>Fecha</th>
                    <th>Intención</th>
                    <th className="table-responsive-hide-xs">Modelo</th>
                    <th className="table-responsive-hide-sm">Herramientas</th>
                    <th className="num table-responsive-hide-xs">Latencia</th>
                    <th>Estado</th>
                  </tr>
                </thead>
                <tbody>
                  {visible.map((e) => (
                    <tr key={e.id}>
                      <td>
                        {formatDateTime(e.created_at)}
                        <div className="cell-sub">usuario {e.user_id ?? "—"}</div>
                      </td>
                      <td>
                        <div className="cell-main">{intentLabel(e.intent)}</div>
                      </td>
                      <td className="muted table-responsive-hide-xs">{e.model}</td>
                      <td className="muted table-responsive-hide-sm">
                        {e.tools.map((t) => t.tool).join(", ") || "—"}
                      </td>
                      <td className="num table-responsive-hide-xs">{e.latency_ms} ms</td>
                      <td>
                        <StatusBadge status={e.status.startsWith("ok") ? "ok" : "ERROR"} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}
    </>
  );
}
