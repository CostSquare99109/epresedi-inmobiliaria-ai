export default function LoginLoading() {
  return (
    <div className="login-page">
      <main className="login-main" role="main">
        <div className="login-card">
          <header className="login-header">
            <div className="login-brand">
              <span className="login-brand-mark" aria-hidden="true">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
                  <polyline points="9 22 9 12 15 12 15 22" />
                </svg>
              </span>
              <div className="login-brand-text">
                <h1 className="login-title">EXPRESEDI</h1>
                <p className="login-subtitle">Inmobiliaria</p>
              </div>
            </div>
            <h2 className="login-heading">Iniciar sesión</h2>
            <p className="login-description">Panel administrativo interno</p>
          </header>
          <div className="skeleton login-skeleton-form" style={{ marginTop: "var(--sp-6)" }} />
          <div className="skeleton login-skeleton-form" style={{ marginTop: "var(--sp-4)" }} />
          <div className="skeleton login-skeleton-form" style={{ marginTop: "var(--sp-4)", height: "42px" }} />
        </div>
      </main>
    </div>
  );
}