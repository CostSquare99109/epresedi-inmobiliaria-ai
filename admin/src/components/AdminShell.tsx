"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Icon, type IconName } from "./icons";

interface NavItem {
  href: string;
  label: string;
  icon: IconName;
}

const GROUPS: { label: string; items: NavItem[] }[] = [
  {
    label: "General",
    items: [{ href: "/", label: "Panel general", icon: "dashboard" }],
  },
  {
    label: "Operación",
    items: [
      { href: "/propiedades", label: "Propiedades", icon: "building" },
      { href: "/citas", label: "Citas", icon: "calendar" },
    ],
  },
  {
    label: "Comercial",
    items: [
      { href: "/leads", label: "Leads", icon: "user-plus" },
      { href: "/conversaciones", label: "Conversaciones", icon: "chat" },
    ],
  },
  {
    label: "Sistema",
    items: [
      { href: "/documentos", label: "Documentos · RAG", icon: "file" },
      { href: "/logs", label: "Logs IA", icon: "list" },
    ],
  },
];

/** Breadcrumb estático por ruta (contexto de navegación, sin datos dinámicos). */
const CRUMBS: Record<string, { group: string; page: string }> = {
  "/": { group: "General", page: "Panel general" },
  "/propiedades": { group: "Operación", page: "Propiedades" },
  "/citas": { group: "Operación", page: "Citas" },
  "/leads": { group: "Comercial", page: "Leads" },
  "/conversaciones": { group: "Comercial", page: "Conversaciones" },
  "/documentos": { group: "Sistema", page: "Documentos · RAG" },
  "/logs": { group: "Sistema", page: "Logs IA" },
};

function isActive(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/";
  return pathname.startsWith(href);
}

export default function AdminShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);

  useEffect(() => {
    setOpen(false);
  }, [pathname]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  const crumb = CRUMBS[pathname] ?? null;

  return (
    <div className="shell">
      <a href="#main" className="skip-link">
        Saltar al contenido
      </a>
      <div
        className={`drawer-overlay ${open ? "show" : ""}`}
        onClick={() => setOpen(false)}
        aria-hidden="true"
      />
      <aside id="sidebar" className={`sidebar ${open ? "open" : ""}`} aria-label="Panel lateral">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">
            <Icon name="home" size={18} />
          </span>
          <span className="brand-text">
            <span className="brand-name">EXPRESEDI</span>
            <span className="brand-sub">Inmobiliaria</span>
          </span>
        </div>
        <nav className="side-nav" aria-label="Secciones administrativas">
          {GROUPS.map((group) => (
            <div className="nav-group" key={group.label}>
              <div className="nav-group-label">{group.label}</div>
              {group.items.map((item) => {
                const active = isActive(pathname, item.href);
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    className={`nav-item ${active ? "active" : ""}`}
                    aria-current={active ? "page" : undefined}
                  >
                    <Icon name={item.icon} size={16} />
                    {item.label}
                  </Link>
                );
              })}
            </div>
          ))}
        </nav>
        <div className="side-foot">
          <b>Panel interno</b>
          <span>Uso administrativo · datos locales</span>
        </div>
      </aside>
      <div className="main-col">
        {crumb && (
          <nav className="topbar" aria-label="Ruta de navegación">
            <ol className="breadcrumb">
              <li>
                <span className="muted">{crumb.group}</span>
                <span className="crumb-sep" aria-hidden="true">
                  <Icon name="chevron-right" size={12} />
                </span>
              </li>
              <li>
                <span className="crumb-current" aria-current="page">
                  {crumb.page}
                </span>
              </li>
            </ol>
          </nav>
        )}
        <header className="mobilebar">
          <button
            type="button"
            className="btn-icon"
            onClick={() => setOpen((v) => !v)}
            aria-expanded={open}
            aria-controls="sidebar"
            aria-label={open ? "Cerrar menú de navegación" : "Abrir menú de navegación"}
          >
            <Icon name={open ? "x" : "menu"} size={18} />
          </button>
          <span className="mobilebar-brand">EXPRESEDI</span>
          {crumb && <span className="mobilebar-page">{crumb.page}</span>}
        </header>
        <main className="content" id="main">
          {children}
        </main>
        <footer className="footer">
          EXPRESEDI Inmobiliaria · Panel interno de operación
        </footer>
      </div>
    </div>
  );
}
