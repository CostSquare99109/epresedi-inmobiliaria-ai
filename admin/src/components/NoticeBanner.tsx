import { Icon } from "./icons";

/** Aviso de éxito (feedback de operaciones del panel). */
export function NoticeBanner({ message }: { message: string }) {
  return (
    <div className="notice-banner" role="status">
      <Icon name="check" size={16} />
      <p className="notice-banner-msg">{message}</p>
    </div>
  );
}
