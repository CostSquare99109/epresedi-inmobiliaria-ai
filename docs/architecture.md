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

## Flujo conversacional (LLM-FIRST PURO)

```
Usuario → /nuevo o mensaje
    ↓
handlers.py → handle_user_message(session, user_id, text)
    ↓
memory_service.get_or_create_user + get_or_create_conversation
    ↓
add_message(USER, text)  ← persiste mensaje usuario
    ↓
ToolContext(state=conv.state, user_text=text)  ← estado actual
    ↓
_run_llm_turn(ctx, text)  ← PASO 1: LLM con tools
    ├── _build_messages()  ← system prompt + historial (8 turnos) + estado + mensaje actual
    ├── LLM chat(tools=TOOL_SPECS, max_tokens=4000)
    │   ├── Si tool_calls → ejecutar tools → loop (máx 4 rondas)
    │   └── Si content (JSON) → parse_llm_response() → decisión
    │       ├── Si JSON inválido → reintentar con instrucción explícita
    │       └── Si válido → retornar LLMDecision
    └── Si max_rounds excedido → protección anti-loop → forzar decisión final
    ↓
Ejecutar tool_calls de la decisión → tool_results
    ↓
_run_llm_turn_with_results(ctx, text, decision, tool_results)  ← PASO 2: decisión final
    ├── Mensajes: system + historial + decisión anterior + tool_results
    ├── LLM chat(tools=None, max_tokens=4000)  ← SIN tools para forzar JSON
    │   ├── Reintento 1-2: finish_reason=length / JSON inválido / texto corto
    │   └── Si falla todo → _build_fallback_reply() basado en tool_results reales
    ↓
merge_state_update()  ← valida y aplica state_updates propuestos por LLM
    ↓
decision.to_agent_reply()  ← AgentReply(texto, intent, imágenes, acciones)
    ↓
Persistir: conv.state = ctx.state, add_message(ASSISTANT, reply.text)
    ↓
Auditoría: AiEvent(request_id, user_id, intent, tool_calls, latency, status)
    ↓
Retornar AgentReply → handlers.py → Telegram
```

## Manejo de errores (Error Handling)

```
Capas de captura (de más específica a más general):

1. LLMProvider.chat() → LLMError(kind: timeout|auth|rate_limit|server|network|unknown)
   - Reintentos automáticos (backoff exponencial, máx 3 por defecto)
   - No duplica tool calls en reintento (idempotente)

2. _run_llm_turn() / _run_llm_turn_with_results()
   - Truncamiento (finish_reason=length): reintenta pidiendo JSON corto
   - JSON inválido: reintenta con errores específicos
   - Respuesta vacía/corta: reintenta pidiendo texto mínimo
   - Loop detection: tool calls idénticos, búsquedas 0 resultados consecutivas
   - Fallback de infraestructura: _build_fallback_reply() con datos reales

3. PureLLMOrchestrator.handle_user_message()
   - LLMError → rollback, log detallado (llm_structural_failure incluye user_id, conversation_id, model, prompt_version)
   - Usuario recibe: "Tuve un inconveniente momentáneo al procesar tu mensaje. Intenta enviarlo nuevamente en unos segundos."
   - Excepción genérica → rollback, log.exception, usuario: "⚠️ Ocurrió un error interno. El equipo fue notificado en los logs."

4. handlers.py → _reply_with()
   - BadRequest (markup/parse) → reintenta sin keyboard / sin markdown
   - Otros errores → re-lanza

NUNCA se expone al usuario: llm_structural_failure, ValidationError, JSONDecodeError, Traceback, python -m scripts.doctor, API keys, tokens.
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

## Observabilidad del flujo

Logs correlacionables por `conversation_id`, `message_id`, `request_id`:

```
conversation_started
user_message_received
history_loaded
context_built
llm_request_started (round=N)
llm_response_received (finish_reason, latency_ms)
structured_output_parsed (ok|errors)
tool_call_requested (tool, args)
tool_executed (tool, ok, latency_ms)
tool_result_received
final_response_generated
assistant_message_persisted
audit_written
```

Errores:
```
llm_request_failed (kind, retry_count)
structured_output_failed (errors, content_preview)
tool_execution_failed (tool, error_code)
conversation_processing_failed (exception_type)
```
