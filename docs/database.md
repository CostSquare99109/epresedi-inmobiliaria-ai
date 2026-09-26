# Base de datos

PostgreSQL + pgvector, todo local. Esquema gestionado por Alembic (`migrations/versions/`).

## Esquema (13 tablas)

| Tabla | Propósito |
|---|---|
| `properties` | Inventario (código único, tipo, operación, precio, ubicación, estado, features JSONB) |
| `documents` | Documentos RAG (hash único, versión, estado, embedding_version) |
| `document_chunks` | Chunks con embedding vector(256), página, sección, hash |
| `users` | Usuarios de Telegram (id = telegram_user_id) |
| `user_preferences` | Preferencias persistentes (ciudad, presupuesto, tipo, habitaciones…) |
| `conversations` | Conversaciones con estado JSONB (last_results, last_property_id…) y resumen |
| `messages` | Mensajes (USER/ASSISTANT) por conversación |
| `ai_events` | Auditoría de IA (request_id, intent, tools, recuperados, latencia) |
| `favorites` | Favoritos (único por user+property) |
| `saved_searches` | Alertas de búsqueda con filtros estructurados |
| `leads` | CRM (estado NEW→LOST, presupuesto, notas) |
| `appointments` | Citas (índice de slot por property+fecha) |
| `alembic_version` | Versión de migraciones |

## Enums

- `PropertyType`: casa, apartamento (únicos tipos válidos)
- `Operation`: SALE, RENT (preparado para TEMPORARY_RENT, PROJECT)
- `PropertyStatus`: AVAILABLE, RESERVED, SOLD, INACTIVE
- `DocumentStatus`: PENDING, PROCESSING, READY, FAILED
- `LeadStatus`: NEW, CONTACTED, INTERESTED, VISIT_SCHEDULED, NEGOTIATION, CLOSED, LOST
- `AppointmentStatus`: REQUESTED, CONFIRMED, CANCELLED, COMPLETED

Los enums se guardan como VARCHAR (native_enum=False) para poder extenderlos con migraciones simples.

## Full-text y vector

- `properties.search_vector`: columna GENERADA (persistida) con `setweight(to_tsvector('spanish', …))` ponderada: título A, barrio/ciudad B, descripción C.
- `properties.title_embedding`: `vector(256)` (dim fija por migración; debe coincidir con `EMBEDDING_DIM`).
- `document_chunks.embedding`: `vector(256)`.

## Índices

Precio, ciudad, tipo, operación, habitaciones, estado (en `properties`), conversación (messages), documento (chunks), slot (appointments), user/property (favorites), user_id (leads, saved_searches), chunk_hash.

## Conexiones

- Sync engine (scripts/migraciones): `app/database/base.py:make_sync_engine` (pool 5+10).
- Async engine (app): `make_async_engine` (pool 10+20), `AsyncSessionLocal`.
- `server_admin_url()` apunta a la BD `postgres` para `CREATE DATABASE`.

## Migraciones

```bash
python -m alembic upgrade head
```

`main.py` las ejecuta al arrancar. Para modificar el esquema: editar `app/database/models.py` + crear migración con `alembic revision --autogenerate -m "…"`. Nunca destruir la base.
