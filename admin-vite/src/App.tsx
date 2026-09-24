import { Routes, Route, Navigate, Outlet } from "react-router-dom";
import { AuthProvider, useAuth } from "./context/AuthContext";
import { AdminShell } from "./components/AdminShell";
import { LoginPage } from "./pages/LoginPage";
import { DashboardPage } from "./pages/DashboardPage";
import { PropiedadesPage } from "./pages/propiedades/PropiedadesPage";
import { PropiedadNuevaPage } from "./pages/propiedades/PropiedadNuevaPage";
import { PropiedadEditarPage } from "./pages/propiedades/PropiedadEditarPage";
import { PropiedadDetallePage } from "./pages/propiedades/PropiedadDetallePage";
import { CitasPage } from "./pages/citas/CitasPage";
import { CitaNuevaPage } from "./pages/citas/CitaNuevaPage";
import { CitaDetallePage } from "./pages/citas/CitaDetallePage";
import { LeadsPage } from "./pages/leads/LeadsPage";
import { NotFoundPage } from "./pages/NotFoundPage";

function PrivateRoutes() {
  const { user, loading } = useAuth();

  if (loading) {
    return (
      <AdminShell>
        <div className="content" style={{ display: "flex", justifyContent: "center", alignItems: "center", minHeight: "400px" }}>
          <span className="muted">Cargando sesión...</span>
        </div>
      </AdminShell>
    );
  }

  if (!user) {
    return <Navigate to="/login" replace />;
  }

  return (
    <AdminShell>
      <Outlet />
    </AdminShell>
  );
}

function PublicRoutes() {
  const { user, loading } = useAuth();

  if (loading) {
    return (
      <div className="login-page" style={{ display: "flex", justifyContent: "center", alignItems: "center", minHeight: "100vh" }}>
        <span className="muted">Cargando...</span>
      </div>
    );
  }

  if (user) {
    return <Navigate to="/" replace />;
  }

  return <Outlet />;
}

export function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/login" element={<PublicRoutes />}>
          <Route index element={<LoginPage />} />
        </Route>
        <Route path="/*" element={<PrivateRoutes />}>
          <Route index element={<DashboardPage />} />
          <Route path="propiedades" element={<PropiedadesPage />} />
          <Route path="propiedades/nueva" element={<PropiedadNuevaPage />} />
          <Route path="propiedades/:id/editar" element={<PropiedadEditarPage />} />
          <Route path="propiedades/:id" element={<PropiedadDetallePage />} />
          <Route path="citas" element={<CitasPage />} />
          <Route path="citas/nueva" element={<CitaNuevaPage />} />
          <Route path="citas/:id" element={<CitaDetallePage />} />
          <Route path="leads" element={<LeadsPage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Routes>
    </AuthProvider>
  );
}