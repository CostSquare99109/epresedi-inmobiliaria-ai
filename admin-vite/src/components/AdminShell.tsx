"use client";

import { useEffect, useState } from "react";
import { Link, useLocation, NavLink } from "react-router-dom";
import { logout } from "../api/auth";
import { Icon, type IconName } from "./icons";
import { ActionToast, type Feedback } from "./ActionToast";

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
      { href: "/citas", label: "Citas", icon: "calendar" },
    ],
  },
  {
    label: "Comercial",
    items: [
      { href: "/leads", label: "Leads", icon: "user-plus" },
    ],
  },
];

const CRUMBS: Record<string, { group: string; page: string }> = {
  "/": { group: "General", page: "Panel general" },
  "/propiedades": { group: "Operación", page: "Propiedades" },
  "/citas": { group: "Operación", page: "Citas" },
  "/leads": { group: "Comercial", page: "Leads" },
};

function isActive(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/";
  return pathname.startsWith(href);
}

export function AdminShell({ children }: { children: React.ReactNode }) {
  const location = useLocation();
  const [open, setOpen] = useState(false);
  const [user, setUser] = useState<{ name: string; email: string; role: string } | null>(null);
  const [loadingUser, setLoadingUser] = useState(true);
  const [feedback, setFeedback] = useState<Feedback | null>(null);

  useEffect(() => {
    setOpen(false);
  }, [location.pathname]);

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
        const result = await getCurrentUser();
        if (result.ok) {
          setUser(result.user);
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
      await logout();
      setUser(null);
      setFeedback({ tone: "ok", message: "Sesión cerrada" });
      setTimeout(() => window.location.href = "/login", 1000);
    } catch (e) {
      setFeedback({ tone: "error", message: "Error cerrando sesión" });
    }
  };

  const crumb = CRUMBS[location.pathname] ?? null;

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
          <Link to="/" className="brand-link" aria-label="Epresedi Inmobiliaria — Panel general">
            <img
              src="/branding/epresedi-logo.jpg"
              alt="Epresedi Inmobiliaria"
              className="brand-logo"
              width={42}
              height={42}
            />
          </Link>
        </div>
        <nav className="side-nav" aria-label="Secciones administrativas">
          {GROUPS.map((group) => (
            <div className="nav-group" key={group.label}>
              <div className="nav-group-label">{group.label}</div>
              {group.items.map((item) => {
                const active = isActive(location.pathname, item.href);
                return (
                  <NavLink
                    key={item.href}
                    to={item.href}
                    className={({ isActive }) => `nav-item ${isActive ? "active" : ""}`}
                    aria-current={active ? "page" : undefined}
                  >
                    <Icon name={item.icon} size={16} />
                    {item.label}
                  </NavLink>
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
              <Link to="/login" className="btn btn-sm btn-secondary">
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
          <span className="mobilebar-brand">
            <img
              src="/branding/epresedi-logo.jpg"
              alt="Epresedi Inmobiliaria"
              className="mobilebar-brand-logo"
              width={34}
              height={34}
            />
            <span className="mobilebar-brand-name">Epresedi</span>
          </span>
        </header>
        <main className="content" id="main">
          {children}
        </main>
        <footer className="footer">
          Epresedi Inmobiliaria · Panel interno de operación
        </footer>
      </div>
    </div>
  );
}

// Import getCurrentUser here to avoid circular dependency
import { getCurrentUser } from "../api/auth";