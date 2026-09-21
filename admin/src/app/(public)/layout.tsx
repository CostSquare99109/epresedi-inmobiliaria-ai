import type { Metadata } from "next";
import "../globals.css";

export const metadata: Metadata = {
  title: {
    default: "epresedi Inmobiliaria · Acceso",
    template: "%s · epresedi Inmobiliaria",
  },
  description: "Panel administrativo interno - Iniciar sesión",
  robots: { index: false, follow: false },
};

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return <div className="auth-layout">{children}</div>;
}