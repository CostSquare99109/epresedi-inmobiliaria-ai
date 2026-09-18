/** Construye hrefs con query params preservados (deep links de filtros). */

export type ParamValue = string | number | undefined | null;

export function buildHref(
  basePath: string,
  params: Record<string, ParamValue>,
  overrides: Record<string, ParamValue> = {},
): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries({ ...params, ...overrides })) {
    if (v === undefined || v === null || v === "") continue;
    sp.set(k, String(v));
  }
  const qs = sp.toString();
  return qs ? `${basePath}?${qs}` : basePath;
}

/** Normaliza un valor de searchParams de Next.js a string único. */
export function singleParam(
  value: string | string[] | undefined,
): string {
  if (Array.isArray(value)) return value[0] ?? "";
  return value ?? "";
}
