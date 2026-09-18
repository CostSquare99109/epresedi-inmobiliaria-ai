# Auditoría de datos demo / hardcodeados

Fecha: 2026-09-17 · Alcance: backend Python (`app/`, `main.py`, `scripts/`, `migrations/`) + panel Next.js (`admin/`) + configuración (`.gitignore`, `.env`) + contenido real de las bases de datos.

## 1. Resumen

El proyecto **ya estaba mayoritariamente limpio**: no había mocks, fixtures ni respuestas simuladas en la ruta de datos real. La única fuente de datos ficticios es el **seed de desarrollo** (`scripts/seed.py`), legítimo para dev/test pero con un problema serio de seguridad: **vaciaba todas las tablas sin ninguna guardia de entorno**.

Se corrigieron 5 hallazgos (1 crítico de integridad de datos, 1 de claridad de código, 3 de higiene). No se eliminó ni un dato legítimo de negocio, enum, regla ni constante técnica.

| Métrica | Valor |
|---|---|
| Archivos inspeccionados | 43 Python + 35 TS/TSX + 8 config/docs + 2 bases de datos |
| Problemas detectados | 5 |
| Problemas corregidos | 5 |
| Mocks de producción eliminados | 0 (no existían) |
| Datos hardcodeados de negocio eliminados | 0 (los encontrados eran legítimos) |
| Endpoints corregidos | 0 |
| Componentes corregidos | 3 (textos de empty state) |
| Servicios corregidos | 1 (`scripts/seed.py`, guardia) |
| Secretos encontrados | 0 hardcodeados en código |

## 2. Flujo de datos verificado (realidad, no apariencia)

```
PostgreSQL (pgvector) → app/<dominio>/service|repository → app/api/routes.py
    → admin/src/lib/backend.ts (server-side, X-Admin-Token) → Server Components → UI
Mutaciones del panel: admin/src/app/propiedades/actions.ts (Server Action)
    → PATCH /properties/{id} → repository → BD
Bot Telegram: handlers → orchestrator → tools → services → BD
```

- El panel **no tiene datos propios**: cada KPI, tabla y tarjeta se calcula en el servidor a partir de respuestas del backend (verificado en `admin/src/app/page.tsx`: `byStatus`, `upcoming`, `staleNewLeads`, `failedDocs` derivan de los DTO reales).
- Nada en `admin/` importa `data/`, `mock/` ni `fixtures/`: **no existen tales directorios**.

## 3. Problemas encontrados y corregidos

### 3.1 CRÍTICO — `scripts/seed.py` borraba todas las tablas sin guardia

El seed ejecuta un *wipe* de `Message, AiEvent, Appointment, Favorite, SavedSearch, Lead, UserPreference, Conversation, DocumentChunk, Document, Property, Project` antes de sembrar. No comprobaba el entorno: un `python -m scripts.seed` apuntando a una instalación real habría borrado leads, citas, conversaciones y auditoría de IA de verdad, sin aviso.

**Corregido** con `_assert_safe_to_wipe()` (llamada al inicio de `seed()`): aborta con `SystemExit` si `APP_ENV=production`/`prod`, salvo `SEED_ALLOW_PRODUCTION=1` explícito. Docstring del módulo reescrito para declarar que es un seed de **desarrollo/test** y destructivo.

### 3.2 Claridad — `_FakeProp` parecía un mock y no lo era

`app/agents/orchestrator.py` envolvía resultados reales (`Property.to_dict()`) en una clase llamada `_FakeProp` para reutilizar los helpers de formato. **No contenía datos falsos**, pero el nombre es una trampa para cualquier auditoría futura. Renombrada a `_PropView` (6 referencias) con docstring que aclara que es un adaptador de presentación.

### 3.3 UI — andamiaje de desarrollo filtrado en el panel

Tres textos de empty state instruían ejecutar el seed de desarrollo dentro de la interfaz del producto:

| Archivo | Antes | Después |
|---|---|---|
| `admin/src/app/propiedades/page.tsx` | «Ejecuta el seed de datos (python -m scripts.seed) o crea propiedades desde la API.» | «Carga las propiedades desde la API de administración y aparecerán aquí automáticamente.» |
| `admin/src/app/page.tsx` (inventario vacío) | «Ejecuta el seed de datos (python -m scripts.seed) o crea propiedades desde la API para comenzar.» | idem |
| `admin/src/app/page.tsx` (tira de atención) | «ejecuta el seed de datos o crea propiedades vía API» | «carga el inventario desde la API de administración» |

Los empty states siguen siendo honestos (FASE 25/26): explican la ausencia de datos y la acción real disponible, sin referenciar la herramienta de desarrollo.

### 3.4 Higiene — artefactos de seed/test no ignorados por git

`.gitignore` **no** cubría `documents/` (donde el seed genera `reglamento_proyecto_x.pdf`, `ficha_villas_de_carepa.docx`, `normativa_mascotas.md`, `contrato_arrendamiento.txt`), ni `documents_test/`, ni `storage_test/` (1573 archivos acumulados), ni `*.tsbuildinfo`. Añadidos, preservando `.gitkeep`.

### 3.5 Higiene — `.pyc` huérfano

`tests/__pycache__/test_smoke_tmp.cpython-314-pytest-9.1.1.pyc` existía sin su `tests/test_smoke_tmp.py`. Eliminado (artefacto de build, ya ignorado por git).

## 4. Datos que eran legítimos (NO se tocaron)

- **Enums de estado** (`AVAILABLE/RESERVED/SOLD/INACTIVE`, `NEW/CONTACTED/...`, `REQUESTED/CONFIRMED/...`, `READY/PROCESSING/PENDING/FAILED`) y sus etiquetas en español (`app/bot/formatting.py`, `admin/src/lib/status.ts`, `admin/src/app/*/page.tsx`): son reglas de negocio, no datos.
- **Constantes de negocio/técnicas**: `PAGE_SIZE=12`, `STALE_LEAD_HOURS=72`, `MAX_UPLOAD_MB=15`, `EMBEDDING_DIM`, radios/espaciados/sombras del design system.
- **Catálogos de intents** (`INTENT_LABELS`, `intentLabel`) y operaciones (`SALE/RENT`).
- **`admin/src/**/placeholder=`** en inputs: son ayudas de formulario, no datos ficticios.
- **`app/bot/formatting.py` → `"No informado"` / `fmt_opt`**: fallback honesto para un campo nulo, no inventa valor.
- **`return []` en `rag/retrieval.py` y `api/files.py`**: respuesta semánticamente correcta (sin resultados), no relleno.
- **Rechazos del orquestador** («No encontré propiedades disponibles con esos criterios…», «No tengo información confirmada sobre eso en los documentos.»): anti-alucinación deliberada — el sistema prefiere decir que no sabe antes que inventar.
- **`app/ai/llm.py`**: proveedor NVIDIA real, credenciales solo desde settings, `LLMError` explícito con el comentario *«Never swallowed into a fabricated answer»*. Sin respuestas simuladas.
- **`app/agents/orchestrator.py`** en modo determinista: renderiza **resultados reales** de tools (`search_properties`, `property_details`, `compare_properties`), sin LLM y sin datos de relleno.
- **Textos de diagnóstico operativo** (`python main.py` en el error de `/health/ready`): el panel es interno/local por diseño; se conservaron como ayuda real de troubleshooting.
- **Seeds/migraciones**: `migrations/versions/*.py` (esquema real), `scripts/doctor.py`, `scripts/ingest.py`.

## 5. Datos que permanecen únicamente para tests / desarrollo

| Artefacto | Destino | Por qué es legítimo |
|---|---|---|
| `scripts/seed.py` | `inmobiliaria` (dev) y `inmobiliaria_test` (tests) | Seed declarado de dev/test; ahora con guardia de entorno |
| `tests/conftest.py` | Fuerza `DATABASE_URL=TEST_DATABASE_URL` (`inmobiliaria_test`), `STORAGE_PATH=storage_test`, `DOCUMENTS_PATH=documents_test`, `LLM_MODE=deterministic`, sin red | Aislamiento explícito antes de importar `app.*` |
| `documents/inbox/*.{pdf,docx,md,txt}` | Ingesta RAG del seed | Documentos sintéticos de dev (4) — ahora ignorados por git |
| `storage/properties/**/cover.jpg` | Portadas de las 16 propiedades del seed | JPEG sintéticos generados con Pillow (color + texto del código), **no son fotos reales** |
| `documents_test/`, `storage_test/` | Suite pytest | Artefactos de test, ahora ignorados por git |

**Estado real de la BD de desarrollo** (`inmobiliaria`), verificado: `projects=3`, `properties=16`, `documents=4` → **exactamente el seed**. En cambio `leads=2`, `appointments=2`, `conversations=35`, `ai_events=135` **no los crea el seed** (el seed solo los borra), por lo que son **registros reales** de uso del bot y de la API. Esto es precisamente lo que la guardia del punto 3.1 protege.

## 6. Secretos y configuración

- `grep` de `api_key|token|password|secret` con valores literales en `app/`, `main.py`, `scripts/`, `admin/src/`: **sin resultados**. Todo pasa por `get_settings()` / `process.env`.
- `.env` y `admin/.env.local` están en `.gitignore`; el navegador nunca recibe `ADMIN_TOKEN` (se inyecta server-side en `admin/src/lib/backend.ts` y en el proxy).
- `NVIDIA_API_KEY`, `TELEGRAM_BOT_TOKEN`, `ADMIN_TOKEN` se leen solo de entorno.

## 7. Validación ejecutada

| Verificación | Comando | Resultado |
|---|---|---|
| Sintaxis Python | `python3 -m py_compile scripts/seed.py app/agents/orchestrator.py main.py migrations/env.py` | **PASS** |
| Guardia del seed (producción) | `APP_ENV=production … _assert_safe_to_wipe()` | **aborta** con mensaje explícito |
| Guardia del seed (desarrollo/test) | `APP_ENV=development …` | **pasa** |
| Guardia del seed (override) | `APP_ENV=production SEED_ALLOW_PRODUCTION=1 …` | **pasa** |
| Suite backend | `python -m pytest tests/ -q` | **169 passed** (13.75 s) |
| Aislamiento de la BD de desarrollo | conteos antes/después de pytest | **sin cambios** (3/16/2/35) |
| Typecheck panel | `node node_modules/typescript/bin/tsc --noEmit` | **PASS** (exit 0) |
| Build panel | `next build` | **PASS** |
| Residuos demo | `grep -RniE 'demo\|mock\|fake\|dummy\|sample\|lorem\|hardcoded'` en `app/`, `scripts/`, `admin/src/` | solo falsos positivos legítimos (ver §4) |

## 8. Riesgos pendientes (no corregidos, a propósito)

1. **El seed sigue siendo destructivo por diseño** (idempotencia para dev/test). La guardia evita producción, pero ejecutarlo con `APP_ENV=development` apuntando a una BD con datos reales seguiría borrando. Recomendación: usar siempre una BD dedicada de dev.
2. **Los datos de la BD de desarrollo son del seed** (16 propiedades ficticias, 3 proyectos, 4 documentos y portadas sintéticas). No deben promoverse a producción: allí el inventario debe cargarse desde la API con inmuebles reales y fotos reales.
3. **`ADMIN_TOKEN` por defecto** (`changeme-admin-token` en `settings.py` y `.env`): hay que rotarlo en cualquier despliegue real.
4. **El panel no tiene login propio** (documentado en `docs/admin-panel.md` §6): protección solo arquitectónica (token server-side + `noindex` + uso interno/local).
5. **No existe UI para crear propiedades**: el panel hoy consulta y cambia estado; la carga inicial se hace por API (`POST /properties`). Es una carencia funcional real, no un dato ficticio, y por eso los empty states remiten a la API.