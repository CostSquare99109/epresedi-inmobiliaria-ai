"use client";

import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Icon } from "@/components/icons";
import { ActionToast, type Feedback } from "@/components/ActionToast";
import { useAuth } from "@/context/AuthContext";

export function LoginPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { login } = useAuth();
  const redirectTo = searchParams.get("redirect") || "/";
  const [feedback, setFeedback] = useState<Feedback | null>(null);
  const [loading, setLoading] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [formData, setFormData] = useState({ email: "", password: "" });

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setFormData(prev => ({ ...prev, [e.target.name]: e.target.value }));
    setFeedback(null);
  };

  const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setFeedback(null);
    setLoading(true);

    try {
      const result = await login(formData.email, formData.password);

      if (!result.ok) {
        setFeedback({ tone: "error", message: result.detail || "Credenciales inválidas" });
        return;
      }

      setFeedback({ tone: "ok", message: "Acceso concedido" });
      setTimeout(() => navigate(redirectTo), 1000);
    } catch (e) {
      setFeedback({ tone: "error", message: e instanceof Error ? e.message : "Error de conexión" });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="login-page">
      <ActionToast feedback={feedback} onClose={() => setFeedback(null)} />

      <main className="login-main" role="main">
        <div className="login-card">
          <header className="login-header">
            <img
              src="/branding/epresedi-logo.jpg"
              alt="Epresedi Inmobiliaria"
              className="login-logo"
              width={96}
              height={96}
            />
            <h2 className="login-heading">Acceso al panel administrativo</h2>
            <p className="login-description">Ingresa con tus credenciales corporativas</p>
          </header>

          <form onSubmit={handleSubmit} className="login-form" noValidate>
            <Input
              label="Correo electrónico"
              name="email"
              type="email"
              value={formData.email}
              onChange={handleChange}
              required
              autoComplete="email"
              placeholder="Correo electrónico"
            />

            <div className="form-field">
              <label htmlFor="contraseña" className="form-label">
                Contraseña
              </label>
              <div className="password-wrap">
                <input
                  id="contraseña"
                  name="password"
                  type={showPassword ? "text" : "password"}
                  value={formData.password}
                  onChange={handleChange}
                  required
                  autoComplete="current-password"
                  placeholder="••••••••"
                  className="form-input"
                />
                <button
                  type="button"
                  className="password-toggle"
                  onClick={() => setShowPassword((v) => !v)}
                  aria-label={showPassword ? "Ocultar contraseña" : "Mostrar contraseña"}
                  aria-pressed={showPassword}
                  title={showPassword ? "Ocultar contraseña" : "Mostrar contraseña"}
                >
                  <Icon name={showPassword ? "eye" : "eye-off"} size={17} />
                </button>
              </div>
            </div>

            <Button
              type="submit"
              className="login-submit"
              loading={loading}
              size="lg"
              variant="primary"
            >
              {loading ? "Accediendo..." : "Entrar"}
              <Icon name="log-in" size={16} />
            </Button>
          </form>

          <footer className="login-footer">
            <p>Uso interno exclusivo</p>
          </footer>
        </div>
      </main>
    </div>
  );
}