# Seguridad

## Secretos

- Nunca en el código, README, tests ni commits: `NVIDIA_API_KEY`, `TELEGRAM_BOT_TOKEN`, `ADMIN_TOKEN`, contraseñas.
- Toda configuración sale de `.env` (gitignored); `.env.example` documenta las variables.
- El panel admin inyecta el token **server-side** (`admin/.env.local`, gitignored): el navegador nunca lo ve.
- Los logs no escriben secretos (solo longitudes/estados).

## Subida de documentos

`app/rag/ingest.py:validate_document` + `safe_document_path`:

- valida extensión (whitelist: pdf, docx, txt, md);
- valida tamaño (`MAX_UPLOAD_MB`, default 15);
- rechaza vacíos;
- calcula hash sha256 (dedupe + integridad);
- evita path traversal (rechaza `/`, `\`, `..` en el nombre);
- guarda con nombre seguro basado en UUID (nunca el nombre del usuario).
- `detect_mime` sniffea magic bytes (no confía solo en el nombre del cliente).

## Imágenes

`app/api/files.py`:

- whitelist de extensión (.jpg/.jpeg/.png/.webp);
- límite de tamaño;
- nombre seguro secuencial (cover.jpg, 001.jpg…);
- `image_path_or_none` a prueba de path traversal (resuelve solo dentro del directorio de la propiedad).

## Prompt injection (RAG)

Todo documento recuperado es **UNTRUSTED DATA**: texto documental, no instrucciones. No puede cambiar system prompt, permisos, herramientas, configuración ni reglas. El extractor determinista solo cita frases literales. Test dedicado: `tests/test_security.py::test_injected_document_is_data_not_instructions`.

## SQL injection

- Todas las consultas usan parámetros vinculados (`:param`) — ninguna concatenación de entrada del usuario.
- Tests: búsqueda con payloads maliciosos (`'; DROP TABLE…`, `UNION SELECT`) sobrevive y la tabla existe.
- El LLM nunca genera SQL: pasa por tools con filtros estructurados validados.

## Rate limiting

`app/security/ratelimit.py`: token bucket por usuario (Redis, fallback memoria) para Telegram y consultas IA; límites de tamaño para archivos (`MAX_UPLOAD_MB`).

## Privacidad

- No se almacena información innecesaria: memoria persistente solo con preferencias estructuradas observables.
- Aislamiento por usuario: favoritos, búsquedas guardadas y citas siempre filtrados por `user_id` (FK + índices). Tests de aislamiento en `test_crm.py`.
- La API interna expone conversaciones/leads/citas/ai-events solo con el token admin (nunca a usuarios finales).
- Los leads guardan hechos observables (nombre, teléfono dados por el usuario), nunca inferencias del modelo como características objetivas.

## Pentest black-box 2026-09-26 (localhost) — correcciones

Ataque externo autorizado sobre `http://localhost:3000` + API `:8000`, con
re-test posterior. Hallazgos y causa-raíz:

- **V-01 Doble reserva concurrente (Alta)**: `create_appointment` hacía
  check-then-insert sin garantía atómica. Fix: índice único parcial
  `uq_appointments_active_slot (property_id, scheduled_at) WHERE status IN
  (REQUESTED, CONFIRMED)` (migración `0007`) + `IntegrityError → 409` en
  POST/PATCH. Cancelar libera el slot por diseño.
- **V-02 Precio extremo → 500 (Media)**: `price=1e30` excedía `Numeric(14,2)`.
  Fix: cotas `le` en `PropertyIn/PropertyPatch` (`price/rent_price ≤
  999999999999.99`, `area_m2 ≤ 99999999.99`).
- **V-03 Cita en pasado (Media)**: sin validación temporal en creación. Fix:
  `validate_business_hours` rechaza pasado (`past`) y <2h de anticipación
  (`too_soon`, igual que el listado de slots).
- **V-04 Slots inválidos → 500 (Media)**: `OutsideBusinessHours` no se
  capturaba en rutas. Fix: `→ 422` en POST/PATCH.
- **V-05 Sin rate-limit en lectura pública (Media)**: 1 IP degradaba p95 a
  4.5 s. Fix: `RATE_LIMIT_PUBLIC_PER_MINUTE` (default 300) en `GET
  /properties` → 429.
- **V-06 CSRF sin token (Media-Baja)**: solo `SameSite=lax` defendía. Fix:
  middleware `csrf_origin_guard`: mutaciones con `Origin/Referer` fuera de
  `CSRF_TRUSTED_ORIGINS` → 403.
- **V-07 Upload 0 bytes (Baja)**: se aceptaba cover vacía. Fix:
  `save_property_image` exige imagen real (firma JPEG/PNG/WEBP + `PIL.verify`).
- **V-08 Access JWT sobrevive al logout ~1h (Baja, residual aceptado)**:
  JWT stateless; el logout revoca el refresh (`→ 401` al reusar) y el cliente
  descarta el access. Mitigar del todo exige blocklist con estado; se acepta
  la ventana de 1h (access corto) y queda documentada aquí.
