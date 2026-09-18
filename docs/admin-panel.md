# Panel administrativo (`admin/`)

Guía del rediseño del panel interno de EXPRESEDI Inmobiliaria (Next.js 15 + React 19 + TypeScript, App Router). El backend es la API FastAPI local (`python main.py`, puerto 8000); el panel nunca expone `ADMIN_TOKEN` al navegador.

## 1. Arquitectura Server / Client

El panel sigue la regla: **Server Components por defecto; cliente solo para interacción real**.

| Ruta | Tipo | Por qué |
|---|---|---|
| `/` (dashboard) | Server (`force-dynamic`) | Solo lectura; agrega 6 endpoints del backend |
| `/propiedades` | **Server** + islas cliente | Tabla/paginación/filtros con deep links; mutación vía Server Action |
| `/citas` | Server (`force-dynamic`) | Solo lectura; filtros en URL |
| `/leads` | Server (`force-dynamic`) | Solo lectura; filtros en URL; `tel:` links |
| `/conversaciones` | Server + isla cliente | Listado server; mensajes en toggle cliente (sin fetch extra) |
| `/logs` | Server (`force-dynamic`) | Solo lectura; filtros en URL |
| `/documentos` | Client | Upload multipart + proceso + borrado requieren interacción y FormData |

- **Filtros**: viven en la URL (`?estado=…&ciudad=…&pagina=…`). Los tabs (`FilterTabs`) y la paginación (`Pagination`) son Server Components hechos solo de `<Link>` → deep-linkables, compartibles y sin JS.
- **Mutación de estado comercial** (`/propiedades`): Server Action `updatePropertyStatus` (`src/app/propiedades/actions.ts`) con validación de enum + `revalidatePath("/propiedades")` y `revalidatePath("/")`. La isla cliente (`PropertyStatusControl`) pide confirmación (`ConfirmDialog`) y muestra feedback (`ActionToast`). El token admin se inyecta server-side.
- **Proxy cliente** (`/api/proxy/[...path]`): se conserva SOLO para operaciones que necesitan FormData desde el navegador (subir documento). No se usa para datos de lectura.
- **Estados de ruta**: `loading.tsx` (skeleton), `error.tsx` (retry, reutiliza `PageHeader` en vez de duplicar markup), `not-found.tsx`.
- **Config de build** (`next.config.ts`): `outputFileTracingRoot` anclado al paquete. Sin esto, Next.js infiere el workspace root por los lockfiles de `$HOME` (Termux) y emite un warning en cada build; con el anclaje el build arranca limpio.
- **Imágenes**: `<img>` nativo con `width/height/loading="lazy"` sobre el proxy (rutas dinámicas no conocidas en build; `next/image` aportaría complejidad sin beneficio aquí). Las portadas se resuelven en servidor con `Promise.all`, solo para la página visible (≤ 12 filas) — elimina el N+1 en cascada del navegador.
- **Metadata**: `robots: { index: false, follow: false }` (panel interno); favicon de marca en `app/icon.svg`.

## 2. Sistema visual

Tokens en `src/app/globals.css` (CSS variables, sin Tailwind ni librerías externas):

- **Neutrales** (mayoría de píxeles): `--bg`, `--surface`, `--surface-2`, `--fg`, `--muted`, `--border`.
- **Acento único**: verde profundo inmobiliario `--primary` (+ soft/border). Un solo color de marca.
- **Semánticos**: success/warn/danger (+ soft) usados solo para estado, nunca decoración.
- **Tipografía**: display serif (Georgia) para títulos y cifras de métricas + sans de sistema para UI. Escala 11/12/13/14/14.5/16/26.
- **Espaciado** en escala de 4px; radios 6/9/12; sombras sutiles de 3 niveles; transiciones 100–200ms con `prefers-reduced-motion` respetado.
- **Densidad**: filas compactas (13px), celda principal en negrita + metadata secundaria en `cell-sub`; números a la derecha con `tabular-nums`.
- **Responsive**: los cortes adaptan la composición, no solo el ancho → `< 1280px` la fila de KPIs pasa a 2 columnas; `< 1024px` el sidebar se convierte en drawer con overlay y aparece la barra móvil con marca + **nombre de la sección actual** (`mobilebar-page`), de modo que el contexto de navegación no se pierde en móvil; las tablas se desplazan horizontalmente sin romper la página y las acciones de celda siguen siendo táctiles (≥ 24px de alto).

## 3. Componentes compartidos

| Componente | Tipo | Uso |
|---|---|---|
| `AdminShell` | Client | Sidebar (General/Operación/Comercial/Sistema), breadcrumb superior, drawer móvil, skip-link |
| `PageHeader` | Server | Título + descripción + acciones por página |
| `MetricCard` | Server | KPI accionable (número + link opcional + hint) |
| `SectionHeader` | Server | Cabecera de tarjeta con link «ver más» |
| `AttentionCard` | Server | Pendientes derivados de datos reales (solo si hay algo) |
| `FilterTabs` + `Pagination` | Server | Tabs de filtro y paginación con deep links |
| `StatusBadge` | Server | Badge con etiqueta en español y tono semántico |
| `PropertyThumb` | Server | Miniatura con fallback a icono |
| `PropertyStatusControl` | Client | Select + confirmación + Server Action + toast |
| `ConfirmDialog` | Client | Diálogo accesible (focus en acción segura, focus trap cíclico con Tab, `aria-describedby`, restauración de focus) |
| `ActionToast` | Client | Feedback flotante de operaciones |
| `ConversationMessages` | Client | Toggle de mensajes en burbujas (datos ya server-rendered) |
| `NoticeBanner` / `ErrorBanner` / `EmptyState` / `LoadingState` | Server-safe | Estados consistentes en todo el panel |

## 4. Reglas de negocio reflejadas

- Los **estados** provienen de los enums reales del backend (`app/database/models.py`): propiedades `AVAILABLE/RESERVED/SOLD/INACTIVE`, documentos `PENDING/PROCESSING/READY/FAILED`, leads `NEW/CONTACTED/INTERESTED/VISIT_SCHEDULED/NEGOTIATION/CLOSED/LOST`, citas `REQUESTED/CONFIRMED/CANCELLED/COMPLETED`. Etiquetas en español en `src/lib/status.ts`.
- El **dashboard** solo muestra métricas derivadas de datos reales; «Requiere atención» se construye con condiciones verificables (documentos fallidos, leads NEW > 72 h, citas REQUESTED sin confirmar, salud degradada, inventario vacío). Sin pendientes, muestra una confirmación sobria.
- **Paginación**: el backend limita `limit ≤ 200`; la UI pagina a 12 por página y solo habilita «Siguiente» cuando la página vino llena (el `count` del backend es por página).

## 5. Validación (resultados reales de esta sesión)

- **Typecheck** → PASS: `node node_modules/typescript/bin/tsc --noEmit` termina con exit 0. (`npm run typecheck` no puede ejecutarse en Termux porque el shim `node_modules/.bin/tsc` no es ejecutable y falla con *cannot execute: required file not found*; por eso se invoca `tsc` directo con Node.)
- **Build de producción** → PASS: `node node_modules/next/dist/bin/next build` compila en ~11–18 s, genera 5/5 páginas y emite la tabla de rutas:

  ```
  ┌ ƒ /                      1.48 kB   107 kB      ┌ ○ /documentos   5.76 kB   112 kB
  ├ ○ /_not-found             128 B    103 kB      ├ ƒ /leads        1.48 kB   107 kB
  ├ ƒ /api/proxy/[...path]    128 B    103 kB      ├ ƒ /logs         1.48 kB   107 kB
  ├ ƒ /citas                1.48 kB    107 kB      └ ƒ /propiedades  3.44 kB   109 kB
  ├ ƒ /conversaciones        1.7 kB    104 kB      + First Load JS shared by all  103 kB
  ```

  El JS compartido (103 kB) es la base de Next.js; cada página añade solo 1.4–5.8 kB → confirma que el árbol se mantiene mayoritariamente server-side.
- **Smoke test de rutas** (`next start` en :3100): `/`, `/propiedades`, `/leads`, `/citas`, `/conversaciones`, `/documentos`, `/logs` → **200**; ruta inexistente → **404** con `not-found.tsx`.
- **Degradación con backend caído**: el dashboard y las tablas renderizan `ErrorBanner` («Sin respuesta del backend») + shell completo (sidebar, breadcrumb, skip-link) sin romperse.
- **Prueba full-stack** (API FastAPI real en :8000 + Postgres/Redis locales, 16 propiedades, 2 leads, 2 citas, 4 documentos, 8 eventos IA):
  - Dashboard: KPIs y «Publicadas recientemente» con títulos reales; «Requiere atención» con pendientes reales.
  - `?estado=AVAILABLE&ciudad=Carepa` → filtrado real y paginación «Página 1 · 12 propiedades (hay más)».
  - `/citas` y `/leads` con estados reales del backend.
  - `/api/proxy/documents` → JSON real del backend con el token inyectado server-side.
- Nota: el frontend no define scripts de `lint` ni `test` (la suite pytest del backend queda fuera del alcance del panel).

## 6. Decisiones y limitaciones

- **Sin dependencias nuevas**: solo `next`, `react`, `react-dom` (lo que ya existía).
- **Sin modo oscuro**: el producto define un tema claro sobrio.
- Los formularios de filtro usan `<form method="get">` nativo: funcionan sin JS y mantienen la URL compartible.
- El `RefreshButton` ya no simula un estado de carga falso: recarga server-side y el feedback es el propio contenido actualizado.
- **Iconografía sin hacks**: la paginación usa un icono `chevron-left` propio en lugar de rotar `chevron-right` con estilo inline; todos los iconos comparten el mismo set monolínea 24×24 (trazo 1.7, `currentColor`).
- **Un solo modal**: `ConfirmDialog` es el único diálogo del panel; concentra ahí la accesibilidad (focus inicial en la acción segura, focus trap con Tab, Escape, restauración de focus) en vez de repartirla por cada pantalla.
- **Modelo de acceso (limitación conocida)**: el panel **no implementa un login propio**. Su protección es arquitectónica: el `ADMIN_TOKEN` solo existe server-side (el navegador nunca lo recibe), `robots: noindex/nofollow`, y el despliegue previsto es interno/local (`localhost:3000`, ver README §13). Cualquiera que alcance el puerto del panel puede ver los datos y disparar las Server Actions, así que **no debe exponerse a Internet** sin añadir autenticación antes (p. ej. Basic Auth en el proxy inverso o un middleware de sesión). No se añadió una capa de auth en esta iteración porque implicaría decisiones de producto (usuarios, roles, sesiones) fuera del alcance de un rediseño de UI, y §53 del brief prohíbe sobreingeniería.
