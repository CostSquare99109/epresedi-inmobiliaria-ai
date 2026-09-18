"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { DocumentDTO } from "@/lib/backend";
import { PageHeader } from "@/components/PageHeader";
import { SectionHeader } from "@/components/SectionHeader";
import { StatusBadge } from "@/components/StatusBadge";
import { EmptyState } from "@/components/EmptyState";
import { ErrorBanner } from "@/components/ErrorBanner";
import { NoticeBanner } from "@/components/NoticeBanner";
import { LoadingState } from "@/components/LoadingState";
import { RefreshButton } from "@/components/RefreshButton";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { Icon } from "@/components/icons";
import { statusMeta } from "@/lib/status";
import { formatBytes, formatDateTime } from "@/lib/format";

const STATUSES = ["READY", "PROCESSING", "PENDING", "FAILED"];

export default function Documentos() {
  const [docs, setDocs] = useState<DocumentDTO[]>([]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [toDelete, setToDelete] = useState<DocumentDTO | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [fileName, setFileName] = useState("");
  const [filtro, setFiltro] = useState("");
  const [q, setQ] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);
  const titleRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    setBusy(true);
    setError("");
    try {
      const res = await fetch(`/api/proxy/documents`, { cache: "no-store" });
      const body = await res.json();
      setDocs(body.documents ?? []);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
      setLoaded(true);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function upload(e: React.FormEvent) {
    e.preventDefault();
    const file = fileRef.current?.files?.[0];
    if (!file) {
      setError("Selecciona un archivo (pdf, docx, txt, md) antes de subir.");
      return;
    }
    setError("");
    setNotice("");
    setUploading(true);
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("title", titleRef.current?.value ?? "");
      const res = await fetch(`/api/proxy/documents`, { method: "POST", body: form });
      if (!res.ok) {
        setError(`La subida fue rechazada (API ${res.status}): ${(await res.text()).slice(0, 160)}`);
        return;
      }
      if (fileRef.current) fileRef.current.value = "";
      if (titleRef.current) titleRef.current.value = "";
      setFileName("");
      setNotice("Documento subido. Ejecuta «Procesar» para indexarlo en el RAG.");
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setUploading(false);
    }
  }

  async function process(id: string) {
    setError("");
    setNotice("");
    const res = await fetch(`/api/proxy/documents/${id}/process`, { method: "POST" });
    if (!res.ok) {
      setError(`El procesamiento falló (API ${res.status}). Revisa el formato del documento e inténtalo de nuevo.`);
    } else {
      setNotice("Procesamiento encolado. El estado se actualizará al terminar.");
    }
    load();
  }

  async function remove(id: string) {
    setDeleting(true);
    setError("");
    try {
      const res = await fetch(`/api/proxy/documents/${id}`, { method: "DELETE" });
      if (!res.ok) {
        setError(`La eliminación falló (API ${res.status}).`);
        return;
      }
      setNotice("Documento eliminado del índice.");
      setToDelete(null);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setDeleting(false);
    }
  }

  const byStatus = useMemo(
    () =>
      docs.reduce<Record<string, number>>((acc, d) => {
        acc[d.status] = (acc[d.status] ?? 0) + 1;
        return acc;
      }, {}),
    [docs],
  );
  const visible = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return docs.filter((d) => {
      if (filtro && d.status !== filtro) return false;
      if (!needle) return true;
      return (
        d.title.toLowerCase().includes(needle) ||
        d.filename.toLowerCase().includes(needle)
      );
    });
  }, [docs, filtro, q]);

  return (
    <>
      <PageHeader
        title="Documentos · RAG"
        description="Base de conocimiento del asistente: sube documentos, procesa el índice y mantiene el contenido al día."
        actions={<RefreshButton label="Recargar" />}
      />

      {error && <ErrorBanner message={error} />}
      {notice && <NoticeBanner message={notice} />}

      <section className="card" aria-label="Subir documento">
        <SectionHeader
          title="Subir documento"
          sub="El contenido queda disponible para el asistente tras procesarlo"
        />
        <div className="card-body">
          <form onSubmit={upload}>
            <div className="form-grid">
              <div className="field">
                <label className="field-label" htmlFor="doc-title">
                  Título del documento
                </label>
                <input
                  type="text"
                  id="doc-title"
                  ref={titleRef}
                  placeholder="Ej.: Manual del propietario"
                />
                <span className="field-hint">
                  Opcional: si se omite se usa el nombre del archivo.
                </span>
              </div>
              <div className="field">
                <label className="field-label" htmlFor="doc-file">
                  Archivo
                </label>
                <div className={`upload-drop${fileName ? " has-file" : ""}`}>
                  <Icon name="upload" size={17} />
                  <input
                    type="file"
                    id="doc-file"
                    ref={fileRef}
                    accept=".pdf,.docx,.txt,.md"
                    onChange={(e) => setFileName(e.target.files?.[0]?.name ?? "")}
                  />
                </div>
                <span className="field-hint">
                  PDF, DOCX, TXT o MD · {formatBytes()}
                </span>
              </div>
            </div>
            <div className="form-actions section-gap">
              <button type="submit" className="btn btn-primary" disabled={uploading}>
                <Icon name="upload" size={15} />
                {uploading ? "Subiendo…" : "Subir documento"}
              </button>
            </div>
          </form>
        </div>
      </section>

      <section className="card section-gap" aria-label="Documentos indexados">
        <SectionHeader
          title="Documentos indexados"
          sub={`${docs.length} documento${docs.length === 1 ? "" : "s"} en la base de conocimiento`}
        />
        {busy && !loaded ? (
          <div className="card-body">
            <LoadingState rows={4} label="Cargando documentos…" />
          </div>
        ) : loaded && docs.length === 0 ? (
          <EmptyState
            bordered
            icon="file"
            title="Sin documentos"
            description="Sube el primer documento con el formulario superior. El asistente solo responde con base real cuando hay contenido indexado."
          />
        ) : (
          <>
            <div className="card-body tight">
              <div className="toolbar">
                <div className="toolbar-filters">
                  <div className="filter-tabs" role="group" aria-label="Filtrar por estado">
                    <button
                      type="button"
                      className={`filter-tab${filtro === "" ? " active" : ""}`}
                      onClick={() => setFiltro("")}
                      aria-pressed={filtro === ""}
                    >
                      Todos
                      <span className="count">{docs.length}</span>
                    </button>
                    {STATUSES.map((s) => (
                      <button
                        key={s}
                        type="button"
                        className={`filter-tab${filtro === s ? " active" : ""}`}
                        onClick={() => setFiltro(s)}
                        aria-pressed={filtro === s}
                      >
                        {statusMeta(s).label}
                        <span className="count">{byStatus[s] ?? 0}</span>
                      </button>
                    ))}
                  </div>
                  <div className="search-field">
                    <Icon name="search" size={14} />
                    <input
                      type="search"
                      value={q}
                      onChange={(e) => setQ(e.target.value)}
                      placeholder="Buscar por título o archivo…"
                      aria-label="Buscar documentos"
                    />
                  </div>
                </div>
                <span className="toolbar-meta">{visible.length} en la vista</span>
              </div>
            </div>

            {visible.length === 0 ? (
              <EmptyState
                bordered
                icon="file"
                title="Ningún documento coincide"
                description="Ajusta la búsqueda o el filtro de estado para ver documentos."
                action={
                  <button
                    type="button"
                    className="btn btn-secondary"
                    onClick={() => {
                      setFiltro("");
                      setQ("");
                    }}
                  >
                    Quitar filtros
                  </button>
                }
              />
            ) : (
              <div className="table-wrap">
                <table>
                  <caption className="visually-hidden">
                    Documentos indexados con estado, fragmentos, versión y acciones
                  </caption>
                  <thead>
                    <tr>
                      <th>Documento</th>
                      <th>Tipo</th>
                      <th>Estado</th>
                      <th className="num">Fragmentos</th>
                      <th className="num">Versión</th>
                      <th>Procesado</th>
                      <th>Acciones</th>
                    </tr>
                  </thead>
                  <tbody>
                    {visible.map((d) => (
                      <tr key={d.id}>
                        <td>
                          <div className="cell-main">{d.title}</div>
                          <div className="cell-sub">{d.filename}</div>
                        </td>
                        <td>{d.document_type}</td>
                        <td>
                          <StatusBadge status={d.status} />
                        </td>
                        <td className="num">{d.chunk_count}</td>
                        <td className="num">v{d.version}</td>
                        <td>
                          {d.processed_at ? formatDateTime(d.processed_at) : "—"}
                          {d.error && (
                            <div className="cell-sub">{d.error.slice(0, 60)}</div>
                          )}
                        </td>
                        <td>
                          <div className="btn-row">
                            <button
                              type="button"
                              className="btn btn-secondary"
                              onClick={() => process(d.id)}
                            >
                              {d.status === "READY" ? "Reprocesar" : "Procesar"}
                            </button>
                            <button
                              type="button"
                              className="btn btn-ghost btn-danger-ghost"
                              onClick={() => setToDelete(d)}
                              aria-label={`Eliminar ${d.title}`}
                            >
                              <Icon name="trash" size={15} />
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}
      </section>

      <ConfirmDialog
        open={toDelete !== null}
        title="¿Eliminar este documento?"
        description={
          toDelete
            ? `«${toDelete.title}» se eliminará junto con sus ${toDelete.chunk_count} fragmentos del índice RAG. Esta acción no se puede deshacer.`
            : ""
        }
        confirmLabel="Eliminar"
        cancelLabel="Conservar"
        danger
        busy={deleting}
        onConfirm={() => toDelete && remove(toDelete.id)}
        onCancel={() => setToDelete(null)}
      />
    </>
  );
}
