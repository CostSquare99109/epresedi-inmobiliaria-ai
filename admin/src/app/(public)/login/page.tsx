"use client";

import { useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Icon } from "@/components/icons";
import { ActionToast, type Feedback } from "@/components/ActionToast";

export default function LoginPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const redirectTo = searchParams.get("redirect") || "/";
  const [feedback, setFeedback] = useState<Feedback | null>(null);
  const [loading, setLoading] = useState(false);
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
      const res = await fetch("/api/proxy/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(formData),
        credentials: "include",
      });

      const data = await res.json();

      if (!res.ok) {
        setFeedback({ tone: "error", message: data.detail || "Credenciales inválidas" });
        return;
      }

      setFeedback({ tone: "ok", message: "Acceso concedido" });
      setTimeout(() => router.push(redirectTo), 1000);
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
            <div className="login-brand">
              <span className="login-brand-mark" aria-hidden="true">
                <Icon name="home" size={20} />
              </span>
              <div className="login-brand-text">
                <h1 className="login-title">EXPRESEDI</h1>
                <p className="login-subtitle">Inmobiliaria</p>
              </div>
            </div>
            <h2 className="login-heading">Iniciar sesión</h2>
            <p className="login-description">Panel administrativo interno</p>
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

            <Input
              label="Contraseña"
              name="password"
              type="password"
              value={formData.password}
              onChange={handleChange}
              required
              autoComplete="current-password"
              placeholder="••••••••"
            />

            <Button
              type="submit"
              className="login-submit"
              loading={loading}
              size="lg"
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