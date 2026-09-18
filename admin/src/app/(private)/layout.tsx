import AdminShell from "@/components/AdminShell";

export default function PrivateLayout({ children }: { children: React.ReactNode }) {
  return <AdminShell>{children}</AdminShell>;
}