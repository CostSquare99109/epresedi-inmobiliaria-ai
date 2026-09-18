"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { logoutAction } from "@/app/actions/auth";
import { Icon, type IconName } from "./icons";
import { ActionToast, type Feedback } from "@/components/ActionToast";

interface NavItem {
  href: string;
  label: string;
  icon: IconName;
  permission?: string;
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
      { href: "/proyectos", label: "Proyectos", icon: "folder" },
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
      { href: "/auditoria", label: "Auditoría", icon: "shield" },
      { href: "/contenido", label: "Contenido CMS", icon: "edit" },
      { href: "/configuracion", label: "Configuración", icon: "settings" },
      { href: "/usuarios", label: "Usuarios", icon: "users", permission: "users.manage" },
    ],
  },
];

const CRUMBS: Record<string, { group: string; page: string }> = {
  "/": { group: "General", page: "Panel general" },
  "/propiedades": { group: "Operación", page: "Propiedades" },
  "/proyectos": { group: "Operación", page: "Proyectos" },
  "/citas": { group: "Operación", page: "Citas" },
  "/leads": { group: "Comercial", page: "Leads" },
  "/conversaciones": { group: "Comercial", page: "Conversaciones" },
  "/documentos": { group: "Sistema", page: "Documentos · RAG" },
  "/logs": { group: "Sistema", page: "Logs IA" },
  "/auditoria": { group: "Sistema", page: "Auditoría" },
  "/contenido": { group: "Sistema", page: "Contenido CMS" },
  "/configuracion": { group: "Sistema", page: "Configuración" },
  "/usuarios": { group: "Sistema", page: "Usuarios" },
};

function isActive(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/";
  return pathname.startsWith(href);
}

export default function AdminShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const [user, setUser] = useState<{ name: string; email: string; role: string } | null>(null);
  const [loadingUser, setLoadingUser] = useState(true);
  const [feedback, setFeedback] = useState<Feedback | null>(null);

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

  useEffect(() => {
    async function loadUser() {
      try {
        const res = await fetch("/api/proxy/auth/me", { credentials: "include" });
        if (res.ok) {
          const data = await res.json();
          setUser(data.user);
        } else {
          setUser(null);
        }
      } catch {
        setUser(null);
      } finally {
        setLoadingUser(false);
      }
    }
    loadUser();
  }, []);

  const handleLogout = async () => {
    setFeedback({ tone: "ok", message: "Cerrando sesión..." });
    try {
      await logoutAction();
      setUser(null);
      setFeedback({ tone: "ok", message: "Sesión cerrada" });
      setTimeout(() => window.location.href = "/login", 1000);
    } catch (e) {
      setFeedback({ tone: "error", message: "Error cerrando sesión" });
    }
  };

  const crumb = CRUMBS[pathname] ?? null;

  return (
    <div className="shell">
      <ActionToast feedback={feedback} onClose={() => setFeedback(null)} />
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
          {loadingUser ? (
            <div className="user-info-loading">Cargando...</div>
          ) : user ? (
            <div className="user-info">
              <div className="user-avatar" aria-hidden="true">
                <Icon name="user" size={16} />
              </div>
              <div className="user-details">
                <span className="user-name">{user.name}</span>
                <span className="user-role">{user.role}</span>
              </div>
              <button
                type="button"
                className="btn-logout"
                onClick={handleLogout}
                disabled={loadingUser}
                aria-label="Cerrar sesión"
              >
                <Icon name="log-out" size={14} />
              </button>
            </div>
          ) : (
            <div className="user-info-empty">
              <span>No autenticado</span>
              <Link href="/login" className="btn btn-sm btn-secondary">
                <Icon name="log-in" size={12} />
                Entrar
              </Link>
            </div>
          )}
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