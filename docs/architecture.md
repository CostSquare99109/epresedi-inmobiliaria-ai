# Arquitectura

## Principios

- **Local-first**: todo funciona en local (PostgreSQL, pgvector, Redis, storage, RAG, panel). La única dependencia externa obligatoria es NVIDIA Build (solo inferencia).
- **Separación de capas**: presentation (bot/admin/API) → application (services, orchestrator) → domain (models) → infrastructure (database, redis, storage).
- **El LLM nunca toca la base de datos**: `LLM → Tool → Service → Repository → Database`.
- **Los criterios numéricos se resuelven con código**: filtros de precio/habitaciones/baños/parqueaderos son deterministas (`app/properties/search.py`); nunca se confía en la memoria del LLM para filtros críticos.
- **No alucinaciones**: si un dato no está en los resultados de herramientas, la respuesta es «No tengo información confirmada sobre eso».

## Flujo principal

```
TELEGRAM (Update)
   │
   ▼
app/bot/handlers.py          ← presentación: sin SQL
   │  (rate limit → orchestrator)
   ▼
app/agents/orchestrator.py   ← intent + referencias + herramientas + memoria + auditoría
   │
   ├── app/agents/tools.py   ← run_tool(): única puerta del modelo a los datos
   │        │
   │        ├── app/properties/{repository,search}.py   (SQL + FTS + pgvector)
   │        ├── app/rag/{retrieval,ingest}.py           (pgvector + full-text)
   │        ├── app/crm/service.py                       (favoritos, alertas, leads)
   │        └── app/appointments/service.py              (citas, anti doble-reserva)
   │
   ├── app/ai/llm.py         ← NVIDIAProvider (tool calling) o modo determinista
   └── app/ai/embeddings.py  ← EmbeddingProvider (NVIDIA o local hash)
```

## Composición (main.py)

`main.py` es solo el punto de composición (~250 líneas): config → logging → infra checks → migraciones → pgvector check → orchestrator → bot → API → workers → scheduler → apagado. La lógica vive en `app/*`.

## Capas y responsabilidades

| Capa | Módulos | Regla |
|---|---|---|
| Presentación | `app/bot/`, `app/api/`, `admin/` | No conocen SQL. El bot no importa repositorios; la API usa servicios |
| Aplicación | `app/agents/`, `app/properties/search.py`, `app/crm/`, `app/appointments/`, `app/memory/`, `app/rag/` | Orquestación y lógica de negocio |
| Dominio | `app/database/models.py` | Modelos + enums; esquema gestionado por Alembic |
| Infraestructura | `app/database/base.py`, `app/workers/`, `app/security/`, `app/core/` | Engines, queue, rate limit, settings, logging |

## Fuente de verdad (source of truth)

1. **Datos estructurados** (PostgreSQL) — inventario, estados, precios.
2. **Documentos oficiales** (RAG) — reglamentos, fichas, contratos.
3. **Datos administrativos** (CRM) — leads, favoritos, búsquedas guardadas.
4. **Contexto conversacional** — estado de la conversación actual.
5. **Inferencias** — nunca se presentan como hechos confirmados.

## Compatibilidad futura (interfaces, no implementaciones)

| Hoy | Mañana | Interfaz |
|---|---|---|
| PostgreSQL local | PostgreSQL cloud | `DATABASE_URL` (env) |
| pgvector | Qdrant | `EmbeddingProvider` + retrieval módulo |
| NVIDIA Build | otro LLM | `LLMProvider` (Protocol) |
| storage local | S3 | `app/api/files.py` (funciones de storage aisladas) |
| Redis local | Redis cloud | `REDIS_URL` (env) |
