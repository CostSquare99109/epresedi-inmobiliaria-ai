import type { Metadata } from "next";
import AdminShell from "@/components/AdminShell";
import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "EXPRESEDI Inmobiliaria · Panel administrativo",
    template: "%s · EXPRESEDI Inmobiliaria",
  },
  description:
    "Panel administrativo de la operación inmobiliaria: propiedades, documentos, leads, conversaciones, citas y auditoría de IA.",
  robots: { index: false, follow: false },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="es">
      <body>
        <AdminShell>{children}</AdminShell>
      </body>
    </html>
  );
}
