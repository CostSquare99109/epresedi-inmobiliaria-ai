import Link from "next/link";
import {
  backend,
  type AiEventDTO,
  type AppointmentDTO,
  type DocumentDTO,
  type HealthDTO,
  type LeadDTO,
  type PropertyDTO,
} from "@/lib/backend";
import { PageHeader } from "@/components/PageHeader";
import { StatusBadge } from "@/components/StatusBadge";
import { EmptyState } from "@/components/EmptyState";
import { ErrorBanner } from "@/components/ErrorBanner";
import { RefreshButton } from "@/components/RefreshButton";
import { MetricCard } from "@/components/MetricCard";
import { SectionHeader } from "@/components/SectionHeader";
import { AttentionCard, type AttentionItem } from "@/components/AttentionCard";
import { Icon, type IconName } from "@/components/icons";
import { intentLabel, statusMeta, INVENTORY_ORDER } from "@/lib/status";
import { formatDateTime, formatMoney, timeAgo } from "@/lib/format";

export const dynamic = "force-dynamic";

const BAR_COLORS: Record<string, string> = {
  AVAILABLE: "var(--success)",
  RESERVED: "var(--warn)",
  SOLD: "var(--neutral)",
  INACTIVE: "var(--idle)",
};

/** Umbral explícito: lead NEW sin gestión durante 3 días. */
const STALE_LEAD_HOURS = 72;

function intentIcon(intent: string): IconName {
  if (intent.includes("VISIT") || intent.includes("APPOINTMENT")) return "calendar";
  if (intent.includes("PROPERTY") || intent.includes("SEARCH") || intent.includes("COMPARE")) {
    return "building";
  }
  if (intent.includes("DOCUMENT")) return "file";
  return "chat";
}

async function settle<T>(path: string): Promise<T | null> {
  try {
    return await backend<T>(path);
  } catch {
    return null;
  }
}

function plural(n: number, one: string, many: string): string {
  return n === 1 ? one : many;
}

export default async function Dashboard() {
  const [health, propsRes, docsRes, leadsRes, apptsRes, eventsRes] = await Promise.all([
    settle<HealthDTO>("/health/ready"),
    settle<{ properties: PropertyDTO[] }>("/properties?limit=200"),
    settle<{ documents: DocumentDTO[] }>("/documents"),
    settle<{ leads: LeadDTO[] }>("/leads"),
    settle<{ appointments: AppointmentDTO[] }>("/appointments"),
    settle<{ events: AiEventDTO[] }>("/ai-events?limit=8"),
  ]);

  const props = propsRes?.properties ?? [];
  const docs = docsRes?.documents ?? [];
  const leads = [...(leadsRes?.leads ?? [])].sort((a, b) =>
    b.created_at.localeCompare(a.created_at),
  );
  const appts = apptsRes?.appointments ?? [];
  const events = eventsRes?.events ?? [];
  const leadById = new Map(leads.map((l) => [l.id, l]));
  const propById = new Map(props.map((p) => [p.id, p]));

  const byStatus = props.reduce<Record<string, number>>((acc, p) => {
    acc[p.status] = (acc[p.status] ?? 0) + 1;
    return acc;
  }, {});
  const now = Date.now();
  const upcoming = appts
    .filter((a) => new Date(a.scheduled_at).getTime() >= now)
    .sort((a, b) => a.scheduled_at.localeCompare(b.scheduled_at));
  const unconfirmed = upcoming.filter((a) => a.status === "REQUESTED");
  const newLeads = leads.filter((l) => l.status === "NEW");
  const staleNewLeads = newLeads.filter(
    (l) => now - new Date(l.created_at).getTime() > STALE_LEAD_HOURS * 3_600_000,
  );
  const failedDocs = docs.filter((d) => d.status === "FAILED" || d.status === "ERROR");
  const readyDocs = docs.filter((d) => d.status === "READY").length;
  const busyDocs = docs.length - readyDocs - failedDocs.length;
  const systemOk = health ? Object.values(health.checks).every(Boolean) : false;
  const avgLatency = events.length
    ? Math.round(events.reduce((acc, e) => acc + e.latency_ms, 0) / events.length)
    : 0;
  const systemOffline = propsRes === null;

  // Portadas reales para las propiedades destacadas (solo 4, en paralelo).
  const available = props.filter((p) => p.status === "AVAILABLE");
  const featured = [...available, ...props.filter((p) => p.status !== "AVAILABLE")].slice(0, 4);
  const covers = await Promise.all(
    featured.map(async (p) => {
      try {
        const r = await backend<{ images: string[] }>(`/properties/${p.id}/images`);
        return r.images[0] ?? null;
      } catch {
        return null;
      }
    }),
  );

  const attention: AttentionItem[] = [];
  if (health === null) {
    attention.push({
      tone: "danger",
      label: "Sin respuesta del backend",
      detail: "verifica que python main.py esté corriendo",
      href: "/",
    });
  } else if (!systemOk) {
    const failed = Object.entries(health.checks).filter(([, v]) => !v).map(([k]) => k);
    attention.push({
      tone: "danger",
      label: "Sistema degradado",
      detail: failed.join(", "),
      href: "/",
    });
  }
  if (failedDocs.length > 0) {
    attention.push({
      tone: "danger",
      label: `${failedDocs.length} ${plural(failedDocs.length, "documento", "documentos")} con error de indexación`,
      detail: "reprocesa o elimina desde Documentos · RAG",
      href: "/documentos",
      count: failedDocs.length,
    });
  }
  if (staleNewLeads.length > 0) {
    attention.push({
      tone: "warn",
      label: `${staleNewLeads.length} ${plural(staleNewLeads.length, "lead nuevo", "leads nuevos")} sin contactar (más de 72 h)`,
      detail: "gestiona los prospectos desde Leads",
      href: "/leads?estado=NEW",
      count: newLeads.length,
    });
  }
  if (unconfirmed.length > 0) {
    attention.push({
      tone: "warn",
      label: `${unconfirmed.length} ${plural(unconfirmed.length, "cita", "citas")} sin confirmar`,
      detail: "confirma o cancela desde Citas",
      href: "/citas?estado=REQUESTED",
      count: unconfirmed.length,
    });
  }
  if (propsRes !== null && props.length === 0) {
    attention.push({
      tone: "warn",
      label: "El inventario está vacío",
      detail: "carga el inventario desde la API de administración",
      href: "/propiedades",
    });
  }

  return (
    <>
      <PageHeader
        title="Panel general"
        description="Estado de la operación inmobiliaria: inventario, actividad comercial del asistente y seguimiento de contenido."
        actions={<RefreshButton />}
      />

      {attention.length > 0 ? (
        <AttentionCard items={attention} />
      ) : (
        <div className="quiet-ok">
          <Icon name="check" size={15} />
          Todo al día: sin pendientes que requieran tu acción.
        </div>
      )}

      <div className="stat-row section-gap">
        <MetricCard
          label="Propiedades disponibles"
          value={byStatus.AVAILABLE ?? 0}
          href="/propiedades?estado=AVAILABLE"
          hint="Ver inventario"
        />
        <MetricCard
          label="Reservadas"
          value={byStatus.RESERVED ?? 0}
          tone="warn"
          href="/propiedades?estado=RESERVED"
        />
        <MetricCard
          label="Leads registrados"
          value={leads.length}
          href="/leads"
          hint={newLeads.length > 0 ? `${newLeads.length} sin contactar` : undefined}
        />
        <MetricCard
          label="Citas próximas"
          value={upcoming.length}
          href="/citas"
          hint={unconfirmed.length > 0 ? `${unconfirmed.length} sin confirmar` : undefined}
        />
      </div>

      <div className="grid-2 section-gap">
        <section className="card" aria-label="Inventario de propiedades">
          <SectionHeader
            title="Inventario"
            sub="Distribución del inventario por estado"
            link={{ href: "/propiedades", label: "Ver propiedades" }}
          />
          <div className="card-body">
            {systemOffline ? (
              <ErrorBanner
                title="Inventario no disponible"
                message="No se pudo consultar /properties. El resto del panel sigue funcionando."
              />
            ) : props.length === 0 ? (
              <EmptyState
                icon="building"
                title="Sin propiedades registradas"
                description="El inventario está vacío. Carga las propiedades desde la API de administración y aparecerán aquí automáticamente."
                action={
                  <Link href="/propiedades" className="btn btn-secondary">
                    Ir a Propiedades
                  </Link>
                }
              />
            ) : (
              <>
                <div className="mini-stats">
                  {INVENTORY_ORDER.map((s) => (
                    <div className={`mini-stat tone-${statusMeta(s).tone}`} key={s}>
                      <div className="ms-v">{byStatus[s] ?? 0}</div>
                      <div className="ms-l">{statusMeta(s).label}</div>
                    </div>
                  ))}
                </div>
                <div
                  className="dist-bar"
                  role="img"
                  aria-label={`Distribución: ${INVENTORY_ORDER.map((s) => `${byStatus[s] ?? 0} ${statusMeta(s).label.toLowerCase()}`).join(", ")}`}
                >
                  {INVENTORY_ORDER.map((s) => {
                    const n = byStatus[s] ?? 0;
                    if (!n) return null;
                    return (
                      <span
                        key={s}
                        style={{
                          width: `${(n / props.length) * 100}%`,
                          background: BAR_COLORS[s],
                        }}
                      />
                    );
                  })}
                </div>
                <div className="dist-legend">
                  {INVENTORY_ORDER.map((s) => (
                    <span className="dist-item" key={s}>
                      <span className={`dot dot-${statusMeta(s).tone}`} aria-hidden="true" />
                      {statusMeta(s).label}
                      <b>{byStatus[s] ?? 0}</b>
                    </span>
                  ))}
                </div>
              </>
            )}
          </div>
        </section>

        <section className="card" aria-label="Actividad reciente del asistente">
          <SectionHeader
            title="Actividad del asistente"
            sub={events.length > 0 ? `Últimas interacciones · latencia media ${avgLatency} ms` : "Últimas interacciones"}
            link={{ href: "/logs", label: "Ver logs" }}
          />
          <div className="card-body">
            {eventsRes === null ? (
              <ErrorBanner message="No se pudo consultar /ai-events." />
            ) : events.length === 0 ? (
              <EmptyState
                icon="list"
                title="Sin actividad todavía"
                description="Cuando los usuarios conversen con el asistente, cada interacción aparecerá aquí con su intención y resultado."
              />
            ) : (
              <div className="feed">
                {events.map((e) => {
                  const ok = e.status.startsWith("ok");
                  return (
                    <div className="feed-row" key={e.id}>
                      <span
                        className={`feed-icon ${ok ? "tone-success" : "tone-danger"}`}
                        aria-hidden="true"
                      >
                        <Icon name={intentIcon(e.intent)} size={14} />
                      </span>
                      <div className="feed-main">
                        <div className="feed-title">{intentLabel(e.intent)}</div>
                        <div className="feed-sub">
                          {e.latency_ms} ms · usuario {e.user_id ?? "—"}
                        </div>
                      </div>
                      <div className="feed-meta">
                        <span className="feed-time">{timeAgo(e.created_at)}</span>
                        <StatusBadge status={ok ? "ok" : "ERROR"} />
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </section>
      </div>

      {!systemOffline && featured.length > 0 && (
        <section className="card section-gap" aria-label="Propiedades publicadas recientemente">
          <SectionHeader
            title="Publicadas recientemente"
            sub="Últimas propiedades incorporadas al inventario"
            link={{ href: "/propiedades", label: "Ver todas" }}
          />
          <div className="prop-grid">
            {featured.map((p, i) => (
              <Link className="prop-card" href="/propiedades" key={p.id}>
                <div className="prop-cover">
                  {covers[i] ? (
                    <img
                      src={`/api/proxy/properties/${p.id}/images/${covers[i]}`}
                      alt={`Foto de ${p.title}`}
                      width={380}
                      height={285}
                      loading="lazy"
                      decoding="async"
                    />
                  ) : (
                    <span className="prop-cover-fallback">
                      <Icon name="building" size={22} />
                    </span>
                  )}
                  <span className="prop-price">{formatMoney(p.price, p.currency)}</span>
                </div>
                <div className="prop-body">
                  <div className="prop-title">{p.title}</div>
                  <div className="prop-meta">
                    {p.property_type} · {p.city}
                  </div>
                  <span className="prop-status">
                    <StatusBadge status={p.status} />
                  </span>
                </div>
              </Link>
            ))}
          </div>
        </section>
      )}

      <div className="grid-2 section-gap">
        <section className="card" aria-label="Próximas citas">
          <SectionHeader
            title="Próximas citas"
            sub="Visitas programadas con clientes"
            link={{ href: "/citas", label: "Ver citas" }}
          />
          <div className="card-body">
            {apptsRes === null ? (
              <ErrorBanner message="No se pudo consultar /appointments." />
            ) : upcoming.length === 0 ? (
              <EmptyState
                icon="calendar"
                title="Sin citas próximas"
                description="Las visitas que los clientes agenden a través del asistente aparecerán aquí."
              />
            ) : (
              <div className="feed">
                {upcoming.slice(0, 5).map((a) => {
                  const prop = propById.get(a.property_id);
                  const lead = a.lead_id ? leadById.get(a.lead_id) : undefined;
                  return (
                    <div className="feed-row" key={a.id}>
                      <span className="feed-icon" aria-hidden="true">
                        <Icon name="calendar" size={14} />
                      </span>
                      <div className="feed-main">
                        <div className="feed-title">
                          {prop ? prop.title : `Propiedad ${a.property_id.slice(0, 8)}…`}
                        </div>
                        <div className="feed-sub">
                          {formatDateTime(a.scheduled_at)}
                          {lead
                            ? ` · ${lead.name || "Cliente"}${lead.phone ? `, ${lead.phone}` : ""}`
                            : ""}
                        </div>
                      </div>
                      <div className="feed-meta">
                        <StatusBadge status={a.status} />
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </section>

        <section className="card" aria-label="Leads recientes">
          <SectionHeader
            title="Leads recientes"
            sub="Prospectos captados por el asistente"
            link={{ href: "/leads", label: "Ver leads" }}
          />
          <div className="card-body">
            {leadsRes === null ? (
              <ErrorBanner message="No se pudo consultar /leads." />
            ) : leads.length === 0 ? (
              <EmptyState
                icon="user-plus"
                title="Sin leads todavía"
                description="Cuando un usuario deje su contacto durante una conversación, el prospecto aparecerá aquí."
              />
            ) : (
              <div className="feed">
                {leads.slice(0, 4).map((l) => (
                  <div className="feed-row" key={l.id}>
                    <span className="feed-icon" aria-hidden="true">
                      <Icon name="user-plus" size={14} />
                    </span>
                    <div className="feed-main">
                      <div className="feed-title">{l.name || "Sin nombre"}</div>
                      <div className="feed-sub">
                        {timeAgo(l.created_at)}
                        {l.budget ? ` · presupuesto ${formatMoney(l.budget, "COP")}` : ""}
                        {l.phone ? ` · ${l.phone}` : ""}
                      </div>
                    </div>
                    <div className="feed-meta">
                      {l.phone && (
                        <a
                          className="call-link"
                          href={`tel:${l.phone}`}
                          aria-label={`Llamar a ${l.name || "este lead"} al ${l.phone}`}
                        >
                          <Icon name="phone" size={13} />
                        </a>
                      )}
                      <StatusBadge status={l.status} />
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </section>
      </div>

      <div className="grid-2 section-gap">
        <section className="card" aria-label="Documentos y RAG">
          <SectionHeader
            title="Documentos · RAG"
            sub="Base de conocimiento indexada del asistente"
            link={{ href: "/documentos", label: "Gestionar" }}
          />
          <div className="card-body">
            {docsRes === null ? (
              <ErrorBanner message="No se pudo consultar /documents." />
            ) : docs.length === 0 ? (
              <EmptyState
                icon="file"
                title="Sin documentos indexados"
                description="Sube manuales, fichas o normativas para que el asistente pueda responder con base real."
                action={
                  <Link href="/documentos" className="btn btn-secondary">
                    Subir documento
                  </Link>
                }
              />
            ) : (
              <>
                <div className="mini-stats">
                  <div className="mini-stat">
                    <div className="ms-v">{docs.length}</div>
                    <div className="ms-l">Documentos</div>
                  </div>
                  <div className="mini-stat tone-success">
                    <div className="ms-v">{readyDocs}</div>
                    <div className="ms-l">Listos</div>
                  </div>
                  <div className="mini-stat tone-warn">
                    <div className="ms-v">{busyDocs}</div>
                    <div className="ms-l">En proceso</div>
                  </div>
                  {failedDocs.length > 0 && (
                    <div className="mini-stat tone-danger">
                      <div className="ms-v">{failedDocs.length}</div>
                      <div className="ms-l">Con error</div>
                    </div>
                  )}
                </div>
                {failedDocs.length > 0 && (
                  <div className="feed">
                    {failedDocs.slice(0, 3).map((d) => (
                      <div className="feed-row" key={d.id}>
                        <span className="feed-icon tone-danger" aria-hidden="true">
                          <Icon name="alert" size={14} />
                        </span>
                        <div className="feed-main">
                          <div className="feed-title">{d.title}</div>
                          <div className="feed-sub">
                            {d.error ? d.error.slice(0, 90) : "Error de procesamiento"}
                          </div>
                        </div>
                        <div className="feed-meta">
                          <StatusBadge status={d.status} />
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </>
            )}
          </div>
        </section>

        <section className="card" aria-label="Salud del sistema">
          <SectionHeader
            title="Salud del sistema"
            sub="Comprobaciones del backend local"
          />
          <div className="card-body tight">
            {health === null ? (
              <ErrorBanner
                title="Sin respuesta del backend"
                message="No se pudo contactar /health/ready. Verifica que el backend esté corriendo (python main.py) y que ADMIN_TOKEN coincida."
              />
            ) : (
              <>
                <div className="chips-row">
                  <span className={`badge tone-${systemOk ? "success" : "danger"}`}>
                    <span className="badge-dot" aria-hidden="true" />
                    {systemOk ? "Sistema operativo" : "Sistema degradado"}
                  </span>
                  {Object.entries(health.checks).map(([k, v]) => (
                    <span className="chip" key={k}>
                      <span
                        className={`dot dot-${v ? "success" : "danger"}`}
                        aria-hidden="true"
                      />
                      {k}
                      <b>{v ? "OK" : "ERROR"}</b>
                    </span>
                  ))}
                </div>
                {Object.keys(health.errors).length > 0 && (
                  <p
                    className="error-banner-msg"
                    role="alert"
                    style={{ marginTop: "var(--sp-3)" }}
                  >
                    {Object.entries(health.errors)
                      .map(([k, v]) => `${k}: ${v}`)
                      .join(" · ")}
                  </p>
                )}
              </>
            )}
          </div>
        </section>
      </div>
    </>
  );
}
