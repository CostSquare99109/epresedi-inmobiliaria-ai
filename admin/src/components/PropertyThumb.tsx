import { Icon } from "./icons";

/**
 * Miniatura de propiedad. Usa <img> nativo (no next/image) porque la fuente
 * es el proxy dinámico /api/proxy/... (rutas no conocidas en build); tamaño,
 * aspect-ratio y lazy loading se controlan desde CSS + atributos.
 */
export function PropertyThumb({
  propertyId,
  filename,
  alt,
}: {
  propertyId: string;
  filename?: string | null;
  alt: string;
}) {
  return (
    <span className="thumb">
      {filename ? (
        <img
          src={`/api/proxy/properties/${propertyId}/images/${filename}`}
          alt={alt}
          width={104}
          height={80}
          loading="lazy"
          decoding="async"
        />
      ) : (
        <Icon name="building" size={16} />
      )}
    </span>
  );
}
