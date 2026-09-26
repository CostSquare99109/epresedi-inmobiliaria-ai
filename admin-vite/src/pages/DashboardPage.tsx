"use client";

import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { RefreshButton } from "../components/RefreshButton";
import { backend } from "../api/client";
import { PageHeader } from "../components/PageHeader";
import { ErrorBanner } from "../components/ErrorBanner";
import { MetricCard } from "../components/MetricCard";
import { Icon, type IconName } from "../components/icons";
import type { DashboardStatsDTO } from "../lib/types";
import { statusMeta } from "../lib/status";

interface DashboardState {
  stats: DashboardStatsDTO | null;
  error: string;
  loading: boolean;
}

export function DashboardPage() {
  const [state, setState] = useState<DashboardState>({
    stats: null,
    error: "",
    loading: true,
  });

  useEffect(() => {
    let mounted = true;
    async function load() {
      try {
        const data = await backend<DashboardStatsDTO>("/dashboard/stats");
        if (mounted) setState({ stats: data, error: "", loading: false });
      } catch (e) {
        if (mounted) setState({ stats: null, error: e instanceof Error ? e.message : "Error cargando dashboard", loading: false });
      }
    }
    load();
    return () => { mounted = false; };
  }, []);

  if (state.loading) {
    return (
      <>
        <PageHeader title="Panel General" description="Resumen del estado actual de Epresedi" />
        <DashboardSkeleton />
      </>
    );
  }

  if (state.error) {
    return (
      <>
        <PageHeader title="Panel General" description="Resumen del estado actual de Epresedi" />
        <ErrorBanner message={state.error} />
      </>
    );
  }

  const stats = state.stats!;
  const props = stats.properties;
  const leads = stats.leads;
  const appts = stats.appointments;
  const conversations = stats.conversations;

  // Property status mapping with display labels and tones
  const propertyStatuses: Array<{ key: string; label: string; tone: "success" | "warn" | "danger" | "neutral" | "info" }> = [
    { key: "AVAILABLE", label: "Disponibles", tone: "success" },
    { key: "RESERVED", label: "Reservadas", tone: "warn" },
    { key: "SOLD", label: "Vendidas", tone: "neutral" },
    { key: "INACTIVE", label: "Inactivas", tone: "danger" },
  ];

  // Operations mapping
  const operations: Array<{ key: string; label: string; icon: IconName; tone: "success" | "warn" | "danger" | "neutral" | "info" }> = [
    { key: "SALE", label: "Venta", icon: "shopping-bag", tone: "success" },
    { key: "RENT", label: "Arriendo", icon: "home", tone: "info" },
  ];

  // Property types mapping (tonos fijos para paridad con Estado de propiedades)
  const propertyTypes: Array<{ key: string; label: string; tone: "success" | "warn" | "danger" | "neutral" | "info" }> = [
    { key: "casa", label: "Casa", tone: "info" },
    { key: "apartamento", label: "Apartamento", tone: "warn" },
  ];

  const TONE_VAR: Record<string, string> = {
    success: "var(--success)",
    warn: "var(--warn)",
    danger: "var(--danger)",
    neutral: "var(--neutral)",
    info: "var(--info)",
  };

  // Etiqueta humana de la propiedad de una cita: nunca exponer el UUID.
  // Prioridad: título > dirección > código > fallback genérico.
  const propertyLabel = (appt: { property_title?: string | null; property_address?: string | null; property_code?: string | null }) =>
    appt.property_title?.trim() ||
    appt.property_address?.trim() ||
    (appt.property_code ? `Propiedad ${appt.property_code}` : "Propiedad sin información");

  

  // Format date for display
  const formatDateTime = (iso: string) => {
    const date = new Date(iso);
    return date.toLocaleString("es-CO", {
      weekday: "short",
      day: "2-digit",
      month: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hour12: true,
    });
  };

  return (
    <>
      <PageHeader
        title="Panel General"
        description="Resumen del estado actual de Epresedi"
        actions={<RefreshButton />}
      />

      {/* ===== BLOQUE 1: RESUMEN PRINCIPAL ===== */}
      <section className="section-gap">
        <div className="card">
          <div className="card-head">
            <div>
              <h2 className="card-title">Resumen ejecutivo</h2>
              <p className="card-sub">Métricas clave del negocio inmobiliario</p>
            </div>
          </div>
          <div className="card-body">
            <div className="stat-row">
              <MetricCard
                title="Propiedades"
                value={props.total}
                to="/propiedades"
                icon="building"
                tone="success"
                hint={props.by_status.AVAILABLE ? `${props.by_status.AVAILABLE} disponibles` : undefined}
              />
              <MetricCard
                title="Leads"
                value={leads.total}
                to="/leads"
                icon="user-plus"
                tone="warn"
                hint={leads.by_status.NEW ? `${leads.by_status.NEW} nuevos` : undefined}
              />
              <MetricCard
                title="Citas"
                value={appts.total}
                to="/citas"
                icon="calendar"
                tone="success"
                hint={appts.by_status.CONFIRMED ? `${appts.by_status.CONFIRMED} confirmadas` : undefined}
              />
              <MetricCard
                title="Conversaciones"
                value={conversations.total}
                to="/conversaciones"
                icon="message-square"
                tone="neutral"
                hint={conversations.recent.length > 0 ? `${conversations.recent.length} recientes` : undefined}
              />
            </div>
          </div>
        </div>
      </section>

      {/* ===== BLOQUE 2: ESTADO DE PROPIEDADES ===== */}
      <section className="section-gap">
        <div className="card">
          <div className="card-head">
            <div>
              <h2 className="card-title">Estado de propiedades</h2>
              <p className="card-sub">Distribución del inventario por estado comercial</p>
            </div>
            <Link className="card-link" to="/propiedades">Ver todas →</Link>
          </div>
          <div className="card-body">
            <div className="mini-stats">
              {propertyStatuses.map((status) => {
                const count = props.by_status[status.key] ?? 0;
                const percentage = props.total > 0 ? Math.round((count / props.total) * 100) : 0;
                return (
                  <div key={status.key} className={`mini-stat tone-${status.tone}`}>
                    <span className="ms-v">{count}</span>
                    <span className="ms-l">{status.label} <span className="muted">({percentage}%)</span></span>
                  </div>
                );
              })}
            </div>
            <div className="dist-bar" role="img" aria-label="Distribución de propiedades por estado">
              {propertyStatuses.map((status) => {
                const count = props.by_status[status.key] ?? 0;
                const percentage = props.total > 0 ? (count / props.total) * 100 : 0;
                const tones: Record<string, string> = {
                  success: "var(--success)",
                  warn: "var(--warn)",
                  danger: "var(--danger)",
                  neutral: "var(--neutral)",
                  info: "var(--info)",
                };
                return (
                  <span
                    key={status.key}
                    style={{ width: `${percentage}%`, background: tones[status.tone] }}
                    title={`${status.label}: ${count} (${percentage.toFixed(1)}%)`}
                  />
                );
              })}
            </div>
            <div className="dist-legend">
              {propertyStatuses.map((status) => {
                const count = props.by_status[status.key] ?? 0;
                const tones: Record<string, string> = {
                  success: "var(--success)",
                  warn: "var(--warn)",
                  danger: "var(--danger)",
                  neutral: "var(--neutral)",
                  info: "var(--info)",
                };
                return (
                  <div key={status.key} className="dist-item">
                    <span className="dot" style={{ background: tones[status.tone] }} />
                    <span>{status.label} <b>{count}</b></span>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      </section>

      {/* ===== BLOQUE 3: OPERACIONES (VENTA vs ARRIENDO) ===== */}
      <section className="section-gap">
        <div className="card">
          <div className="card-head">
            <div>
              <h2 className="card-title">Operaciones</h2>
              <p className="card-sub">Propiedades por modalidad comercial</p>
            </div>
            <Link className="card-link" to="/propiedades">Ver inventario →</Link>
          </div>
          <div className="card-body">
            <div className="grid-2">
              {operations.map((op) => {
                const count = props.by_operation[op.key] ?? 0;
                const percentage = props.total > 0 ? Math.round((count / props.total) * 100) : 0;
                return (
                  <Link key={op.key} to="/propiedades" className="card" style={{ textDecoration: "none", color: "inherit" }}>
                    <div className="card-body tight">
                      <div style={{ display: "flex", alignItems: "center", gap: "var(--sp-3)" }}>
                        <div className={`feed-icon tone-${op.tone}`} style={{ width: 48, height: 48 }}>
                          <Icon name={op.icon} size={24} />
                        </div>
                        <div>
                          <div style={{ fontSize: "var(--fs-h3)", fontWeight: 650 }}>{op.label}</div>
                          <div className="muted" style={{ fontSize: "var(--fs-caption)" }}>{count} propiedades</div>
                        </div>
                        <div style={{ marginLeft: "auto", fontFamily: "var(--font-display)", fontSize: "32px", fontWeight: 700, color: TONE_VAR[op.tone] }}>
                          {count}
                        </div>
                      </div>
                      <div className="muted" style={{ fontSize: "var(--fs-caption)", marginTop: "var(--sp-2)" }}>
                        {percentage}% del inventario
                      </div>
                      <div className="dist-bar" role="img" aria-label={`${op.label}: ${percentage}% del inventario`} style={{ marginTop: "var(--sp-2)" }}>
                        <span style={{ width: `${percentage}%`, background: TONE_VAR[op.tone] }} />
                      </div>
                    </div>
                  </Link>
                );
              })}
            </div>
            <div className="dist-legend">
              {operations.map((op) => {
                const count = props.by_operation[op.key] ?? 0;
                return (
                  <div key={op.key} className="dist-item">
                    <span className="dot" style={{ background: TONE_VAR[op.tone] }} />
                    <span>{op.label} <b>{count}</b></span>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      </section>

      {/* ===== BLOQUE 4: TIPOS DE PROPIEDAD ===== */}
      {Object.keys(props.by_type).length > 0 && (
        <section className="section-gap">
          <div className="card">
            <div className="card-head">
              <div>
                <h2 className="card-title">Tipos de propiedad</h2>
                <p className="card-sub">Distribución del inventario por tipología</p>
              </div>
              <Link className="card-link" to="/propiedades">Ver todas →</Link>
            </div>
            <div className="card-body">
              <div className="mini-stats">
                {propertyTypes
                  .filter((pt) => (props.by_type[pt.key] ?? 0) > 0)
                  .map((pt) => {
                    const count = props.by_type[pt.key] ?? 0;
                    const percentage = props.total > 0 ? Math.round((count / props.total) * 100) : 0;
                    return (
                      <div key={pt.key} className={`mini-stat tone-${pt.tone}`}>
                        <span className="ms-v">{count}</span>{" "}
                        <span className="ms-l">{pt.label} <span className="muted">({percentage}%)</span></span>
                      </div>
                    );
                  })}
              </div>
              <div className="dist-bar" role="img" aria-label="Distribución de propiedades por tipo">
                {propertyTypes
                  .filter((pt) => (props.by_type[pt.key] ?? 0) > 0)
                  .map((pt) => {
                    const count = props.by_type[pt.key] ?? 0;
                    const percentage = props.total > 0 ? (count / props.total) * 100 : 0;
                    return (
                      <span
                        key={pt.key}
                        style={{ width: `${percentage}%`, background: TONE_VAR[pt.tone] }}
                        title={`${pt.label}: ${count} (${percentage.toFixed(1)}%)`}
                      />
                    );
                  })}
              </div>
              <div className="dist-legend">
                {propertyTypes
                  .filter((pt) => (props.by_type[pt.key] ?? 0) > 0)
                  .map((pt) => {
                    const count = props.by_type[pt.key] ?? 0;
                    return (
                      <div key={pt.key} className="dist-item">
                        <span className="dot" style={{ background: TONE_VAR[pt.tone] }} />
                        <span>{pt.label} <b>{count}</b></span>
                      </div>
                    );
                  })}
              </div>
            </div>
          </div>
        </section>
      )}

      {/* ===== BLOQUE 5: PRÓXIMAS CITAS ===== */}
      <section className="section-gap">
        <div className="card">
          <div className="card-head">
            <div>
              <h2 className="card-title">Próximas citas</h2>
              <p className="card-sub">Visitas agendadas para los próximos 7 días</p>
            </div>
            <Link className="card-link" to="/citas">Ver todas →</Link>
          </div>
          <div className="card-body">
            {appts.today.length > 0 && (
              <div style={{ marginBottom: "var(--sp-4)" }}>
                <h3 style={{ fontSize: "var(--fs-h3)", fontWeight: 650, marginBottom: "var(--sp-2)" }}>Hoy</h3>
                <div className="feed">
                  {appts.today.map((appt) => (
                    <Link key={appt.id} to={`/citas/${appt.id}`} className="feed-row" style={{ textDecoration: "none", color: "inherit" }}>
                      <div className="feed-icon tone-success">
                        <Icon name="calendar" size={16} />
                      </div>
                      <div className="feed-main">
                        <div className="feed-title">
                          {formatDateTime(appt.scheduled_at)}
                          <span className="muted" style={{ marginLeft: "var(--sp-2)", fontWeight: 400 }}>
                            · {statusMeta(appt.status).label}
                          </span>
                        </div>
                        <div className="feed-sub">{propertyLabel(appt)}</div>
                      </div>
                      <span className={`badge tone-${statusMeta(appt.status).tone}`}>
                        {statusMeta(appt.status).label}
                      </span>
                    </Link>
                  ))}
                </div>
              </div>
            )}

            {appts.upcoming.length > 0 && (
              <div>
                <h3 style={{ fontSize: "var(--fs-h3)", fontWeight: 650, marginBottom: "var(--sp-2)" }}>Próximos días</h3>
                <div className="feed">
                  {appts.upcoming
                    .filter((appt) => !appts.today.some((t) => t.id === appt.id))
                    .slice(0, 8)
                    .map((appt) => (
                      <Link key={appt.id} to={`/citas/${appt.id}`} className="feed-row" style={{ textDecoration: "none", color: "inherit" }}>
                        <div className="feed-icon tone-info">
                          <Icon name="calendar" size={16} />
                        </div>
                        <div className="feed-main">
                          <div className="feed-title">
                            {formatDateTime(appt.scheduled_at)}
                          </div>
                          <div className="feed-sub">{propertyLabel(appt)}</div>
                        </div>
                        <span className={`badge tone-${statusMeta(appt.status).tone}`}>
                          {statusMeta(appt.status).label}
                        </span>
                      </Link>
                    ))}
                </div>
              </div>
            )}

            {(appts.today.length === 0 && appts.upcoming.length === 0) && (
              <div className="empty bordered" style={{ margin: 0 }}>
                <div className="empty-icon">
                  <Icon name="calendar" size={24} />
                </div>
                <p className="empty-title">No hay citas próximas</p>
                <p className="empty-desc">Las citas programadas aparecerán aquí automáticamente</p>
                <div className="empty-action">
                  <Link to="/citas/nueva" className="btn btn-primary">
                    <Icon name="plus" size={16} /> Nueva cita
                  </Link>
                </div>
              </div>
            )}
          </div>
        </div>
      </section>

      {/* ===== BLOQUE 6: ACCIONES RÁPIDAS ===== */}
      <section className="section-gap">
        <div className="card">
          <div className="card-head">
            <h2 className="card-title">Acciones rápidas</h2>
          </div>
          <div className="card-body">
            <div className="grid-2" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))" }}>
              <Link to="/propiedades/nueva" className="card" style={{ textDecoration: "none", color: "inherit", padding: "var(--sp-4)" }}>
                <div className="feed-icon tone-success" style={{ marginBottom: "var(--sp-2)" }}>
                  <Icon name="plus" size={24} />
                </div>
                <div style={{ fontWeight: 600, fontSize: "var(--fs-body)" }}>Nueva propiedad</div>
                <div className="muted" style={{ fontSize: "var(--fs-small)", marginTop: "var(--sp-1)" }}>Registrar inmueble</div>
              </Link>
              <Link to="/citas/nueva" className="card" style={{ textDecoration: "none", color: "inherit", padding: "var(--sp-4)" }}>
                <div className="feed-icon tone-info" style={{ marginBottom: "var(--sp-2)" }}>
                  <Icon name="calendar" size={24} />
                </div>
                <div style={{ fontWeight: 600, fontSize: "var(--fs-body)" }}>Nueva cita</div>
                <div className="muted" style={{ fontSize: "var(--fs-small)", marginTop: "var(--sp-1)" }}>Agendar visita</div>
              </Link>
              <Link to="/propiedades" className="card" style={{ textDecoration: "none", color: "inherit", padding: "var(--sp-4)" }}>
                <div className="feed-icon tone-neutral" style={{ marginBottom: "var(--sp-2)" }}>
                  <Icon name="building" size={24} />
                </div>
                <div style={{ fontWeight: 600, fontSize: "var(--fs-body)" }}>Ver propiedades</div>
                <div className="muted" style={{ fontSize: "var(--fs-small)", marginTop: "var(--sp-1)" }}>Inventario completo</div>
              </Link>
              <Link to="/leads" className="card" style={{ textDecoration: "none", color: "inherit", padding: "var(--sp-4)" }}>
                <div className="feed-icon tone-warn" style={{ marginBottom: "var(--sp-2)" }}>
                  <Icon name="users" size={24} />
                </div>
                <div style={{ fontWeight: 600, fontSize: "var(--fs-body)" }}>Ver leads</div>
                <div className="muted" style={{ fontSize: "var(--fs-small)", marginTop: "var(--sp-1)" }}>Gestión de clientes</div>
              </Link>
            </div>
          </div>
        </div>
      </section>

      {/* ===== FOOTER: Última actualización ===== */}
      <div className="footer">
        Última actualización: {new Date(stats.system.timestamp).toLocaleString("es-CO")}
      </div>
    </>
  );
}

// Skeleton loading state
function DashboardSkeleton() {
  const skeletonCard = (key: number) => (
    <div key={key} className="stat-card">
      <span className="stat-text" style={{ flex: 1 }}>
        <div className="skeleton" style={{ height: 30, width: "60%" }} />
        <div className="skeleton" style={{ height: 14, width: "80%", marginTop: "var(--sp-2)" }} />
      </span>
    </div>
  );
  return (
    <>
      <div className="stat-row">
        {[0, 1, 2, 3].map(skeletonCard)}
      </div>
      <div className="section-gap">
        <div className="card"><div className="card-body"><div className="skeleton-block" /></div></div>
      </div>
      <div className="section-gap">
        <div className="card"><div className="card-body"><div className="skeleton-block" /></div></div>
      </div>
      <div className="section-gap">
        <div className="card"><div className="card-body"><div className="skeleton-block" /></div></div>
      </div>
      <div className="section-gap">
        <div className="card"><div className="card-body"><div className="skeleton-block" /></div></div>
      </div>
    </>
  );
}