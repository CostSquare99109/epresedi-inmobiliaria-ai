# EPRESEDI — AUDITORÍA DE SEGURIDAD

**Fecha:** 2026-09-26
**Alcance:** Backend FastAPI (`app/`), panel admin (`admin-vite/`), bot Telegram, agente LLM + herramientas, RAG/pgvector, PostgreSQL/Redis, gestión de secretos (`.env`, historial git), dependencias, scripts operativos.
**Repositorio:** github.com/CostSquare99109/epresedi-inmobiliaria-ai (**público** — factor determinante en la severidad de los hallazgos de configuración).
**Método:** auditoría estática de código + verificación controlada no destructiva (tests, inspección de configuración activa, revisión de historial git). Sin pruebas de explotación contra terceros ni servicios en producción.

> Convención de clasificación: **vulnerabilidad confirmada** (reproducida o verificada en configuración activa) / **riesgo probable** (condiciones presentes, explotación no verificada) / **mala práctica** / **informativo** / **falso positivo** (verificado y descartado).
> Severidades: CRÍTICA / ALTA / MEDIA / BAJA / INFO. Los hallazgos corregidos durante la auditoría se marcan `Estado: CORREGIDO` y se detallan en la sección 4.

---

## 1. Resumen ejecutivo

La auditoría encontró **2 vulnerabilidades críticas y 2 altas, todas corregidas durante la propia auditoría**, además de 2 riesgos medios residuales y varios de menor severidad.

El hallazgo dominante fue una **falla sistémica de control de acceso en la API de administración**: cuatro endpoints de gestión (`GET /documents`, `POST /documents/{id}/process`, `DELETE /documents/{id}`, `GET /properties/admin`) carecían de la dependencia `Depends(require_permission(...))` y estaban expuestos **sin autenticación** a cualquiera que alcanzara el puerto 8000. Combinado con un segundo hallazgo crítico — el `JWT_SECRET` no estaba definido en `.env` y la aplicación firmaba tokens con el valor por defecto del código, `changeme-jwt-secret`, en un repositorio público — el panel administrativo estaba efectivamente abierto: un atacante podía **forjar un token de superadmin sin conocer ningún secreto** y, de todos modos, ni siquiera lo necesitaba para listar o borrar documentos del pipeline RAG.

También se confirmó una **IDOR horizontal** en la agenda: `cancel_appointment`/`reschedule_appointment` aceptaban un parámetro `user_scope` que ninguna ruta ni herramienta pasaba (parámetro muerto), de modo que cualquier usuario de Telegram podía cancelar o reprogramar citas ajenas vía el agente. La herramienta del agente ahora filtra por dueño y hay tests de regresión.

El resto del sistema mostró una **postura defensiva sólida**: SQL parametrizado en toda la codebase (ORM + binds, cero concatenación en rutas de usuario), scoping por `user_id` en CRM/memoria, cookies `httponly` sin almacenamiento de tokens en JS, PBKDF2-HMAC-SHA256 con 100k iteraciones, rate limiting por bucket token, filtro de redacción de secretos en logs, lista blanca estricta de campos en el estado conversacional propuesto por el LLM, y defensa contra prompt-injection/traversal/SQLi cubierta por tests. Los falsos positivos investigados (SSRF en websearch, fuga de claves API, scoping de CRM) se documentan en la sección 3.

**Conclusión:** el sistema pasa de "acceso administrativo abierto por defecto" a una postura donde el acceso requiere autenticación y permisos verificados en cada ruta, con 7 tests de regresión nuevos y suite completa en verde (489 passed).

---

## 2. Estadísticas

| Métrica | Valor |
|---|---|
| Archivos de código revisados | ~30 (backend, panel, scripts, config, tests) |
| Hallazgos totales | **20** |
| CRÍTICA | 2 (2 corregidos) |
| ALTA | 2 (2 corregidos) |
| MEDIA | 4 (2 corregidos, 2 pendientes) |
| BAJA | 8 (4 corregidos, 4 pendientes) |
| INFO / higiene | 3 |
| Falsos positificados verificados | 1 (SEC-20) + 3 descartados sin hallazgo (§3 final) |
| Corregidos en esta auditoría | **10** |
| Corregidos post-auditoría | **1** (SEC-11, refresh con rotación/revocación) |
| Tests de regresión añadidos | 7 (auditoría) + 5 (SEC-11) |
| Suite tras correcciones | **500 passed** (0 fallos) |
| Secretos reales filtrados a git | **0** (`.env` nunca commiteado; verificado en historial completo) |

---

## 3. Hallazgos

### SEC-01 — JWT_SECRET con valor por defecto público
- **Severidad:** CRÍTICA | **Categoría:** Vulnerabilidad confirmada | **CWE:** CWE-798 (hardcoded credentials) | **OWASP:** A02 / A05
- **Archivo:** `app/core/settings.py` (default `changeme-jwt-secret`), `.env` (clave ausente) | **Componente:** autenticación admin
- **Descripción:** `JWT_SECRET` no estaba definido en `.env` ni documentado en `.env.example`; la app firmaba y verificaba tokens admin con el valor por defecto del código, visible en un repositorio público.
- **Causa raíz:** default inseguro silencioso + falta de guard de arranque.
- **Evidencia:** `.env` sin `JWT_SECRET`; `get_settings().JWT_SECRET == "changeme-jwt-secret"` en runtime real.
- **Explotación:** firmar localmente un JWT `{"role":"superadmin", ...}` con ese secreto y presentarlo en `Authorization: Bearer` o como cookie `admin_access_token` → acceso total al panel.
- **Impacto:** compromiso total del panel: gestión de usuarios, propiedades, leads, citas, ajustes.
- **Precondiciones:** alcanzar el puerto 8000. **Probabilidad:** trivial.
- **Corrección (aplicada):** `JWT_SECRET` fuerte generado con `secrets.token_urlsafe(48)` y anexado a `.env`; documentado en `.env.example`; guard fail-fast en `main.py:149` (RuntimeError si production conserva el default, warning en dev); test `test_jwt_secret_is_not_the_public_default` en `tests/test_security.py`.
- **Prioridad:** P0 | **Estado: CORREGIDO**

### SEC-02 — DELETE /documents sin autenticación
- **Severidad:** CRÍTICA | **Categoría:** Vulnerabilidad confirmada | **CWE:** CWE-306 | **OWASP:** A01
- **Archivo:** `app/api/routes.py:1198` | **Componente:** API administración / RAG
- **Descripción:** el borrado de documentos no requería sesión ni permiso; cualquier cliente podía eliminar documentos del pipeline RAG por id.
- **Causa raíz:** la ruta se añadió sin `Depends(require_permission(...))`.
- **Evidencia:** test nuevo `test_documents_endpoints_require_admin` (401 sin credenciales; antes de la corrección respondía 200).
- **Explotación:** `DELETE /documents/{uuid}` en bucle → destrucción del corpus de conocimiento del agente.
- **Impacto:** pérdida de disponibilidad/integridad del asistente (DoS de contenido).
- **Precondiciones:** ninguna. **Probabilidad:** trivial.
- **Corrección (aplicada):** `Depends(require_permission("documents.delete"))`.
- **Prioridad:** P0 | **Estado: CORREGIDO**

### SEC-03 — POST /documents/{id}/process sin autenticación
- **Severidad:** ALTA | **Categoría:** Vulnerabilidad confirmada | **CWE:** CWE-306 | **OWASP:** A01
- **Archivo:** `app/api/routes.py:1182` | **Componente:** API administración / RAG
- **Descripción:** re-disparaba la ingesta (parseo + embedding) de cualquier documento por id sin autenticación; vector de gasto de recursos y manipulación del índice.
- **Corrección (aplicada):** `Depends(require_permission("documents.create"))` + cubierto por el test de 401s.
- **Prioridad:** P0 | **Estado: CORREGIDO**

### SEC-04 — GET /documents sin autenticación
- **Severidad:** ALTA | **Categoría:** Vulnerabilidad confirmada | **CWE:** CWE-306 | **OWASP:** A01
- **Archivo:** `app/api/routes.py:1150` | **Componente:** API administración
- **Descripción:** listaba metadatos de todos los documentos ingeridos (nombre de archivo, estado, versión) sin sesión.
- **Corrección (aplicada):** `Depends(require_permission("documents.read"))`; el test e2e existente se actualizó para autenticarse.
- **Prioridad:** P0 | **Estado: CORREGIDO**

### SEC-05 — GET /properties/admin sin autenticación
- **Severidad:** MEDIA | **Categoría:** Vulnerabilidad confirmada | **CWE:** CWE-306 | **OWASP:** A01
- **Archivo:** `app/api/routes.py:571` | **Componente:** API administración
- **Descripción:** inventario administrativo completo (incluye propiedades no publicadas, precios internos) expuesto sin sesión.
- **Corrección (aplicada):** `Depends(require_permission("properties.read"))`; test `test_admin_inventory_requires_admin` (401 sin sesión, 200 con superadmin, `/properties` público sigue 200).
- **Prioridad:** P1 | **Estado: CORREGIDO**

### SEC-06 — IDOR: cancelar/reprogramar citas ajenas vía agente
- **Severidad:** MEDIA | **Categoría:** Vulnerabilidad confirmada | **CWE:** CWE-639 | **OWASP:** A01
- **Archivo:** `app/appointments/service.py:264` (`cancel_appointment`), `:285` (`reschedule_appointment`); `app/agents/tools.py:1079`, `:1166-1176` | **Componente:** agenda / herramientas del agente
- **Descripción:** ambas funciones aceptaban `user_scope` pero **ningún caller lo pasaba** (parámetro muerto): la búsqueda era solo por `appointment_id`, así que un usuario podía actuar sobre citas de otro pasando el id.
- **Evidencia:** tests nuevos: dueño cancela OK (`True`), usuario distinto recibe `False` sin tocar la cita (3 tests, incl. vía `run_tool` con `ToolContext` de un tercero).
- **Explotación:** enumerar ids (UUID v4 → no trivial, pero filtrados en mensajes/chat) o usar un id conocido para cancelar citas de terceros vía el bot.
- **Impacto:** borrado/reprogramación no autorizada de citas comerciales.
- **Corrección (aplicada):** nueva `get_appointment_for_user(session, id, user_scope)` (join con `Lead`, filtra `Lead.user_id`); las herramientas del agente pasan `user_scope=ctx.user_id`; las rutas admin siguen usando el scope global deliberadamente.
- **Prioridad:** P1 | **Estado: CORREGIDO**

### SEC-07 — Permiso huérfano `properties.images` (rutas de imágenes solo para superadmin)
- **Severidad:** BAJA | **Categoría:** Mala práctica (denegación funcional, no fuga) | **CWE:** CWE-276 | **OWASP:** A01
- **Archivo:** `app/api/routes.py` (5 rutas), matriz en `app/security/auth.py` | **Componente:** RBAC
- **Descripción:** 5 rutas pedían `properties.images`, permiso que no existía en la matriz de ningún rol; con el wildcard de superadmin pasaban, pero ADMIN/EDITOR recibían 403. Efecto: funcionalidad rota para roles legítimos, no fuga.
- **Corrección (aplicada):** permisos granulares alineados con la matriz: upload→`images.create`, delete→`images.delete`, reorder/portada/metadata→`images.update`. Test de matriz RBAC (`test_route_permissions_are_covered_by_rbac_matrix`) impide que un permiso de ruta vuelva a quedar sin rol asignado.
- **Prioridad:** P2 | **Estado: CORREGIDO**

### SEC-08 — Endpoints CMS con `NameError` (CmsContent sin importar)
- **Severidad:** BAJA | **Categoría:** Mala práctica / defecto funcional | **CWE:** CWE-754 | **OWASP:** A05
- **Archivo:** `app/api/routes.py` (rutas `/cms-content*`), `app/database/models.py:180,189` | **Componente:** API CMS (WIP)
- **Descripción:** las rutas CMS usaban `CmsContent`/`CmsContentType` sin importarlos → `NameError` → 500 en runtime. No cubierto por tests.
- **Corrección (aplicada):** imports añadidos al módulo de modelos de routes.py.
- **Prioridad:** P3 | **Estado: CORREGIDO**

### SEC-09 — /health/ready filtraba mensajes de error internos
- **Severidad:** BAJA | **Categoría:** Mala práctica | **CWE:** CWE-209 (error information exposure) | **OWASP:** A05
- **Archivo:** `app/api/routes.py` (`/health/ready`) | **Componente:** API
- **Descripción:** incluía `str(e)` de componentes caídos en la respuesta HTTP (rutas de DB, drivers, paths internos).
- **Corrección (aplicada):** la respuesta devuelve solo `f"{type(e).__name__}: componente no disponible"`; el detalle completo queda en `log.warning` del servidor.
- **Prioridad:** P3 | **Estado: CORREGIDO**

### SEC-10 — Inyección de fórmulas CSV en exports
- **Severidad:** BAJA | **Categoría:** Riesgo probable | **CWE:** CWE-1236 | **OWASP:** A03
- **Archivo:** `app/api/routes.py:1920` (`_csv_safe`, aplicado en los 3 exports CSV) | **Componente:** API administración
- **Descripción:** campos controlados por usuarios finales (nombre del lead, notas, texto libre) se volcaban a CSV admin sin neutralizar; al abrir en Excel, un valor tipo `=cmd|...` se ejecuta como fórmula en el equipo del asesor.
- **Precondiciones:** un asesor abre el export en Excel/LibreOffice. **Probabilidad:** baja, pero real (el lead inicial lo controla cualquiera que escriba al bot).
- **Corrección (aplicada):** `_csv_safe()` prefija `'` ante valores que empiezan por `= + - @ \t \r` (convención OWASP).
- **Prioridad:** P2 | **Estado: CORREGIDO**

### SEC-11 — Refresh token de larga vida sin rotación ni revocación
- **Severidad:** MEDIA | **Categoría:** Riesgo probable | **CWE:** CWE-613 | **OWASP:** A07
- **Archivo:** `app/security/auth.py` (refresh ~30 días), `admin-vite/src/api/auth.ts` | **Componente:** sesión admin
- **Descripción:** el refresh token no se rota en uso y no existe denylist/revocación real; `POST /auth/logout` borra cookies pero el refresh sigue siendo válido si fue robado. Un XSS o robo de cookie persistente mantiene acceso ~30 días.
- **Corrección (aplicada 2026-09-26, post-auditoría):** refresh con `jti` único por emisión (`auth.py:create_refresh_token`); denylist Redis `revoked:refresh:{jti}` con TTL = vida restante y fallback en memoria (`revoke_refresh_token`/`is_refresh_token_revoked`); `/auth/refresh` con rotación de un solo uso — el token presentado se revoca al consumirse y su reuso es 401 auditado como posible robo; `/auth/logout` idempotente que revoca el refresh de la cookie aunque el access haya expirado; tokens legacy sin `jti` se rechazan (re-login único tras deploy). Tests: rotación/reuso, logout revoca, logout sin sesión, legacy rechazado, fallback en memoria (5 nuevos; suite 500 passed).
- **Prioridad:** P1 | **Estado: CORREGIDO**

### SEC-12 — Sin bloqueo de cuenta tras intentos fallidos
- **Severidad:** MEDIA | **Categoría:** Riesgo probable | **CWE:** CWE-307 | **OWASP:** A07
- **Archivo:** `app/security/auth.py` (`/auth/login`) | **Componente:** autenticación admin
- **Descripción:** existe rate limit 10/min **por IP**, pero no lockout por cuenta: con rotación de IPs (proxies) es viable fuerza bruta distribuida contra una cuenta conocida.
- **Corrección propuesta:** contador por cuenta + bloqueo temporal exponencial + notificación; mantener el límite por IP como primera capa.
- **Prioridad:** P1 | **Estado: PENDIENTE**

### SEC-13 — Upload validado solo por extensión; `detect_mime` es código muerto
- **Severidad:** BAJA | **Categoría:** Mala práctica | **CWE:** CWE-434 | **OWASP:** A04
- **Archivo:** `app/rag/parsing.py:109` (`detect_mime`, nunca llamado), `app/rag/ingest.py:29` (`validate_document`) | **Componente:** ingesta RAG
- **Descripción:** la validación confía en la extensión del nombre; existe una función de sniffing de magic bytes (`%PDF`, `PK\x03\x04`) pero **no está conectada**. Riesgo residual bajo: subir requiere permiso `documents.create` (solo admin/editor) y el parser `pypdf`/`zipfile` rechaza contenido no válido.
- **Corrección propuesta:** llamar `detect_mime` dentro de `validate_document` (eximir `.txt`/`.md`).
- **Prioridad:** P3 | **Estado: PENDIENTE**

### SEC-14 — Swagger /openapi.json expuesto sin autenticación
- **Severidad:** BAJA | **Categoría:** Mala práctica | **CWE:** CWE-200 | **OWASP:** A05
- **Archivo:** `app/api/routes.py` (app FastAPI) | **Componente:** API
- **Descripción:** `/docs`, `/redoc` y `/openapi.json` públicos. Aceptable en dev (127.0.0.1); en despliegue público revela el mapa completo de endpoints.
- **Corrección:** ya mitigado en código — `_fastapi_kwargs()` (`app/api/routes.py:72`) fija `docs_url/redoc_url/openapi_url=None` cuando `APP_ENV=production`.
- **Prioridad:** P3 | **Estado: MITIGADO (verificado en código durante el fix de SEC-11)**

### SEC-15 — Sin cabeceras de seguridad HTTP
- **Severidad:** BAJA | **Categoría:** Mala práctica | **CWE:** CWE-693 | **OWASP:** A05
- **Archivo:** `app/api/routes.py` (sin middleware de cabeceras) | **Componente:** API / panel
- **Descripción:** no se emiten `Content-Security-Policy`, `X-Frame-Options`/`frame-ancestors`, `HSTS` ni `X-Content-Type-Options: nosniff`. El panel es un SPA de confianza propia, pero el endurecimiento es estándar.
- **Corrección propuesta:** middleware `SecurityHeaders` condicionado a `APP_ENV=production` (HSTS solo con HTTPS real).
- **Prioridad:** P3 | **Estado: PENDIENTE**

### SEC-16 — python-jose en modo mantenimiento
- **Severidad:** BAJA | **Categoría:** Mala práctica (componente) | **CWE:** CWE-1104 | **OWASP:** A06
- **Archivo:** `app/security/auth.py:9` (`from jose import jwt`) | **Componente:** autenticación
- **Descripción:** `python-jose==3.5.0` (incluye los parches de CVE-2024-33663/33664) está instalado pero en mantenimiento; `pyjwt==2.13.0` ya está disponible en el entorno.
- **Corrección propuesta:** migrar a `pyjwt` (misma superficie, API estable).
- **Prioridad:** P3 | **Estado: PENDIENTE**

### SEC-17 — Artefactos de runtime versionados en git (`dump.rdb`, `cookies.txt`)
- **Severidad:** INFO (higiene) | **Categoría:** Mala práctica | **CWE:** CWE-200 | **OWASP:** A05
- **Archivo:** raíz del repo | **Componente:** control de versiones
- **Descripción:** ambos ya están en `.gitignore` pero fueron añadidos antes de ignorarlos, así que siguen **tracked**. `cookies.txt` solo contiene comentarios de cabecera; `dump.rdb` es un snapshot de Redis (podría contener colas/mensajes del momento del commit; el actual es dato de desarrollo).
- **Corrección propuesta (no ejecutada — requiere commit autorizado):**
  ```
  git rm --cached dump.rdb cookies.txt
  git commit -m "chore: remover artefactos de runtime del control de versiones"
  ```
- **Prioridad:** P3 | **Estado: PENDIENTE (acción documentada; no se ejecutó por política de no-commit sin autorización)**

### SEC-18 — Sourcemaps del panel publicados en el repo
- **Severidad:** INFO | **Categoría:** Informativo | **OWASP:** A05
- **Archivo:** `admin-vite/vite.config.ts` (`sourcemap: true`) + `admin-vite/dist/*.map` tracked | **Componente:** panel
- **Descripción:** los `.map` exponen el código fuente completo del panel. El repo ya es público, así que no constituye fuga adicional; se recomienda `sourcemap: "hidden"` o despublicar `dist/`.
- **Prioridad:** P4 | **Estado: PENDIENTE**

### SEC-19 — `ADMIN_TOKEN` legacy persistente
- **Severidad:** INFO | **Categoría:** Higiene de configuración | **OWASP:** A05
- **Archivo:** `app/core/settings.py`, `.env`, `tests/conftest.py` | **Componente:** configuración
- **Descripción:** el flujo X-Admin-Token/ADMIN_TOKEN fue eliminado del código productivo; la variable solo se usa en tests. Marcado como LEGACY en `.env.example` durante esta auditoría.
- **Corrección propuesta:** renombrar el uso de tests a `TEST_ADMIN_TOKEN` y eliminar `ADMIN_TOKEN` de settings.
- **Prioridad:** P4 | **Estado: PENDIENTE**

### SEC-20 — `.env` con credenciales reales en el working dir
- **Severidad:** FALSO POSITIVO (verificado) | **Categoría:** Falso positivo | **OWASP:** A05
- **Descripción:** `.env` contiene `TELEGRAM_BOT_TOKEN` y `NVIDIA_API_KEY` reales ([REDACTED]). **Verificación:** `.env` está en `.gitignore` desde el primer commit y `git log -p --all` con patrones `nvapi-` y de token de Telegram devuelve 0 coincidencias reales (los 36 matches eran identificadores de código como `nva_configured`). No hubo fuga.
- **Prioridad:** — | **Estado: DESCARTADO**

**Falsos positivos adicionales descartados sin hallazgo:**
1. *SSRF en websearch* — `app/agents/websearch.py` solo consulta HTML de DuckDuckGo; no hay URLs arbitrarias controlables por el usuario final.
2. *Scoping CRM/memoria* — todas las queries filtran por `user_id`/`conversation_id`; `AppUser.id` = Telegram id (no ids secuenciales adivinables).
3. *Fuga de claves en logs* — `app/core/logging.py` redacta `api_key|token|password|secret|authorization` y `app/ai/llm.py` nunca registra la clave.

---

## 4. Vulnerabilidades corregidas (detalle de cambios)

| # | Archivo | Cambio |
|---|---|---|
| 1 | `.env` | `JWT_SECRET` fuerte (48 bytes url-safe) generado con `secrets` y anexado sin mostrarlo en pantalla |
| 2 | `.env.example` | `JWT_SECRET` documentado + `ADMIN_TOKEN` marcado LEGACY |
| 3 | `main.py:146-159` | Guard fail-fast: `RuntimeError` en production con el default; warning en dev |
| 4 | `app/api/routes.py:1150` | `GET /documents` → `documents.read` |
| 5 | `app/api/routes.py:1182` | `POST /documents/{id}/process` → `documents.create` |
| 6 | `app/api/routes.py:1198` | `DELETE /documents/{id}` → `documents.delete` |
| 7 | `app/api/routes.py:571` | `GET /properties/admin` → `properties.read` |
| 8 | `app/api/routes.py` (5 rutas) | `properties.images` → `images.create` / `images.delete` / `images.update` |
| 9 | `app/api/routes.py` | imports `CmsContent`, `CmsContentType` (fix NameError CMS) |
| 10 | `app/api/routes.py` `/health/ready` | error enmascarado en respuesta; detalle solo en log |
| 11 | `app/api/routes.py:1920` | `_csv_safe()` + aplicado a los 3 exports CSV |
| 12 | `app/appointments/service.py:250` | `get_appointment_for_user()` con join a `Lead` y filtro por dueño |
| 13 | `app/appointments/service.py:264,285` | `cancel`/`reschedule` respetan `user_scope`; `get_appointment` duplicada consolidada |
| 14 | `app/agents/tools.py:1079,1166,1176` | herramientas del agente pasan `user_scope=ctx.user_id` |
| 15 | `tests/test_appointments.py` | 3 tests: cancel/reprogramar scoped al dueño, incl. vía herramienta del agente |
| 16 | `tests/test_api.py` | GET /documents autenticado en e2e existente + 2 tests nuevos de 401/200 |
| 17 | `tests/test_security.py` | test matriz RBAC (permisos de ruta cubiertos por roles) + test JWT_SECRET no-default |
| 18 | `app/security/auth.py` | `jti` en refresh + denylist Redis/memoria (`revoke/is_refresh_token_revoked`) (SEC-11) |
| 19 | `app/api/routes.py` `/auth/refresh`, `/auth/logout` | rotación de un solo uso con auditoría de reuso + logout idempotente que revoca (SEC-11) |
| 20 | `tests/test_api.py`, `tests/test_security.py` | 5 tests de sesión SEC-11 (rotación, logout, legacy, fallback) |

**Verificación:** `python -m pytest tests/ -q` → **500 passed** (incluye 7 tests de la auditoría + 5 de SEC-11; antes de las correcciones, los tests de 401 fallaban contra las rutas abiertas, confirmando el hallazgo). `ruff check` sobre los archivos tocados: solo findings pre-existentes del estilo del repo (B008 `Depends(...)`, etc.); el nuevo fallback Redis/memoria replica el patrón de `ratelimit.py`.

---

## 5. Riesgos pendientes (roadmap)

| ID | Riesgo | Severidad | Acción |
|---|---|---|---|
| SEC-12 | Sin lockout por cuenta | MEDIA | Contador por email + bloqueo exponencial |
| SEC-13 | `detect_mime` desconectado | BAJA | Llamarlo desde `validate_document` |
| SEC-14 | Swagger en producción | — | Ya mitigado (`_fastapi_kwargs`, verificado) |
| SEC-15 | Sin cabeceras de seguridad | BAJA | Middleware condicional |
| SEC-16 | python-jose en mantenimiento | BAJA | Migrar a pyjwt |
| SEC-17/18/19 | Higiene de repo/config | INFO | `git rm --cached` (con commit), sourcemaps hidden, retirar ADMIN_TOKEN |

---

## 6. Dependencias

Versiones instaladas relevantes (sin CVE conocidos aplicables a estas versiones exactas; `python-jose==3.5.0` ya incluye los fixes 2024): `fastapi 0.133.1`, `uvicorn 0.41.0`, `sqlalchemy 2.0.52`, `pydantic 2.13.4`, `pypdf 6.19.0`, `python-telegram-bot 22.6`, `alembic 1.13.3`, `redis 8.1.0`, `httpx 0.28.1`, `aiohttp 3.14.1`, `python-multipart 0.0.32`. Recomendación: ejecutar `pip-audit` y `npm audit` en un entorno con red como verificación periódica (no ejecutado aquí por entorno sin salida a red garantizada).

---

## 7. Secretos

- `.env` contiene credenciales reales de Telegram y NVIDIA ([REDACTED]); **nunca fue commiteado** (verificado contra el historial completo con patrones de ambos formatos).
- `JWT_SECRET` ahora es fuerte y único por despliegue; `.env.example` documenta cómo generarlo (`python -c "import secrets; print(secrets.token_urlsafe(48))"`).
- No hay secretos en `dump.rdb`/`cookies.txt` (inspeccionados), ni en logs (filtro de redacción), ni en el frontend (cookies httponly, cero tokens en JS/localStorage).

---

## 8. Autenticación y autorización (estado post-fix)

- **Contraseñas:** PBKDF2-HMAC-SHA256, 100k iteraciones; política mínima 8 chars en `create_admin`.
- **Sesión:** JWT acceso (cookie httponly `admin_access_token`, SameSite=lax) + refresh; `secure` solo en producción.
- **RBAC:** `superadmin > admin > editor > asesor` con matriz `PERMISSIONS` y wildcards `modulo.*`; **toda ruta de administración ahora tiene `require_permission`** (la matriz completa de rutas fue revisada endpoint por endpoint).
- **Agent/Telegram:** no expone superficie admin; las herramientas de citas operan scoped al `ctx.user_id`.
- **Pendiente:** rotación/revocación de refresh (SEC-11) y lockout (SEC-12).

---

## 9. Agente LLM y herramientas

- Validación crítica en código, no en el LLM: precios, disponibilidad, horarios y slots se validan en `app/appointments/service.py`/`bizconfig.py`; el modelo no puede inventar `max_price`/`min_price` ni ranking de cercanía (invariantes con tests).
- El estado conversacional propuesto por el LLM pasa por whitelist de campos con validación de tipos/rangos/enums (`app/agents/state.py`), nunca corrompe estado.
- Inyección de prompts: mitigada por system prompt + sandbox de herramientas + límites de tokens por resultado; cubierta en `tests/test_security.py`.
- RAG: ingesta requiere permiso admin (post-fix); envenenamiento del corpus requeriría credenciales comprometidas (riesgo residual aceptable, monitorizable vía audit log).

---

## 10. Infraestructura y despliegue

- Postgres/Redis locales (repo-local `./pgdata`, sin SSL — aceptable en red local; en despliegue real exigir TLS).
- `main.py` auto-arranca infra, corre migraciones y verifica pgvector; el nuevo guard de `JWT_SECRET` bloquea arranque en production con defaults.
- Exposición: API en `:8000` (bind por defecto — en despliegue, limitar a 127.0.0.1 o tras proxy con TLS).
- `.gitignore` correcto para `.env`, `pgdata/`, `storage/`, `documents/**`; faltan des-trackear `dump.rdb`/`cookies.txt` (SEC-17).

---

## 11. Pruebas ejecutadas

| Comando | Resultado |
|---|---|
| `python -m pytest tests/ -q` | **500 passed**, 0 failed |
| `python -m pytest tests/test_security.py tests/test_api.py tests/test_appointments.py -q` | 79 passed |
| `ruff check` (archivos tocados) | solo findings pre-existentes (B008/estilo repo), 0 nuevos |
| `python -m py_compile` (7 archivos modificados) | OK |
| `git log -p --all` + patrones de secretos | 0 filtraciones |
| `git ls-files` artefactos | `dump.rdb`, `cookies.txt` tracked (SEC-17) |

Tests nuevos de regresión (12): 3 IDOR de citas (servicio + herramienta del agente), 2 API auth (401s de documentos, inventario admin protegido con `/properties` público intacto), 1 matriz RBAC vs rutas, 1 JWT_SECRET no-default, y 5 de sesión SEC-11 (rotación/reuso, logout revoca, logout sin sesión, legacy sin jti, fallback en memoria).

---

## 12. Recomendaciones

**Inmediatas (hoy):**
1. Desplegar los fixes (ya en working tree, sin commitear — decidir commit/PR cuando el equipo lo autorice).
2. Confirmar en el entorno real que `main.py` arranca con el `JWT_SECRET` nuevo (el guard avisa si no).

**Corto plazo (1-2 semanas):**
3. SEC-11: rotación y revocación de refresh tokens.
4. SEC-12: lockout por cuenta.
5. SEC-17: `git rm --cached dump.rdb cookies.txt` + commit.
6. `pip-audit`/`npm audit` en CI.

**Medio plazo:**
7. SEC-13/14/15/16: magic bytes, Swagger off en prod, cabeceras de seguridad, migración a pyjwt.
8. Cobertura de tests RBAC para todas las rutas (extender el test de matriz).
9. Retirar `ADMIN_TOKEN` (SEC-19) y sourcemaps del repo (SEC-18).

---

## 13. Veredicto

**Estado pre-auditoría: NO APTO** — acceso administrativo forjable sin secretos y endpoints de gestión sin autenticación en un repositorio público.
**Estado post-correcciones: APTO CON CONDICIONES** — las 4 puertas abiertas críticas/altas están cerradas y cubiertas por tests de regresión; la postura defensiva del resto del sistema es sólida. Las condiciones para mantener la aptitud son: desplegar los fixes tal cual (sin regresar los `Depends`), mantener `JWT_SECRET` fuera del repo con el guard activo, y ejecutar el roadmap de la sección 5 (SEC-12 primero).

---

*Auditado y corregido en sesión del 2026-09-26. Los cambios están en el working tree sin commitear, a la espera de autorización (ver sección 12).*
