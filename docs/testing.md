# Testing

```bash
python -m pytest tests/ -q
```

155 tests. Base de datos aislada (`inmobiliaria_test`), embeddings locales deterministas, **nunca** NVIDIA ni Telegram reales.

## Aislamiento (conftest.py)

- El entorno se fija ANTES de importar `app.*` para que `get_settings()` (lru_cache) tome la config de test.
- `DATABASE_URL` → `TEST_DATABASE_URL`; storage/documents redirigidos a `storage_test/` y `documents_test/`.
- `LLM_MODE=deterministic`, `EMBEDDING_PROVIDER=local`, tokens vacíos.
- Fixture `prepared_db` (session): crea + migra + siembra la BD exactamente una vez.
- `user_id` único por test (ids nunca colisionan aunque se hagan commits).

## Cobertura por suite

| Suite | Qué cubre |
|---|---|
| `test_database.py` | Migraciones head aplicadas, tablas esperadas, índices, constraints (código único), CRUD, pgvector |
| `test_search.py` | Parsing de precio («300 millones», «1.5», separadores miles), filtros (tipo/operación/habitaciones/baños/parking/área), búsqueda estructurada, disponibilidad (SOLD/RESERVED/INACTIVE ocultos), FTS, vector, búsquedas guardadas, similares |
| `test_rag.py` | Parsing TXT/MD/PDF/DOCX, chunking (tamaño/solapamiento/secciones/hashes estables), validación de archivos, dedupe, versioning, retrieval híbrido, citations |
| `test_agent.py` | Detección de intents (25 casos), attribute question vs nueva búsqueda, tools (search/get/unknown), referencias contextuales (ordinal y precio), preferencias persistentes, fallback menu |
| `test_crm.py` | Favoritos (add/dup/list/remove), aislamiento por usuario, búsquedas guardadas, leads (create/update/status/invalid) |
| `test_appointments.py` | Slots (excluye ocupados y pasados), doble-reserva rechazada, cancelación idempotente, datetime naive→UTC |
| `test_security.py` | Prompt injection (documento inyectado = data, no instrucciones), archivos inválidos (extensión/vacío/tamaño/path traversal), SQL injection (búsqueda y RAG sobreviven), payloads malformados |
| `test_api.py` | Health + ready, CRUD de propiedades (con y sin admin), 401 en endpoints protegidos, documentos (upload/process/delete/extensión), path traversal en imágenes |
| `test_telegram.py` | Keyboards (filas/labels/book_slot), callback roundtrip, registro de comandos, welcome/help, handlers con mocks E2E, rate limit |
| `test_e2e.py` | Flujo completo: búsqueda natural → detalles → guardar → comparar → pregunta de documento (RAG con cita) → financiación → citas vía botones → alertas guardadas → journey completo de la definición de terminado |

## Pruebas de no-alucinación

- «¿Tiene piscina?» sobre una propiedad sin ese dato → «No tengo información confirmada…» (nunca «sí»).
- «¿Cuántos apartamentos tiene el Proyecto Y?» sin documentación → reconocimiento honesto.
- Comparador con <2 opciones → pide más opciones (no inventa).
- Propiedades SOLD/RESERVED/INACTIVE nunca aparecen como disponibles.

## Prueba E2E de RAG

Documento con «El Proyecto X cuenta con 120 apartamentos» → pregunta «¿Cuántos apartamentos tiene el Proyecto X?» → respuesta con el dato + Fuente. Y el caso negativo (Proyecto Y).
