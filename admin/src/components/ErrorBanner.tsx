import { Icon } from "./icons";

interface ErrorBannerProps {
  title?: string;
  message: string;
  onRetry?: () => void;
  retryLabel?: string;
}

export function ErrorBanner({
  title = "No se pudo cargar la información",
  message,
  onRetry,
  retryLabel = "Reintentar",
}: ErrorBannerProps) {
  return (
    <div className="error-banner" role="alert">
      <Icon name="alert" size={18} />
      <div>
        <p className="error-banner-title">{title}</p>
        <p className="error-banner-msg">{message}</p>
      </div>
      {onRetry && (
        <button type="button" className="btn btn-danger" onClick={onRetry}>
          {retryLabel}
        </button>
      )}
    </div>
  );
}
