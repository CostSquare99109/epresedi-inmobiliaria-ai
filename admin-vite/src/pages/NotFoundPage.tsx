"use client";

import { Link } from "react-router-dom";
import { Icon } from "../components/icons";
import { PageHeader } from "../components/PageHeader";

export function NotFoundPage() {
  return (
    <>
      <PageHeader
        title="Página no encontrada"
        description="La ruta solicitada no existe en el panel administrativo."
      />
      <div className="card" style={{ maxWidth: "400px" }}>
        <div className="card-body" style={{ textAlign: "center", padding: "var(--sp-7) var(--sp-5)" }}>
          <Icon name="alert" size={48} className="muted" />
          <h2 style={{ marginTop: "var(--sp-4)" }}>404 · No encontrada</h2>
          <p className="muted" style={{ marginTop: "var(--sp-2)" }}>
            La página que buscas no existe o ha sido movida.
          </p>
          <Link to="/" className="btn btn-primary" style={{ marginTop: "var(--sp-5)" }}>
            <Icon name="home" size={14} />
            Volver al panel
          </Link>
        </div>
      </div>
    </>
  );
}