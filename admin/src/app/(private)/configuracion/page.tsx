import type { Metadata } from "next";
import { backend, type SystemSettingDTO } from "@/lib/backend";
import { PageHeader } from "@/components/PageHeader";
import { ErrorBanner } from "@/components/ErrorBanner";
import { RefreshButton } from "@/components/RefreshButton";
import { Icon } from "@/components/icons";
import { SectionHeader } from "@/components/SectionHeader";
import { Select } from "@/components/ui/Select";
import { SettingsPageContent } from "@/app/(private)/ajustes/SettingsPageContent";
import { buildHref, singleParam } from "@/lib/params";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Configuración del sistema" };

const CATEGORY_OPTIONS = [
  { value: "general", label: "General" },
  { value: "branding", label: "Branding" },
  { value: "contact", label: "Contacto" },
  { value: "appointments", label: "Citas" },
  { value: "uploads", label: "Subidas" },
  { value: "assistant", label: "Asistente" },
];

interface PageProps {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

export default async function Configuracion({ searchParams }: PageProps) {
  const sp = await searchParams;
  const q = (sp.q as string)?.trim() || "";
  const categoria = (sp.categoria as string)?.trim() || "";

  let settings: SystemSettingDTO[] = [];
  let error = "";
  try {
    const data = await backend<{ settings: SystemSettingDTO[] }>("/settings");
    settings = data.settings ?? [];
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  const visible = settings.filter((s) => {
    if (q && !s.key.toLowerCase().includes(q.toLowerCase()) && !s.label.toLowerCase().includes(q.toLowerCase())) return false;
    if (categoria && s.category !== categoria) return false;
    return true;
  });

  const baseParams: Record<string, string | undefined> = {
    q: q || undefined,
    categoria: categoria || undefined,
  };

  return (
    <>
      <PageHeader
        title="Configuración del sistema"
        description="Ajustes de negocio administrables: horarios, límites, contacto, zona horaria, etc."
        actions={<RefreshButton label="Recargar" />}
      />

      {error && <ErrorBanner message={error} />}

      <section className="card" aria-label="Configuración del sistema">
        <div className="card-head">
          <div className="toolbar">
            <div className="toolbar-filters">
              <form method="get" action="/configuracion" role="search" className="search-form">
                <span className="search-field">
                  <Icon name="search" size={14} />
                  <input
                    type="search"
                    name="q"
                    defaultValue={q}
                    placeholder="Buscar por clave, etiqueta…"
                    aria-label="Búsqueda general"
                  />
                </span>
                <button type="submit" className="btn btn-secondary">Buscar</button>
              </form>
              <Select
                label="Categoría"
                name="categoria"
                value={categoria}
                onChange={(e) => {
                  window.location.href = buildHref("/configuracion", baseParams, { categoria: e.target.value });
                }}
                options={[
                  { value: "", label: "Todas las categorías" },
                  ...CATEGORY_OPTIONS,
                ]}
                aria-label="Filtrar por categoría"
                className="inline-select"
              />
            </div>
            <span className="toolbar-meta">{visible.length} ajustes</span>
          </div>
        </div>

        {visible.length === 0 ? (
          <div className="empty bordered" style={{ padding: "var(--sp-6) var(--sp-4)" }}>
            <Icon name="settings" size={40} className="empty-icon" />
            <p className="empty-title">{q || categoria ? "Sin ajustes" : "Sin ajustes configurados"}</p>
            <p className="empty-desc">{q || categoria ? "Ningún ajuste coincide con los filtros." : "Los ajustes se crean desde la API o se inicializan con valores por defecto."}</p>
          </div>
        ) : (
          <div className="table-wrap">
            <table>
              <caption className="visually-hidden">Listado de ajustes del sistema con clave, tipo, valor y categoría</caption>
              <thead>
                <tr>
                  <th>Clave</th>
                  <th>Etiqueta</th>
                  <th>Tipo</th>
                  <th>Valor</th>
                  <th>Categoría</th>
                  <th>Editable</th>
                  <th>Descripción</th>
                </tr>
              </thead>
              <tbody>
                {visible.map((s) => (
                  <tr key={s.key}>
                    <td>
                      <div className="cell-main" style={{ fontFamily: "monospace", fontSize: "12px" }}>{s.key}</div>
                    </td>
                    <td>
                      <div className="cell-main">{s.label || "—"}</div>
                    </td>
                    <td><span className="badge">{s.type}</span></td>
                    <td>
                      <div className="cell-main" style={{ fontFamily: "monospace", fontSize: "12px", maxWidth: "300px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {typeof s.value === "string" ? s.value : JSON.stringify(s.value)}
                      </div>
                    </td>
                    <td>{s.category}</td>
                    <td>{s.is_editable ? "Sí" : "No"}</td>
                    <td className="cell-sub" style={{ maxWidth: "250px" }}>{s.description.slice(0, 80)}{s.description.length > 80 ? "…" : ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="card section-gap" aria-label="Actualizar ajustes">
        <SectionHeader title="Actualizar ajustes" sub="Modifica uno o varios ajustes. Solo claves conocidas y editables." />
        <SettingsPageContent basePath="/configuracion" />
      </section>
    </>
  );
}