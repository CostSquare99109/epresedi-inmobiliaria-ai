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
