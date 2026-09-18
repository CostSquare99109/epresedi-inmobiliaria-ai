import type { Metadata } from "next";
import "../globals.css";

export const metadata: Metadata = {
  title: {
    default: "EXPRESEDI Inmobiliaria · Acceso",
    template: "%s · EXPRESEDI Inmobiliaria",
  },
  description: "Panel administrativo interno - Iniciar sesión",
  robots: { index: false, follow: false },
};

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return <div className="auth-layout">{children}</div>;
}