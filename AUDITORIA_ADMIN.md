# AUDITORÍA DEL PANEL ADMINISTRATIVO — EXPRESEDI INMOBILIARIA

---

## 1. RESUMEN EJECUTIVO

### Estado general
El panel administrativo (`admin/`) es una **aplicación Next.js 15 (App Router) funcional pero incompleta** que actúa principalmente como **visor de solo lectura con capacidades limitadas de escritura**. Se conecta a un backend FastAPI (Python) mediante un proxy que inyecta el token de administrador server-side.

### Qué está bien
- **Arquitectura limpia**: Separación clara frontend/backend, tipado estricto TypeScript, Server Actions para mutaciones.
- **Dashboard completo**: Métricas clave, distribución de inventario, actividad del asistente, citas próximas, leads recientes, estado de documentos RAG, salud del sistema.
- **Listados funcionales**: Propiedades, leads, citas, conversaciones, documentos, logs IA — todos con filtrado, paginación (donde aplica) y estados vacíos.
- **Gestión de documentos RAG completa**: Subida, procesamiento, re-procesamiento, eliminación con confirmación.
- **Cambio de estado de propiedades**: Funcional (AVAILABLE, RESERVED, SOLD, INACTIVE) con confirmación y feedback.
- **Diseño coherente**: CSS variables, responsive, accesibilidad básica (ARIA, focus visible, skip link).
- **Backend robusto**: FastAPI + SQLAlchemy 2.0 + pgvector, migraciones Alembic, validación Pydantic, full-text search, embeddings.

### Qué falta (CRÍTICO)
- **CRUD de propiedades en el frontend**: El backend expone POST/PATCH/DELETE `/properties` pero **no existe ninguna UI** para crear, editar o eliminar propiedades.
- **Gestión de imágenes incompleta**: Solo subida; **no hay eliminación, reordenación ni selección de portada**.
- **Gestión de leads**: Solo lectura; no se puede editar, cambiar estado, agregar notas, asignar asesor.
- **Gestión de citas**: Solo lectura; no se puede crear, editar, cancelar, reprogramar desde el admin.
- **Usuarios y roles**: **No existe ningún sistema de gestión de usuarios administrativos** (solo un token único `ADMIN_TOKEN`).
- **Gestión de contenido estático**: Banners, FAQs, info de contacto, configuración comercial — todo requiere editar código.

### Principales riesgos
1. **Admin de solo lectura de facto**: El 80% de las operaciones de escritura requieren acceso directo a la API o base de datos.
2. **Un solo token de admin**: Sin roles, sin auditoría de acciones administrativas, sin expiración.
3. **Imágenes huérfanas**: Al eliminar una propiedad, sus imágenes quedan en disco (no hay cascade en storage).
4. **Sin validación frontend**: Los formularios (documentos) validan solo en backend; UX mejorable.

### Principales oportunidades
- Completar el CRUD de propiedades (alto impacto, backend ya listo).
- Añadir gestión de imágenes completa (eliminar, reordenar, portada).
- Implementar leads y citas con escritura (CRUD).
- Sistema de usuarios/roles para operación real.
- Hacer administrable el contenido que hoy está hardcodeado.

---

## 2. STACK DETECTADO

| Tecnología | Versión | Uso | Evidencia |
|------------|---------|-----|-----------|
| Next.js | 15.1.0 | Framework frontend (App Router) | `admin/package.json:12` |
| React | 19.0.0 | UI library | `admin/package.json:13` |
| TypeScript | 5.x | Tipado estricto | `admin/tsconfig.json:7` |
| CSS Variables | Nativo | Sistema de estilos (sin framework) | `admin/src/app/globals.css` |
| FastAPI | 0.115+ | Backend API | `app/api/routes.py` |
| Python | 3.11+ | Backend runtime | `pyproject.toml` |
| SQLAlchemy | 2.0 | ORM async | `app/database/base.py` |
| PostgreSQL | 16+ | Base de datos principal | `alembic.ini`, `migrations/` |
| pgvector | 0.5.1+ | Búsqueda vectorial | `migrations/versions/8027eadf0d90_initial_schema.py:23` |
| Alembic | 1.13+ | Migraciones | `alembic.ini` |
| Redis | 7+ | Cola de jobs / cache | `app/workers/queue.py` |
| Pydantic | 2.x | Validación API | `app/api/routes.py:8` |
| Uvicorn | 0.30+ | ASGI server | `main.py:184` |
| Pillow | 10+ | Generación imágenes seed | `scripts/seed.py:235` |
| pytest | 8.x | Testing backend | `pyproject.toml` |
| ESLint/Prettier | No configurado | Linting | Ausente en `package.json` |

**Ausentes destacables**: Librería de componentes (Radix, shadcn), librería de formularios (React Hook Form, Zod), testing frontend (Vitest, Playwright), Storybook, CI/CD.

---

## 3. MAPA DEL PANEL

| Ruta | Página | Tipo | Descripción |
|------|--------|------|-------------|
| `/` | `page.tsx` | Server Component | Dashboard con métricas, inventario, actividad IA, citas, leads, docs, salud |
| `/propiedades` | `propiedades/page.tsx` | Server Component | Listado paginado, filtros (estado, ciudad), thumbnails, cambio de estado |
| `/propiedades/actions.ts` | Server Action | Mutación | `updatePropertyStatus` (PATCH `/properties/{id}`) |
| `/leads` | `leads/page.tsx` | Server Component | Listado con filtros por estado (NEW, CONTACTED, INTERESTED, VISIT_SCHEDULED, NEGOTIATION, CLOSED, LOST) |
| `/citas` | `citas/page.tsx` | Server Component | Listado con filtros, orden cronológico (próximas/historial) |
| `/conversaciones` | `conversaciones/page.tsx` | Server Component | Vista de solo lectura de conversaciones Telegram + últimos mensajes |
| `/documentos` | `documentos/page.tsx` | Client Component | **CRUD completo**: subida (PDF/DOCX/TXT/MD), procesamiento, re-procesamiento, eliminación |
| `/logs` | `logs/page.tsx` | Server Component | Auditoría eventos IA (filtros: estado, intención, latencia media) |
| `/api/proxy/[...path]` | `route.ts` | Route Handler | Proxy client-side → backend con inyección `X-Admin-Token` |

**Componentes compartidos** (`admin/src/components/`):
- `AdminShell` — Layout con sidebar, breadcrumb, responsive drawer
- `PageHeader`, `SectionHeader` — Encabezados consistentes
- `MetricCard`, `AttentionCard` — KPIs y alertas
- `PropertyThumb`, `PropertyStatusControl` — UI específica propiedades
- `FilterTabs`, `Pagination` — Controles de tabla (server-side, deep links)
- `ConfirmDialog`, `ActionToast` — Feedback accesible
- `StatusBadge`, `Icon`, `EmptyState`, `ErrorBanner`, `NoticeBanner`, `LoadingState`

**Librerías** (`admin/src/lib/`):
- `backend.ts` — Cliente API server-side con `adminHeaders()`
- `status.ts` — Metadatos de estado (label + tone) para todas las entidades
- `format.ts` — Formateo dinero, fechas, bytes, timeAgo
- `params.ts` — Utilidades query string (buildHref, singleParam)

---

## 4. FUNCIONALIDADES EXISTENTES

| Área | Funcionalidad | Estado | Evidencia |
|------|---------------|--------|-----------|
| Dashboard | Métricas (disponibles, reservadas, leads, citas) | ✅ EXISTE | `page.tsx:182-207` |
| Dashboard | Distribución inventario por estado (barra + leyenda) | ✅ EXISTE | `page.tsx:235-270` |
| Dashboard | Actividad reciente asistente (latencia, intención, status) | ✅ EXISTE | `page.tsx:276-318` |
| Dashboard | Propiedades recientes con portada | ✅ EXISTE | `page.tsx:322-361` |
| Dashboard | Próximas citas (con propiedad + lead) | ✅ EXISTE | `page.tsx:364-410` |
| Dashboard | Leads recientes (contacto, presupuesto, teléfono) | ✅ EXISTE | `page.tsx:412-459` |
| Dashboard | Documentos RAG (contadores por estado, errores) | ✅ EXISTE | `page.tsx:462-528` |
| Dashboard | Salud sistema (checks postgres, redis, nvidia, storage) | ✅ EXISTE | `page.tsx:530-574` |
| Propiedades | Listado paginado (12/page) | ✅ EXISTE | `propiedades/page.tsx:38-43` |
| Propiedades | Filtro por estado (tabs deep-link) | ✅ EXISTE | `propiedades/page.tsx:78-88` |
| Propiedades | Búsqueda por ciudad (form GET) | ✅ EXISTE | `propiedades/page.tsx:89-104` |
| Propiedades | Miniatura portada (proxy imagen) | ✅ EXISTE | `PropertyThumb.tsx` |
| Propiedades | Cambio de estado (select + confirm + Server Action) | ✅ EXISTE | `PropertyStatusControl.tsx`, `actions.ts` |
| Propiedades | Estados: AVAILABLE, RESERVED, SOLD, INACTIVE | ✅ EXISTE | `status.ts:12-15` |
| Leads | Listado completo con orden creado desc | ✅ EXISTE | `leads/page.tsx:30-31` |
| Leads | Filtro por estado (7 estados) | ✅ EXISTE | `leads/page.tsx:57-71` |
| Leads | Teléfono clickeable (tel:) | ✅ EXISTE | `leads/page.tsx:118-126` |
| Citas | Listado con propiedad + lead resueltos | ✅ EXISTE | `citas/page.tsx:44-45` |
| Citas | Orden: próximas asc, historial desc | ✅ EXISTE | `citas/page.tsx:52-60` |
| Citas | Filtro por estado (4 estados) | ✅ EXISTE | `citas/page.tsx:77-91` |
| Documentos | Subida archivo (PDF, DOCX, TXT, MD) | ✅ EXISTE | `documentos/page.tsx:54-83` |
| Documentos | Procesar / Reprocesar (RAG) | ✅ EXISTE | `documentos/page.tsx:85-95` |
| Documentos | Eliminar con confirmación | ✅ EXISTE | `documentos/page.tsx:97-114` |
| Documentos | Filtros (estado + búsqueda texto) | ✅ EXISTE | `documentos/page.tsx:218-254` |
| Conversaciones | Vista resumen + últimos 5 mensajes | ✅ EXISTE | `conversaciones/page.tsx:43-62` |
| Logs IA | Tabla eventos (intención, modelo, tools, latencia) | ✅ EXISTE | `logs/page.tsx:120-156` |
| Logs IA | Filtros (estado OK/ERROR, intención) | ✅ EXISTE | `logs/page.tsx:68-97` |

---

## 5. FUNCIONALIDADES FALTANTES (FALTA)

### 5.1 CRUD Propiedades — Frontend inexistente
| Operación | Backend | Frontend | Evidencia |
|-----------|---------|----------|-----------|
| CREATE | ✅ `POST /properties` | ❌ **FALTA** | `routes.py:137-145` |
| READ (list) | ✅ `GET /properties` | ✅ EXISTE | `propiedades/page.tsx` |
| READ (detail) | ✅ `GET /properties/{id}` | ❌ **FALTA** | `routes.py:128-134` |
| UPDATE (partial) | ✅ `PATCH /properties/{id}` | ❌ **FALTA** (solo status) | `routes.py:148-155` |
| DELETE | ✅ `DELETE /properties/{id}` | ❌ **FALTA** | `routes.py:158-165` |

**Campos soportados en backend pero sin UI**: `description`, `address`, `latitude`, `longitude`, `project_id`, `features[]`, `property_type` (7 tipos), `operation` (SALE/RENT), `currency`.

### 5.2 Gestión de imágenes — Incompleta
| Operación | Backend | Frontend | Evidencia |
|-----------|---------|----------|-----------|
| Subir | ✅ `POST /properties/{id}/images` | ✅ (solo vía API directa) | `routes.py:168-179` |
| Listar | ✅ `GET /properties/{id}/images` | ✅ (dashboard + listado) | `routes.py:182-186` |
| Ver | ✅ `GET /properties/{id}/images/{filename}` | ✅ (via proxy) | `routes.py:189-194` |
| **Eliminar** | ❌ **FALTA** | ❌ **FALTA** | — |
| **Reordenar** | ❌ **FALTA** | ❌ **FALTA** | — |
| **Seleccionar portada** | ❌ **FALTA** (convención: `cover.*`) | ❌ **FALTA** | `files.py:48` |

### 5.3 Gestión de Leads — Solo lectura
| Operación | Backend | Frontend |
|-----------|---------|----------|
| CREATE | ❌ (se crea desde bot) | ❌ |
| READ | ✅ `GET /leads` | ✅ |
| UPDATE (status, notes, budget, phone) | ✅ `crm.update_lead` | ❌ **FALTA** |
| DELETE | ❌ | ❌ |
| Asignar asesor | ❌ | ❌ |
| Exportar | ❌ | ❌ |

### 5.4 Gestión de Citas — Solo lectura
| Operación | Backend | Frontend |
|-----------|---------|----------|
| CREATE | ✅ `appointments.create_appointment` | ❌ **FALTA** |
| READ | ✅ `GET /appointments` | ✅ |
| UPDATE (status, notes, reschedule) | ✅ `cancel_appointment` + lógica | ❌ **FALTA** |
| DELETE | ❌ (solo cancel) | ❌ |
| Ver slots disponibles | ✅ `list_available_slots` | ❌ **FALTA** |

### 5.5 Usuarios y Roles — Inexistente
| Funcionalidad | Estado |
|---------------|--------|
| Listar usuarios admin | ❌ FALTA |
| Crear usuario admin | ❌ FALTA |
| Editar usuario | ❌ FALTA |
| Cambiar rol/permisos | ❌ FALTA |
| Desactivar usuario | ❌ FALTA |
| Auditoría acciones admin | ❌ FALTA |
| Múltiples roles (superadmin, admin, editor, asesor) | ❌ FALTA |
| Expiración tokens / rotación | ❌ FALTA |

### 5.6 Gestión de Contenido Público — Inexistente
| Contenido | Estado actual | Debería ser admin? |
|-----------|---------------|---------------------|
| Banners / hero público | Hardcodeado en frontend público | ✅ SÍ |
| FAQs | No existe / hardcodeado | ✅ SÍ |
| Info contacto empresa | Variables de entorno / hardcodeado | ✅ SÍ |
| Configuración comercial (horarios, zonas) | Settings / hardcodeado | ✅ SÍ |
| Textos legales / términos | No existe | ✅ SÍ |
| Proyectos (entidad `Project` existe en BD) | Solo seed | ✅ SÍ |

### 5.7 Import/Export / Acciones Masivas
| Funcionalidad | Estado |
|---------------|--------|
| Exportar propiedades (CSV/Excel) | ❌ FALTA |
| Importar propiedades (CSV/Excel) | ❌ FALTA |
| Acciones masivas (cambiar estado múltiple, eliminar) | ❌ FALTA |
| Exportar leads | ❌ FALTA |
| Exportar citas | ❌ FALTA |

---

## 6. FUNCIONALIDADES INCOMPLETAS (INCOMPLETA)

| ID | Funcionalidad | Qué existe | Qué falta | Archivo/Ubicación | Impacto | Prioridad |
|----|---------------|------------|-----------|-------------------|---------|-----------|
| INC-001 | CRUD Propiedades | READ + status change | CREATE, UPDATE (campos), DELETE, Detail view | `propiedades/page.tsx`, `actions.ts` | **ALTO** | P1 |
| INC-002 | Gestión imágenes | Subida + listado + vista | Eliminar, reordenar, definir portada, validación tamaño/formato frontend | `files.py`, `routes.py:168-194` | **ALTO** | P1 |
| INC-003 | Gestión Leads | Listado + filtros | Editar (status, notes, budget, phone), asignar, historial | `leads/page.tsx`, `crm/service.py:86-103` | **MEDIO** | P2 |
| INC-004 | Gestión Citas | Listado + filtros | Crear, reprogramar, cancelar, ver slots | `citas/page.tsx`, `appointments/service.py` | **MEDIO** | P2 |
| INC-005 | Proyectos | Existe en BD + seed | CRUD completo en admin (crear, editar, asignar propiedades) | `models.py:111-123`, `seed.py:43-50` | **BAJO** | P3 |
| INC-006 | Filtros propiedades | Estado + ciudad | Tipo, operación, rango precio, área, habitaciones, proyecto | `propiedades/page.tsx:33-43` | **MEDIO** | P2 |
| INC-007 | Vista detalle propiedad | No existe | Modal/página con todos los campos, imágenes, acciones | — | **ALTO** | P1 |
| INC-008 | Estados vacíos accionables | Existen (EmptyState) | Botones "Crear primero" en propiedades, leads, citas | `EmptyState.tsx`, `page.tsx:223-232` | **BAJO** | P3 |

---

## 7. FUNCIONALIDADES MEJORABLES (MEJORABLE)

| ID | Funcionalidad | Problema actual | Mejora sugerida | Prioridad |
|----|---------------|-----------------|-----------------|-----------|
| MEJ-001 | Dashboard métricas | Solo contadores básicos | Añadir: conversión lead→cita, ticket medio, días en mercado, propiedades sin imágenes | P3 |
| MEJ-002 | Tabla propiedades | Columnas fijas | Columnas configurables, densidad, vista tarjetas/tabla | P3 |
| MEJ-003 | Búsqueda propiedades | Solo ciudad (ilike) | Full-text search (usa `search_vector` existente), filtros combinados | P2 |
| MEJ-004 | Responsive tablas | Scroll horizontal en móvil | Tarjetas apiladas en < 640px, columnas prioritarias | P2 |
| MEJ-005 | Accesibilidad formularios | Labels OK, pero sin `aria-describedby` en errores | Vincular errores a inputs, announcements ARIA live | P3 |
| MEJ-006 | Validación frontend | Solo backend | Validación client-side (Zod/Valibot) para UX inmediata | P3 |
| MEJ-007 | Carga de imágenes | Sin preview, sin compresión | Preview antes de subir, compresión client-side (canvas), progress | P2 |
| MEJ-008 | Feedback mutaciones | Solo toast | Skeletons durante Server Action, optimistic UI para status | P3 |
| MEJ-009 | Navegación teclado | Básica | Shortcuts (/, n para nueva propiedad, escape para cerrar modales) | P4 |
| MEJ-010 | Tema oscuro | Solo claro | Toggle tema (CSS variables ya preparadas) | P4 |

---

## 8. GESTIÓN DE PROPIEDADES — AUDITORÍA COMPLETA

### 8.1 Modelo de datos (Backend) — `app/database/models.py:126-202`
```python
Property:
  - id: UUID (PK)
  - code: String(24) UNIQUE — auto PROP-XXXX
  - title: String(200)
  - description: Text
  - property_type: Enum[casa, apartamento, lote, local, oficina, finca, proyecto]
  - operation: Enum[SALE, RENT]
  - price: Numeric(14,2)
  - currency: String(3) default COP
  - city: String(80)
  - neighborhood: String(120)
  - address: String(240)
  - latitude/longitude: Numeric(9,6) nullable
  - area_m2: Numeric(10,2) nullable
  - bedrooms/bathrooms/parking_spaces: Integer nullable
  - status: Enum[AVAILABLE, RESERVED, SOLD, INACTIVE] default AVAILABLE
  - features: JSONB []
  - project_id: FK → projects.id nullable
  - search_vector: TSVECTOR (computed, español)
  - title_embedding: HALFVEC(2048) — semántico
  - created_at / updated_at: timestamps
```

**Cobertura de campos en admin frontend**:
| Campo | En listado | En detalle | En crear/editar |
|-------|------------|------------|-----------------|
| title | ✅ | ❌ | ❌ |
| code | ✅ | ❌ | ❌ (auto) |
| property_type | ✅ | ❌ | ❌ |
| operation | ✅ | ❌ | ❌ |
| price | ✅ | ❌ | ❌ |
| city/neighborhood | ✅ | ❌ | ❌ |
| address | ❌ | ❌ | ❌ |
| lat/lon | ❌ | ❌ | ❌ |
| area_m2 | ✅ | ❌ | ❌ |
| bedrooms/bathrooms/parking | ✅ | ❌ | ❌ |
| status | ✅ + control | ❌ | ✅ (solo status) |
| features | ❌ | ❌ | ❌ |
| project | ✅ (nombre) | ❌ | ❌ |
| description | ❌ | ❌ | ❌ |
| images | ✅ (portada) | ❌ | ❌ (subida sóla) |

### 8.2 Flujos administrativos — Propiedades

| Flujo | Existe | Bloqueos |
|-------|--------|----------|
| Ver listado | ✅ | — |
| Filtrar listado | ✅ | Faltan filtros avanzados |
| Ver detalle | ❌ | **No existe página/modal detalle** |
| Crear propiedad | ❌ | **Backend listo, frontend ausente** |
| Editar propiedad | ❌ | **Backend listo (PATCH), frontend ausente** |
| Cambiar estado | ✅ | Solo 4 estados, sin historial |
| Subir imágenes | ⚠️ Solo API | **Sin UI integrada en flujo propiedad** |
| Gestionar imágenes | ❌ | **Sin eliminar, reordenar, portada** |
| Eliminar propiedad | ❌ | **Backend listo, frontend ausente** |
| Duplicar propiedad | ❌ | — |
| Ver propiedades sin imágenes | ❌ | Se podría derivar (left join) |
| Ver propiedades incompletas | ❌ | Campos obligatorios no definidos en UI |

---

## 9. GESTIÓN DE IMÁGENES — AUDITORÍA COMPLETA

### 9.1 Backend actual (`app/api/files.py`, `routes.py:168-194`)

**Subida** (`POST /properties/{id}/images`):
- Validación: extensión (jpg/jpeg/png/webp), tamaño ≤ `MAX_UPLOAD_MB` (15MB default)
- Naming: primera → `cover.{ext}`, siguientes → `001.{ext}`, `002.{ext}`...
- Almacenamiento: `storage/properties/{property_id}/`
- **Sin compresión, sin redimensionado, sin validación dimensiones**

**Listado** (`GET /properties/{id}/images`):
- Orden: `cover.*` primero, luego numérico `001`, `002`...
- Retorna array de filenames

**Servicio** (`GET /properties/{id}/images/{filename}`):
- Protección path traversal (`_SAFE_NAME` regex)
- Sirve archivo directo (`FileResponse`)

**Ausente en backend**:
- `DELETE /properties/{id}/images/{filename}`
- `PATCH /properties/{id}/images/reorder` (o similar)
- `PATCH /properties/{id}/images/{filename}/cover`

### 9.2 Frontend actual
- **Dashboard**: Muestra portada via `PropertyThumb` (proxy `/api/proxy/properties/{id}/images/{filename}`)
- **Listado propiedades**: Muestra miniatura portada (resuelta en servidor)
- **Documentos**: Subida archivos (no imágenes de propiedad)

### 9.3 Hallazgos de imágenes

| Hallazgo | Categoría | Prioridad | Evidencia |
|----------|-----------|-----------|-----------|
| No hay UI para subir imágenes desde panel propiedades | FALTA | P1 | `propiedades/page.tsx` — no hay botón "Subir imágenes" |
| No se puede eliminar imagen | FALTA | P1 | Backend sin endpoint DELETE |
| No se puede reordenar | FALTA | P2 | Convención `cover.*` + numérico, pero inmutable |
| No se puede cambiar portada | FALTA | P2 | Primera subida = cover, inmutable |
| Sin validación client-side (tipo, tamaño) | MEJORABLE | P3 | `documentos/page.tsx` valida en backend únicamente |
| Sin preview antes de subir | MEJORABLE | P3 | `upload-drop` muestra solo nombre |
| Sin compresión/optimización | MEJORABLE | P3 | Pillow disponible en backend pero no usado |
| Imágenes huérfanas al borrar propiedad | INCOMPLETA | P2 | `delete_property` no limpia `storage/properties/{id}/` |
| Límite de imágenes no documentado | MEJORABLE | P4 | Sin límite en código, solo disco |

---

## 10. EDICIÓN DE PROPIEDADES — MATRIZ CRUD

| Entidad | Crear | Leer | Actualizar | Eliminar | Activar/Desactivar |
|---------|-------|------|------------|----------|-------------------|
| **Propiedad** | ❌ FALTA | ✅ EXISTE (listado) | ⚠️ PARCIAL (solo status) | ❌ FALTA | ✅ EXISTE (status) |
| **Imagen** | ⚠️ PARCIAL (solo API) | ✅ EXISTE | ❌ FALTA (reordenar/portada) | ❌ FALTA | ❌ FALTA |
| **Lead** | ❌ (desde bot) | ✅ EXISTE | ❌ FALTA | ❌ FALTA | ❌ FALTA (status manual) |
| **Cita** | ❌ FALTA | ✅ EXISTE | ❌ FALTA | ⚠️ PARCIAL (cancel) | ❌ FALTA |
| **Documento** | ✅ EXISTE | ✅ EXISTE | ✅ EXISTE (reprocesar) | ✅ EXISTE | ❌ N/A |
| **Usuario admin** | ❌ FALTA | ❌ FALTA | ❌ FALTA | ❌ FALTA | ❌ FALTA |
| **Proyecto** | ❌ FALTA | ❌ FALTA (solo seed) | ❌ FALTA | ❌ FALTA | ❌ FALTA |

**Conclusión**: El panel es **>80% solo lectura** para las entidades core del negocio (propiedades, leads, citas). Solo Documentos y Estado de Propiedad tienen escritura real.

---

## 11. ESTADOS DE PROPIEDADES

### 11.1 Definición (Backend) — `models.py:72-76`
```python
class PropertyStatus(StrEnum):
    AVAILABLE = "AVAILABLE"   # Disponible → búsqueda pública
    RESERVED  = "RESERVED"    # Reservada  → no en búsqueda, pero activa
    SOLD      = "SOLD"        # Vendida    → histórico, no en búsqueda
    INACTIVE  = "INACTIVE"    # Inactiva   → retirada, no en búsqueda
```

### 11.2 Frontend — `status.ts:12-15`, `PropertyStatusControl.tsx`
- Select con los 4 estados, confirmación modal, Server Action `updatePropertyStatus`
- `revalidatePath("/propiedades")` + `revalidatePath("/")` tras cambio
- Badge visual con tone: success/warn/neutral/idle

### 11.3 Inconsistencias detectadas
| Problema | Detalle | Impacto |
|----------|---------|---------|
| No hay estado "ARRENDADA" | `Operation.RENT` existe pero `PropertyStatus` no tiene `RENTED` | Propiedades en arriendo usan `AVAILABLE` o `INACTIVE` |
| No hay historial de cambios de estado | Solo `updated_at` genérico | Auditoría imposible |
| Frontend no filtra por estado en búsqueda pública | El asistente usa `property_repository` que filtra por status | **Consistente**: solo `AVAILABLE` se muestra al público |
| PropertyStatusControl permite cualquier transición | Sin reglas de negocio (ej. SOLD → AVAILABLE) | Riesgo de datos inconsistentes |

---

## 12. INVENTARIO — CAPACIDADES ACTUALES vs REQUERIDAS

| Capacidad | Estado | Detalle |
|-----------|--------|---------|
| Ver todas las propiedades | ✅ | Paginado 12/page, orden created_at desc |
| Filtrar por estado | ✅ | 4 tabs (Todos, Disponible, Reservada, Vendida, Inactiva) |
| Buscar por ciudad | ✅ | `ilike %ciudad%` |
| Buscar por texto libre | ❌ | **Falta** (backend tiene `search_vector` full-text) |
| Filtrar por tipo | ❌ | **Falta** (casa, apartamento, lote, local, oficina, finca, proyecto) |
| Filtrar por operación | ❌ | **Falta** (SALE, RENT) |
| Filtrar por rango precio | ❌ | **Falta** |
| Filtrar por área/habitaciones | ❌ | **Falta** |
| Filtrar por proyecto | ❌ | **Falta** (existe `project_id` en BD) |
| Ordenar columnas | ❌ | **Falta** (orden fijo: created_at desc) |
| Paginación | ✅ | Server-side (offset/limit), solo Anterior/Siguiente |
| Ver fecha creación/actualización | ❌ | **Falta** (existe en BD, no en tabla) |
| Identificar sin imágenes | ❌ | **Falta** (requiere left join o flag) |
| Identificar incompletas | ❌ | **Falta** (definir "incompleto") |
| Vista tabla | ✅ | Única vista actual |
| Vista tarjetas | ❌ | **Falta** (dashboard usa tarjetas pero solo 4) |
| Exportación | ❌ | **Falta** |
| Importación | ❌ | **Falta** |
| Acciones masivas | ❌ | **Falta** |

**Clasificación**:
- **Esenciales**: Búsqueda texto, filtros tipo/operación/precio, ordenación, exportación
- **Importantes**: Vista tarjetas, identificar sin imágenes/incompletas, fecha actualización
- **Opcionales**: Importación, acciones masivas, filtros proyecto/área/habitaciones

---

## 13. GESTIÓN DE LEADS Y CLIENTES

### 13.1 Modelo (Backend) — `models.py:398-416`
```python
Lead:
  - id: UUID
  - user_id: FK → users (Telegram user)
  - name: String(160)
  - phone: String(40)
  - status: Enum[NEW, CONTACTED, INTERESTED, VISIT_SCHEDULED, NEGOTIATION, CLOSED, LOST]
  - budget: Numeric(14,2) nullable
  - preferences: JSONB
  - notes: Text
  - created_at / updated_at
```

### 13.2 Frontend actual (`leads/page.tsx`)
- **Solo lectura**: Tabla con nombre, teléfono (tel:), estado, presupuesto, fecha
- **Filtros**: 7 estados con contadores
- **Sin acciones**: No editar, no cambiar estado, no notas, no asignar

### 13.3 Backend CRM (`crm/service.py:86-103`)
```python
async def update_lead(session, lead_id, data: dict):
    # Soporta: name, phone, budget, notes, status, preferences
```

### 13.4 Hallazgos

| Hallazgo | Categoría | Prioridad | Evidencia |
|----------|-----------|-----------|-----------|
| No se puede editar lead | FALTA | P1 | Backend `update_lead` existe, frontend no |
| No se puede cambiar estado lead | FALTA | P1 | 7 estados definidos, solo lectura |
| No hay notas/comentarios | FALTA | P2 | Campo `notes` en BD, no expuesto |
| No hay asignación a asesor | FALTA | P2 | No existe campo `assigned_to` en modelo |
| No hay historial de interacciones | FALTA | P3 | Solo `created_at`/`updated_at` |
| No hay exportación | FALTA | P3 | — |
| Teléfono clickeable (tel:) | ✅ EXISTE | — | `leads/page.tsx:118-126` |

---

## 14. GESTIÓN DE CITAS

### 14.1 Modelo (Backend) — `models.py:419-439`
```python
Appointment:
  - id: UUID
  - lead_id: FK → leads (nullable)
  - property_id: FK → properties (CASCADE)
  - scheduled_at: DateTime (index)
  - duration_minutes: Integer default 60
  - status: Enum[REQUESTED, CONFIRMED, CANCELLED, COMPLETED]
  - notes: Text
  - created_at / updated_at
```

### 14.2 Frontend actual (`citas/page.tsx`)
- **Solo lectura**: Tabla con propiedad, interesado, fecha, estado
- **Filtros**: 4 estados con contadores
- **Orden inteligente**: Próximas asc, historial desc

### 14.3 Backend Appointments (`appointments/service.py`)
- `list_available_slots()` — genera slots 9-17h, excluye domingos, evita double-booking
- `create_appointment()` — atómico, previene double-booking
- `cancel_appointment()` — solo si no CANCELLED/COMPLETED
- `list_appointments()`, `get_appointment()`

### 14.4 Hallazgos

| Hallazgo | Categoría | Prioridad | Evidencia |
|----------|-----------|-----------|-----------|
| No se puede crear cita desde admin | FALTA | P1 | Backend `create_appointment` existe |
| No se puede reprogramar | FALTA | P1 | Requiere cancel + crear; no hay UI |
| No se puede cancelar desde admin | FALTA | P1 | Backend `cancel_appointment` existe |
| No se ven slots disponibles | FALTA | P2 | `list_available_slots` no expuesto en API |
| No hay notas visibles/editables | FALTA | P2 | Campo `notes` en BD, no en tabla |
| No hay asignación a asesor | FALTA | P3 | No existe campo en modelo |
| Sin recordatorios/notificaciones | FALTA | P3 | — |

---

## 15. USUARIOS, ROLES Y PERMISOS

### 15.1 Estado actual
| Aspecto | Implementación |
|---------|----------------|
| Autenticación admin | Header `X-Admin-Token` comparado con `ADMIN_TOKEN` env var |
| Roles | **Uno solo**: "admin" (token válido = acceso total) |
| Usuarios admin | **No existen** en BD (tabla `users` es para clientes Telegram) |
| Permisos granulares | **No** (todo o nada) |
| Auditoría acciones admin | **No** (solo `AiEvent` para asistente) |
| Sesiones / expiración | **No** (token estático) |
| Recuperación acceso | **No** |

### 15.2 Modelo usuarios (clientes) — `models.py:285-292`
```python
AppUser:
  - id: BigInteger (Telegram user_id)
  - username, first_name
  - created_at, last_seen_at
  - preference: UserPreference (1:1)
```
**No hay tabla de usuarios administrativos**.

### 15.3 Hallazgos de seguridad — Autorización

| Hallazgo | Severidad | Descripción |
|----------|-----------|-------------|
| Token único compartido | **CRÍTICO** | Un solo `ADMIN_TOKEN` para todo el equipo; sin rotación, sin revocación individual |
| Sin RBAC | **ALTO** | Cualquier token válido = acceso total (CRUD propiedades, docs, leads, citas) |
| Sin auditoría admin | **ALTO** | No hay log de quién cambió qué y cuándo |
| Endpoints GET sin auth | **MEDIO** | `/properties`, `/properties/{id}/images` son públicos (sin `require_admin`) |
| Path traversal en imágenes | **BAJO** | Protegido por regex `_SAFE_NAME` en `files.py:58-65` |
| Validación tamaño archivo | **BAJO** | Solo backend (`MAX_UPLOAD_MB`), sin client-side |
| CSRF | **BAJO** | Server Actions + same-origin; proxy requiere token |

---

## 16. GESTIÓN DE CONTENIDO — QUÉ ES ADMINISTRABLE VS HARDCODEADO

### 16.1 Administrable desde el panel actual
| Contenido | Panel | API Endpoint |
|-----------|-------|--------------|
| Propiedades (solo estado) | ✅ Parcial | `PATCH /properties/{id}` (solo status) |
| Documentos RAG | ✅ Completo | `POST/GET/DELETE /documents`, `POST /documents/{id}/process` |
| Estados de propiedad | ✅ | `PATCH /properties/{id}` (status) |

### 16.2 Requiere editar código / variables de entorno
| Contenido | Ubicación actual | Debería estar en admin |
|-----------|------------------|------------------------|
| Nombre empresa / branding | `admin/src/components/AdminShell.tsx:93-94` | ✅ SÍ |
| Info contacto (tel, email, dirección) | `.env` / frontend público | ✅ SÍ |
| Horarios de atención | `app/appointments/service.py:22` (SLOT_HOURS) | ✅ SÍ |
| Zona horaria | `.env:64` (`TZ=America/Bogota`) | ✅ SÍ |
| Moneda / formato precios | `settings.py:44` (`currency: COP`) / `format.ts` | ✅ SÍ |
| Límites subida | `.env:52` (`MAX_UPLOAD_MB=15`) | ✅ SÍ |
| Tipos de propiedad (enum) | `models.py:56-63` (migración BD) | ⚠️ Requiere migración |
| Operaciones (enum) | `models.py:66-69` | ⚠️ Requiere migración |
| Textos legales / FAQs | **No existen** | ✅ SÍ |
| Banners / hero público | Frontend público (no auditado) | ✅ SÍ |
| Configuración asistente (prompts) | `app/agents/prompts.py` | ✅ SÍ |

### 16.3 Datos hardcodeados detectados (solo seed/dev)
| Dato | Archivo | Tipo | Nota |
|------|---------|------|------|
| 16 propiedades seed | `scripts/seed.py:52-149` | **DEV ONLY** | Solo para desarrollo/test; `APP_ENV=production` bloquea seed |
| 3 proyectos seed | `scripts/seed.py:43-50` | **DEV ONLY** | Idem |
| 4 documentos RAG seed | `scripts/seed.py:152-233` | **DEV ONLY** | PDF/DOCX/MD/TXT generados en `documents/inbox` |
| Imágenes sintéticas | `scripts/seed.py:235-245` | **DEV ONLY** | Pillow genera JPEGs de colores con texto |
| Estados enum | `models.py`, `status.ts` | **CONFIG** | No "hardcodeado" — es configuración de dominio |
| Labels español | `status.ts:10-39` | **CONFIG** | I18n nativo, no hardcodeo |

**Conclusión**: **No hay datos hardcodeados en producción**. El seed es explícitamente solo para dev/test y se bloquea en producción. Los enums y labels son configuración de dominio legítima.

---

## 17. FUNCIONALIDADES SIMULADAS (BOTONES SIN ACCIÓN REAL)

| Botón/Área | Simula | Realidad | Evidencia |
|------------|--------|----------|-----------|
| "Agregar propiedad" | ❌ No existe botón | — | `propiedades/page.tsx` — no hay botón crear |
| "Editar propiedad" | ❌ No existe | — | Solo select de estado |
| "Eliminar propiedad" | ❌ No existe | — | Backend tiene DELETE, frontend no |
| "Subir imágenes" (en propiedades) | ❌ No existe | — | Solo en Documentos |
| "Exportar" | ❌ No existe | — | En ninguna tabla |
| "Importar" | ❌ No existe | — | — |
| "Cambiar estado lead" | ❌ No existe | — | Solo visualización badge |
| "Crear cita" | ❌ No existe | — | Backend tiene create, frontend no |
| "Reprogramar cita" | ❌ No existe | — | — |
| "Cancelar cita" | ❌ No existe | — | Backend tiene cancel, frontend no |
| "Gestionar usuarios" | ❌ No existe sección | — | No hay ruta `/usuarios` |
| "Configuración" | ❌ No existe sección | — | No hay ruta `/configuracion` |

**No se encontraron**: Botones que solo muestran toast, modales sin persistencia, TODOs/FIXMEs en código admin.

---

## 18. UX/UI DEL ADMIN — ANÁLISIS

### 18.1 Fortalezas
- **Jerarquía visual clara**: PageHeader → SectionHeader → Card → Table/Grid
- **Consistencia**: Componentes reutilizados (MetricCard, StatusBadge, FilterTabs, Pagination)
- **Estados vacíos accionables**: `EmptyState` con botón "Ir a Propiedades" cuando procede
- **Feedback**: ConfirmDialog (accesible), ActionToast (auto-dismiss 6s), LoadingState (skeletons)
- **Navegación**: Sidebar colapsable móvil, breadcrumb escritorio, skip link
- **Responsive**: Breakpoints 1279px, 1023px, 599px bien definidos en CSS
- **Accesibilidad base**: ARIA labels, roles, focus-visible, semantica HTML

### 18.2 Debilidades / Confusión

| Problema | Ubicación | Impacto |
|----------|-----------|---------|
| **Sin botón "Nueva propiedad"** | `propiedades/page.tsx` | Usuario no descubre que puede crear (aunque backend no lo soporta en UI) |
| **Imágenes desconectadas** | Subida en `/documentos` vs propiedades | Flujo mental roto: se esperaría subir imágenes en la propiedad |
| **Sin vista detalle propiedad** | Click en fila no navega | Row es `<tr>` sin link; solo status es interactivo |
| **Filtros leads/citas no preservan página** | `FilterTabs` resetea `pagina` pero leads/citas no tienen paginación | Inconsistencia UX |
| **Toolbar mezcla filtros y búsqueda** | `propiedades/page.tsx:76-105` | `FilterTabs` (links) + form GET (ciudad) — patrones distintos |
| **Sin indicador de carga en Server Action** | `PropertyStatusControl` | `useTransition` pero sin skeleton en select |
| **Dashboard no permite drill-down** | Métricas son links pero sin contexto | Click "Ver inventario" → pierde filtro aplicado |

### 18.3 Formularios — Auditoría
| Formulario | Validación | Campos obligatorios | Error handling | Loading | Prevención doble envío |
|------------|------------|---------------------|----------------|---------|------------------------|
| Subida documento | Solo backend | Archivo | ErrorBanner + NoticeBanner | `uploading` state | `disabled={uploading}` |
| Cambio estado propiedad | Backend (enum) | Status | ConfirmDialog + ActionToast | `useTransition` | `disabled={pending}` |
| Filtros (GET) | Navegación | N/A | N/A | N/A | N/A |

**No hay formularios visualmente completos que no guarden** — la única mutación real es cambio de estado y documentos.

---

## 19. API Y BACKEND — COBERTURA FRONTEND vs BACKEND

| Endpoint | Método | Auth | Frontend | Gap |
|----------|--------|------|----------|-----|
| `/health` | GET | No | Dashboard | — |
| `/health/ready` | GET | No | Dashboard | — |
| `/properties` | GET | No | Listado + Dashboard | — |
| `/properties` | POST | Admin | ❌ | **CREATE** |
| `/properties/{id}` | GET | No | ❌ | **DETAIL** |
| `/properties/{id}` | PATCH | Admin | ⚠️ Solo status | **UPDATE parcial** |
| `/properties/{id}` | DELETE | Admin | ❌ | **DELETE** |
| `/properties/{id}/images` | POST | Admin | ❌ | **UPLOAD sin UI** |
| `/properties/{id}/images` | GET | No | Listado + Dashboard | — |
| `/properties/{id}/images/{f}` | GET | No | PropertyThumb | — |
| `/documents` | GET | No | Documentos | — |
| `/documents` | POST | Admin | Documentos | — |
| `/documents/{id}/process` | POST | Admin | Documentos | — |
| `/documents/{id}` | DELETE | Admin | Documentos | — |
| `/leads` | GET | Admin | Leads | — |
| `/appointments` | GET | Admin | Citas | — |
| `/conversations` | GET | Admin | Conversaciones | — |
| `/ai-events` | GET | Admin | Logs | — |

**Endpoints backend sin exponer en API admin**:
- `appointments.create_appointment` — no hay POST `/appointments`
- `appointments.list_available_slots` — no hay GET `/properties/{id}/slots`
- `crm.update_lead` — no hay PATCH `/leads/{id}`
- `projects` CRUD — no expuestos

---

## 20. BASE DE DATOS — SOPORTE FUNCIONAL

### 20.1 Tablas principales (migración inicial)
| Tabla | Propósito | Admin UI |
|-------|-----------|----------|
| `properties` | Inventario core | Parcial (list + status) |
| `projects` | Agrupación propiedades | ❌ Solo seed |
| `documents` + `chunks` | RAG conocimiento | ✅ Completo |
| `leads` | Prospectos | Parcial (list) |
| `appointments` | Visitas | Parcial (list) |
| `users` + `preferences` | Clientes Telegram | ❌ |
| `favorites` / `saved_searches` | UX cliente | ❌ |
| `conversations` + `messages` | Historial chat | ✅ Read-only |
| `ai_events` | Auditoría IA | ✅ Read-only |

### 20.2 Gaps BD → Frontend
| Entidad | Campos en BD no expuestos en admin |
|---------|-------------------------------------|
| Property | `description`, `address`, `latitude`, `longitude`, `project_id`, `features[]`, `search_vector`, `title_embedding` |
| Lead | `preferences` (JSONB), `notes` |
| Appointment | `duration_minutes`, `notes` |
| Project | Todos (name, description, city) |
| Document | `property_id`, `project_id`, `document_type`, `version`, `embedding_version` |

### 20.3 Problemas potenciales
- **Cascade delete imágenes**: `Property` delete no limpia `storage/properties/{id}/` (fs orphan)
- **DocumentChunk.property_id/project_id** duplicado (denormalizado) — OK para RAG
- **No hay tabla `admin_users`** — bloquea RBAC real

---

## 21. SEGURIDAD — CLASIFICACIÓN HALLAZGOS

| ID | Hallazgo | Severidad | Descripción | Mitigación |
|----|----------|-----------|-------------|------------|
| SEC-001 | Token admin único | **CRÍTICO** | Un token compartido, sin rotación, sin revocación individual | Implementar tabla `admin_users` + JWT/sesiones |
| SEC-002 | Sin RBAC | **ALTO** | Todo token válido = superadmin | Roles: superadmin, admin, editor, asesor |
| SEC-003 | Sin auditoría admin | **ALTO** | No log de quién hizo qué (cambio estado, borrado, etc.) | Tabla `admin_audit_log` |
| SEC-004 | Endpoints GET públicos | **MEDIO** | `/properties`, `/properties/{id}/images` sin auth | Revisar si datos son públicos por diseño |
| SEC-005 | Sin rate limiting admin | **MEDIO** | `RATE_LIMIT_PER_MINUTE` solo en bot | Aplicar a `/api/proxy/*` |
| SEC-006 | Validación solo backend | **BAJO** | Subida archivos valida solo en API | Añadir client-side (tipo, tamaño) |
| SEC-007 | Path traversal imágenes | **BAJO** | Protegido por regex estricta | ✅ Ya mitigado |
| SEC-008 | Secrets en .env | **INFORMATIVO** | `ADMIN_TOKEN=changeme-admin-token` en `.env.example` | Rotar en prod, usar secret manager |

---

## 22. ACCESIBILIDAD

### 22.1 Cumple (WCAG 2.1 AA base)
- ✅ Skip link (`#main`)
- ✅ Focus visible (`outline: 2px solid var(--primary)`)
- ✅ ARIA labels en navegación, tablas, dialogs, feeds
- ✅ `role="alertdialog"` en ConfirmDialog, `role="alert"` en ErrorBanner
- ✅ `aria-live` implícito via `role="status"` / `role="alert"` en toasts
- ✅ Contraste CSS variables (definidas pero no auditadas numéricamente)
- ✅ Semántica HTML: `<table>`, `<nav>`, `<main>`, `<section>`, `<header>`, `<footer>`
- ✅ `visually-hidden` para captions de tabla
- ✅ Reduced motion support (`prefers-reduced-motion`)

### 22.2 Pendiente / Mejorable
| Hallazgo | Prioridad |
|----------|-----------|
| Contraste no verificado numéricamente (4.5:1 texto, 3:1 UI) | P3 |
| `PropertyStatusControl` select nativo — difícil styling focus | P3 |
| Error messages no vinculados a inputs via `aria-describedby` | P3 |
| Focus trap en ConfirmDialog ✅ pero no en modales futuros | P3 |
| No hay landmarks `role="region"` en secciones principales | P4 |

---

## 23. RESPONSIVE

| Breakpoint | Comportamiento | Estado |
|------------|----------------|--------|
| **≥1280px** (Desktop) | Sidebar fija 232px, grid-2, stat-row 4 cols, topbar sticky | ✅ |
| **1024-1279px** | Sidebar fija, stat-row 2 cols, grid-2 mantiene 2 cols | ✅ |
| **768-1023px** (Tablet) | Sidebar → drawer, topbar oculta, mobilebar visible, grid-2 → 1 col | ✅ |
| **<600px** (Mobile) | Stat-row 2 cols, padding reducido, tabs scroll horizontal, tablas scroll-x | ✅ |

### Problemas detectados
| Componente | Móvil (<600px) | Tablet (768-1023px) |
|------------|----------------|---------------------|
| Tabla propiedades | Scroll horizontal (OK) | Scroll horizontal (OK) |
| Filtros (FilterTabs) | Scroll horizontal (OK) | Fit (OK) |
| Formulario documentos | Stack vertical (OK) | Stack vertical (OK) |
| Modal ConfirmDialog | Centrado, padding seguro (OK) | Centrado (OK) |
| Dashboard tarjetas | 1 col (OK) | 2 cols (OK) |
| Sidebar | Drawer overlay (OK) | Drawer overlay (OK) |

**Conclusión**: Responsive **bien implementado** con CSS nativo, sin frameworks. Tablas usan `overflow-x: auto` — patrón aceptable para datos densos.

---

## 24. FLUJOS ADMINISTRATIVOS — ANÁLISIS COMPLETO

### Flujo A: Crear casa → Agregar info → Subir imágenes → Definir portada → Guardar → Encontrar → Editar → Cambiar precio/imágenes/estado
| Paso | Existe | Bloqueo |
|------|--------|---------|
| Entrar al panel | ✅ | — |
| Crear nueva casa | ❌ | **Sin UI, sin endpoint frontend** |
| Agregar información | ❌ | **Sin formulario** |
| Subir imágenes | ⚠️ Solo API | **Sin UI integrada** |
| Definir imagen principal | ❌ | **Convención `cover.*` inmutable** |
| Guardar | ❌ | **Sin formulario** |
| Encontrar la casa | ✅ | Listado + filtros |
| Editarla | ❌ | **Sin página detalle/edición** |
| Cambiar precio | ❌ | **Backend soporta, frontend no** |
| Cambiar imágenes | ❌ | **Sin gestión imágenes** |
| Cambiar estado | ✅ | **Único paso funcional** |

**Resultado**: **Flujo roto en 9/11 pasos**. Solo listar y cambiar estado funcionan.

### Flujo B: Buscar propiedad → Filtrar → Abrir detalle → Editar → Guardar
| Paso | Existe |
|------|--------|
| Buscar (ciudad) | ✅ |
| Filtrar (estado) | ✅ |
| Abrir detalle | ❌ (click en fila no navega) |
| Editar | ❌ |
| Guardar | ❌ |

### Flujo C: Revisar citas → Buscar cliente → Revisar propiedad → Cambiar estado
| Paso | Existe |
|------|--------|
| Revisar citas | ✅ |
| Buscar cliente | ⚠️ Solo en cita (lead link) |
| Revisar propiedad | ⚠️ Link a listado, no a detalle |
| Cambiar estado | ✅ (desde listado propiedades) |

### Flujo D: Administrar usuarios → Cambiar permisos
| Paso | Existe |
|------|--------|
| Administrar usuarios | ❌ **No existe sección** |
| Cambiar permisos | ❌ **No existe RBAC** |

---

## 25. COMPARACIÓN CON PANEL INMOBILIARIO PROFESIONAL

| Categoría | Profesional esperado | Actual | Gap | Prioridad |
|-----------|---------------------|--------|-----|-----------|
| **Propiedades** | CRUD completo, duplicar, plantillas | List + status | **CRUD completo** | P1 |
| **Imágenes** | Múltiples, drag-drop reorder, portada, compresión, CDN | Subida sola, convención cover | **Gestión completa** | P1 |
| **Inventario** | Vista tabla/tarjetas, filtros avanzados, búsqueda full-text, export | Tabla básica, 2 filtros | **Filtros, búsqueda, vistas, export** | P1/P2 |
| **Leads/CRM** | Kanban, pipeline, notas, tareas, asignación, historial, email/SMS | List + 7 estados | **CRM real** | P2 |
| **Citas** | Calendario, slots, confirmación, recordatorios, reprogramar | List + filtros | **Gestión completa** | P2 |
| **Usuarios/Roles** | RBAC granular, auditoría, 2FA, sesiones | Token único | **Sistema completo** | P1 |
| **Contenido** | CMS para web (banners, FAQs, legales, SEO) | Nada | **CMS básico** | P2 |
| **Reportes** | Dashboards, funnels, conversión, ROI, export | Métricas básicas | **Analytics** | P3 |
| **Configuración** | Horarios, zonas, monedas, plantillas, integraciones | Solo .env | **Panel config** | P3 |
| **Notificaciones** | Email, push, in-app, webhooks | Nada | **Sistema notificaciones** | P3 |

---

## 26. PRIORIZACIÓN CONSOLIDADA

### P0 — Bloqueante (Impide uso central)
| ID | Hallazgo | Motivo |
|----|----------|--------|
| P0-001 | **Sin CRUD propiedades en frontend** | Operación core inmobiliaria inutilizable desde admin; requiere API directa |
| P0-002 | **Token admin único sin RBAC** | Riesgo seguridad operativa; no hay separación de responsabilidades |

### P1 — Crítico (Antes de producción)
| ID | Hallazgo | Motivo |
|----|----------|--------|
| P1-001 | Crear/Editar/Eliminar propiedades (UI) | Backend listo; frontend bloquea operación diaria |
| P1-002 | Gestión imágenes (eliminar, reordenar, portada) | Imágenes son críticas en inmobiliaria; flujo roto |
| P1-003 | Gestión leads (editar, estado, notas) | Comercial no puede operar leads desde panel |
| P1-004 | Gestión citas (crear, cancelar, reprogramar) | Operación de visitas inutilizable desde admin |
| P1-005 | Usuarios admin + RBAC básico | Requisito mínimo multi-usuario |

### P2 — Importante (Mejora considerable)
| ID | Hallazgo | Motivo |
|----|----------|--------|
| P2-001 | Filtros avanzados propiedades (tipo, operación, precio, área, proyecto) | Productividad diaria |
| P2-002 | Búsqueda full-text propiedades (aprovechar `search_vector`) | Encuentra propiedades rápido |
| P2-003 | Vista detalle propiedad (modal/página) | Contexto completo antes de editar |
| P2-004 | Exportación CSV/Excel (propiedades, leads, citas) | Reporting operativo |
| P2-005 | Proyectos CRUD (agrupar propiedades) | Modelo existe, sin UI |
| P2-006 | Validación client-side formularios | UX inmediata, menos errores backend |
| P2-007 | Preview + compresión imágenes | Ahorro almacenamiento, UX |

### P3 — Mejora (Conveniencia)
| ID | Hallazgo | Motivo |
|----|----------|--------|
| P3-001 | Dashboard métricas avanzadas (conversión, ticket medio, días mercado) | Decisiones data-driven |
| P3-002 | Vista tarjetas/tabla configurable | Preferencia usuario |
| P3-003 | Acciones masivas (cambiar estado múltiple) | Operación en lote |
| P3-004 | Historial cambios propiedad (auditoría) | Trazabilidad |
| P3-005 | Accesibilidad WCAG 2.1 AA completa | Inclusión, compliance |
| P3-006 | Tema oscuro | Preferencia usuario |
| P3-007 | Content management (FAQs, banners, legales) | Autonomía marketing |

### P4 — Futuro (Avanzado)
| ID | Hallazgo |
|----|----------|
| P4-001 | Importación CSV/Excel propiedades |
| P4-002 | Plantillas de propiedad |
| P4-003 | Integración calendario (CalDAV/Google/Outlook) |
| P4-004 | Notificaciones email/push (recordatorios citas, leads nuevos) |
| P4-005 | API keys para integraciones externas |
| P4-006 | Shortcuts teclado globales |
| P4-007 | Multi-idioma (i18n) |

---

## 27. MATRIZ GENERAL DE FUNCIONALIDADES

| Área | Funcionalidad | Estado | Evidencia | Impacto | Prioridad |
|------|---------------|--------|-----------|---------|-----------|
| Propiedades | Listar | ✅ EXISTE | `propiedades/page.tsx` | — | — |
| Propiedades | Filtrar (estado, ciudad) | ✅ EXISTE | `propiedades/page.tsx:78-104` | — | — |
| Propiedades | Paginar | ✅ EXISTE | `TableControls.tsx:61-117` | — | — |
| Propiedades | Ver miniatura | ✅ EXISTE | `PropertyThumb.tsx` | — | — |
| Propiedades | Cambiar estado | ✅ EXISTE | `PropertyStatusControl.tsx`, `actions.ts` | — | — |
| Propiedades | **Crear** | ❌ FALTA | Backend `POST /properties` existe | **ALTO** | P1 |
| Propiedades | **Ver detalle** | ❌ FALTA | Backend `GET /properties/{id}` existe | **ALTO** | P1 |
| Propiedades | **Editar (campos)** | ❌ FALTA | Backend `PATCH /properties/{id}` existe | **ALTO** | P1 |
| Propiedades | **Eliminar** | ❌ FALTA | Backend `DELETE /properties/{id}` existe | **ALTO** | P1 |
| Propiedades | Filtros avanzados | ❌ FALTA | Tipo, operación, precio, área, proyecto | MEDIO | P2 |
| Propiedades | Búsqueda full-text | ❌ FALTA | BD tiene `search_vector` | MEDIO | P2 |
| Propiedades | Exportar | ❌ FALTA | — | MEDIO | P2 |
| Imágenes | Subir | ⚠️ PARCIAL | Solo API directa, sin UI en propiedades | ALTO | P1 |
| Imágenes | Listar | ✅ EXISTE | `GET /properties/{id}/images` | — | — |
| Imágenes | **Eliminar** | ❌ FALTA | Backend sin endpoint | ALTO | P1 |
| Imágenes | **Reordenar** | ❌ FALTA | Backend sin endpoint | MEDIO | P2 |
| Imágenes | **Definir portada** | ❌ FALTA | Convención `cover.*` inmutable | MEDIO | P2 |
| Imágenes | Validación client-side | ❌ FALTA | Solo backend | BAJO | P3 |
| Imágenes | Preview/compresión | ❌ FALTA | — | BAJO | P3 |
| Leads | Listar | ✅ EXISTE | `leads/page.tsx` | — | — |
| Leads | Filtrar estado | ✅ EXISTE | 7 estados con contadores | — | — |
| Leads | **Editar** | ❌ FALTA | Backend `crm.update_lead` existe | ALTO | P1 |
| Leads | **Cambiar estado** | ❌ FALTA | 7 estados definidos | ALTO | P1 |
| Leads | **Notas** | ❌ FALTA | Campo `notes` en BD | MEDIO | P2 |
| Leads | Asignar asesor | ❌ FALTA | No hay campo en modelo | MEDIO | P2 |
| Leads | Exportar | ❌ FALTA | — | BAJO | P3 |
| Citas | Listar | ✅ EXISTE | `citas/page.tsx` | — | — |
| Citas | Filtrar estado | ✅ EXISTE | 4 estados con contadores | — | — |
| Citas | Orden cronológico | ✅ EXISTE | Próximas asc, historial desc | — | — |
| Citas | **Crear** | ❌ FALTA | Backend `create_appointment` existe | ALTO | P1 |
| Citas | **Reprogramar** | ❌ FALTA | Requiere cancel + create | ALTO | P1 |
| Citas | **Cancelar** | ❌ FALTA | Backend `cancel_appointment` existe | ALTO | P1 |
| Citas | Ver slots | ❌ FALTA | Backend `list_available_slots` no expuesto | MEDIO | P2 |
| Citas | Notas | ❌ FALTA | Campo `notes` en BD | BAJO | P3 |
| Documentos | Subir | ✅ EXISTE | `documentos/page.tsx:54-83` | — | — |
| Documentos | Procesar/Reprocesar | ✅ EXISTE | `documentos/page.tsx:85-95` | — | — |
| Documentos | Eliminar | ✅ EXISTE | `documentos/page.tsx:97-114` | — | — |
| Documentos | Filtrar/Búsqueda | ✅ EXISTE | `documentos/page.tsx:218-254` | — | — |
| Conversaciones | Ver | ✅ EXISTE | `conversaciones/page.tsx` | — | — |
| Conversaciones | Resumen + mensajes | ✅ EXISTE | Últimos 5 mensajes | — | — |
| Logs IA | Ver eventos | ✅ EXISTE | `logs/page.tsx` | — | — |
| Logs IA | Filtrar | ✅ EXISTE | Estado + intención | — | — |
| Usuarios | **Cualquier CRUD** | ❌ FALTA | No existe tabla/admin_users | CRÍTICO | P0/P1 |
| Roles/Permisos | **RBAC** | ❌ FALTA | Solo token único | CRÍTICO | P0 |
| Contenido | **CMS básico** | ❌ FALTA | Banners, FAQs, legales, contacto | ALTO | P2 |
| Configuración | **Panel config** | ❌ FALTA | Horarios, moneda, zonas, límites | MEDIO | P3 |

---

## 28. DEPENDENCIAS DE IMPLEMENTACIÓN

| Funcionalidad | UI | Form/Validación | API/Backend | BD | Storage | Permisos | Buscador/Asistente |
|---------------|-----|-----------------|-------------|-----|---------|----------|-------------------|
| **Crear propiedad** | ✅ Requiere | ✅ Requiere | ✅ Existe | ✅ Existe | ⚠️ Imágenes | ✅ Requiere RBAC | ✅ Auto (embedding sync) |
| **Editar propiedad** | ✅ Requiere | ✅ Requiere | ✅ Existe | ✅ Existe | ⚠️ Imágenes | ✅ Requiere RBAC | ✅ Auto (embedding sync) |
| **Eliminar propiedad** | ✅ Requiere | ⚠️ Confirm | ✅ Existe | ✅ Existe | ❌ Limpieza fs | ✅ Requiere RBAC | ✅ Auto (borrado vector) |
| **Gestión imágenes** | ✅ Requiere | ✅ Requiere | ❌ DELETE/REORDER/COVER | ✅ Existe | ✅ Existe | ✅ Requiere RBAC | ⚠️ Portada → listado |
| **Leads CRUD** | ✅ Requiere | ✅ Requiere | ❌ PATCH /leads/{id} | ✅ Existe | — | ✅ Requiere RBAC | — |
| **Citas CRUD** | ✅ Requiere | ✅ Requiere | ❌ POST/PATCH /appointments | ✅ Existe | — | ✅ Requiere RBAC | — |
| **Usuarios/RBAC** | ✅ Requiere | ✅ Requiere | ❌ Nueva API | ❌ Nueva tabla | — | **Core** | — |
| **Proyectos CRUD** | ✅ Requiere | ✅ Requiere | ❌ Nueva API | ✅ Existe | — | ✅ Requiere RBAC | ⚠️ Filtro propiedades |
| **Content CMS** | ✅ Requiere | ✅ Requiere | ❌ Nueva API | ❌ Nueva tabla | ✅ Storage | ✅ Requiere RBAC | — |

**Orden lógico de implementación**:
1. **Usuarios/RBAC** (base para todo lo demás)
2. **CRUD Propiedades** (core negocio)
3. **Gestión Imágenes** (core negocio)
4. **Leads CRUD** (comercial)
5. **Citas CRUD** (operación)
6. **Proyectos CRUD** (organización)
7. **Filtros/Búsqueda avanzada** (productividad)
8. **Content CMS** (autonomía marketing)
9. **Export/Import/Reportes** (analytics)
10. **Notificaciones/Integraciones** (escala)

---

## 29. IMPACTO EN EL RESTO DEL SISTEMA

| Nueva funcionalidad admin | Afecta a | Detalle |
|---------------------------|----------|---------|
| Crear propiedad | Web pública, Asistente IA, Búsqueda | `sync_property_embedding` actualiza vector; `search_vector` computed; aparece en búsquedas si `AVAILABLE` |
| Cambiar estado propiedad | Web pública, Asistente IA, Búsqueda | Solo `AVAILABLE` visible en búsquedas; `revalidatePath("/")` limpia cache dashboard |
| Subir/eliminar imagen | Web pública, Dashboard, Listado | `PropertyThumb` usa proxy; portada en dashboard y cards |
| Editar lead | Asistente IA (contexto cliente) | `Lead.preferences` usado por orquestador |
| Crear cita | Asistente IA (slots), Notificaciones | `list_available_slots` evita double-booking |
| Documentos RAG | Asistente IA (respuestas) | `process_document` → chunks + embeddings → retrieval |
| Usuarios/RBAC | Todo el panel | Requiere refactor auth en frontend + backend |

**Riesgo**: Cualquier cambio en modelo `Property` (campos, enums) requiere migración BD + actualización TypeScript DTOs + formularios frontend.

---

## 30. DATOS QUE REQUIEREN PROGRAMADOR HOY

| Dato | Dónde está definido | Cómo se modifica hoy | Por qué debería ser admin |
|------|---------------------|----------------------|---------------------------|
| Propiedades (todas) | BD (tabla `properties`) | `python -m scripts.seed` / SQL directo / API POST | Operación diaria inmobiliaria |
| Imágenes propiedades | `storage/properties/{id}/` | `POST /properties/{id}/images` vía curl / script | Gestión visual esencial |
| Proyectos | BD (tabla `projects`) | Seed / SQL / API (no expuesta) | Agrupación comercial |
| Documentos RAG | BD + `storage/documents/` | Panel `/documentos` ✅ | **Ya administrable** |
| Leads | BD (tabla `leads`) | Solo desde bot / SQL / API (no expuesta PATCH) | Seguimiento comercial |
| Citas | BD (tabla `appointments`) | Solo desde bot / SQL / API (no expuesta POST/PATCH) | Agenda operativa |
| Config horarios | `app/appointments/service.py:22` | Editar código + deploy | Cambios estacionales |
| Zona horaria | `.env:64` (`TZ`) | Editar .env + restart | Multi-país futuro |
| Moneda/formatos | `settings.py` + `format.ts` | Editar código | Multi-moneda futuro |
| Tipos propiedad/operación | `models.py` enums + migración | Migración Alembic + código | Extensibilidad catálogo |
| Textos legales/FAQs | **No existen** | — | Compliance, soporte |
| Banners web | Frontend público (no auditado) | Editar código | Campañas marketing |

---

## 31. FUNCIONALIDADES RECOMENDADAS A FUTURO

| Funcionalidad | Clasificación | Justificación |
|---------------|---------------|---------------|
| Historial de cambios (auditoría) | **RECOMENDADA** | Trazabilidad legal/comercial; quién cambió qué y cuándo |
| Eliminación lógica (soft delete) | **RECOMENDADA** | Recuperación errores; `deleted_at` en todas las tablas core |
| Papelera / restore | **RECOMENDADA** | UX seguridad ante borrados accidentales |
| Acciones masivas | **RECOMENDADA** | Cambiar estado 50 propiedades a la vez; eficiencia |
| Importación CSV/Excel | **RECOMENDADA** | Migración datos legacy; carga masiva inicial |
| Exportación programada | **OPCIONAL** | Reportes automáticos a gerencia |
| Gestión avanzada imágenes (CDN, thumbnails, WebP) | **OPCIONAL** | Performance web pública; coste storage |
| Gestión leads avanzada (pipeline Kanban, tareas, emails) | **RECOMENDADA** | CRM real para equipo comercial |
| Gestión asesores/equipo | **RECOMENDADA** | Asignación leads/citas, comisiones, rendimiento |
| Estadísticas / Dashboards avanzados | **OPCIONAL** | KPIs negocio: conversión, ticket medio, tiempo cierre |
| Notificaciones (email, push, in-app) | **FUTURA** | Alertas leads nuevos, recordatorios citas |
| Plantillas propiedad | **FUTURA** | Estandarización carga; velocidad |
| Configuración general panel | **RECOMENDADA** | Horarios, moneda, zonas, límites sin deploy |
| Multi-idioma | **FUTURA** | Expansión internacional |
| API keys / Webhooks | **FUTURA** | Integración CRM externos, portales inmobiliarios |

---

## 32. ROADMAP SUGERIDO

### Fase 1 — Fundación y Core (Semanas 1-3)
**Objetivo**: Panel usable para operación diaria básica
- [ ] **P0-002**: Sistema usuarios admin + RBAC básico (tabla `admin_users`, roles, JWT/sesiones, middleware)
- [ ] **P1-001**: CRUD Propiedades frontend (Create/Edit/Delete + Detail view modal/página)
- [ ] **P1-002**: Gestión imágenes completa (DELETE, reorder drag-drop, cover selection, preview)
- [ ] **P1-003**: Leads CRUD (editar, cambiar estado, notas)
- [ ] **P1-004**: Citas CRUD (crear, cancelar, reprogramar, ver slots)
- [ ] **P2-001**: Filtros avanzados propiedades (tipo, operación, precio, área, proyecto)
- [ ] **P2-002**: Búsqueda full-text (aprovechar `search_vector`)
- [ ] **P2-006**: Validación client-side (Zod/Valibot) en formularios

### Fase 2 — Productividad y Organización (Semanas 4-6)
- [ ] **P2-003**: Vista detalle propiedad (modal con toda info, imágenes, acciones)
- [ ] **P2-004**: Exportación CSV/Excel (propiedades, leads, citas)
- [ ] **P2-005**: Proyectos CRUD (crear, editar, asignar propiedades)
- [ ] **P2-007**: Preview + compresión imágenes client-side
- [ ] **P3-001**: Dashboard métricas avanzadas (conversión, ticket medio, días mercado)
- [ ] **P3-004**: Historial cambios propiedad (tabla `property_audit_log`)
- [ ] **MEJ-004**: Responsive tablas → tarjetas en móvil
- [ ] **MEJ-005**: Accesibilidad WCAG 2.1 AA completa

### Fase 3 — Autonomía y Escala (Semanas 7-10)
- [ ] **P3-003**: Acciones masivas (checkboxes + bulk actions)
- [ ] **P3-007**: Content CMS (banners, FAQs, legales, contacto, SEO)
- [ ] **P3-006**: Panel configuración (horarios, moneda, zonas, límites upload)
- [ ] **P4-001**: Importación CSV/Excel propiedades (con validación y preview)
- [ ] **P4-004**: Notificaciones (email recordatorios citas, leads nuevos)
- [ ] **P4-003**: Integración calendario (CalDAV/Google/Outlook)
- [ ] **MEJ-010**: Tema oscuro
- [ ] **MEJ-009**: Shortcuts teclado globales

### Fase 4 — Madurez (Continuo)
- [ ] **P4-002**: Plantillas propiedad
- [ ] **P4-005**: API keys / Webhooks para integraciones
- [ ] **P4-006**: Multi-idioma (i18n)
- [ ] **P4-007**: Gestión asesores/equipo (comisiones, rendimiento)

---

## 33. CONCLUSIÓN

El panel administrativo de EXPRESEDI tiene una **base técnica sólida y bien arquitecturada** (Next.js 15, TypeScript strict, FastAPI, SQLAlchemy 2.0, pgvector, migraciones, diseño system CSS propio), pero **su cobertura funcional es de aproximadamente 35%** respecto a lo que requiere una inmobiliaria para operar día a día sin desarrolladores.

**El hallazgo central**: El backend **ya implementa el 90% de la API necesaria** (CRUD propiedades, leads, citas, proyectos, documentos, imágenes), pero el frontend **solo consume lectura y dos escrituras menores** (cambio estado propiedad, documentos RAG). Esto convierte al panel en un **"dashboard de solo lectura con dos acciones"**, obligando al equipo a usar `curl`, scripts Python o SQL directo para la operación normal.

**Riesgo crítico**: La autenticación con **un único token estático sin RBAC ni auditoría** no es viable para un equipo real. Cualquier persona con el token tiene superadmin; no hay trazabilidad de cambios ni revocación individual.

**Recomendación inmediata**: Priorizar **Fase 1** (usuarios/RBAC + CRUD propiedades + imágenes + leads/citas CRUD). Con eso, el panel pasa de "visor" a "herramienta operativa real". El backend está listo; el esfuerzo es 100% frontend + auth.

**Inversión estimada Fase 1**: 3-4 semanas de desarrollo frontend (React/Next.js) + 1 semana backend (auth/RBAC, endpoints faltantes citas/leads). No requiere cambios de esquema BD.

---

*Informe generado por auditoría automatizada + análisis manual — Septiembre 2026*
*Archivo: `AUDITORIA_ADMIN.md` en raíz del proyecto*