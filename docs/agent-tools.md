# Herramientas del agente

Arquitectura obligatoria: `LLM → Tool → Service → Repository → Database`. El LLM nunca consulta PostgreSQL directamente.

`app/agents/tools.py:run_tool(name, args, ctx)` es la **única** puerta del modelo a los datos. Cada tool devuelve un dict JSON-safe que se añade al contexto del LLM (compacto, sin secretos) y se audita en `ai_events`.

## Herramientas

| Tool | Función | Servicio |
|---|---|---|
| `search_properties` | Búsqueda con filtros estructurados + consulta semántica (SQL+FTS+vector) | `properties.search` |
| `get_property` | Ficha completa por código, id o referencia contextual | `properties.repository` |
| `compare_properties` | Comparación data-only (contexto si hay <2 refs) | `properties.repository` |
| `search_documents` | Búsqueda RAG, devuelve chunks citables | `rag.retrieval` |
| `get_property_images` | Lista imágenes locales | `api.files` |
| `save_property` / `remove_saved_property` | Favoritos | `crm.service` |
| `save_search` / `list_saved_searches` | Alertas de búsqueda | `crm.service` |
| `create_lead` / `get_customer_profile` | CRM (solo datos observables) | `crm.service` |
| `list_available_slots` / `schedule_visit` / `cancel_appointment` | Agenda con anti doble-reserva | `appointments.service` |
| `recommend_similar` | Similares reales (mismo tipo/ciudad, banda de precio, vector) | `properties.search` |

## Referencias contextuales (resolución determinista)

`_find_property` resuelve en este orden cuando no hay ref explícita:

1. La única propiedad en contexto (`last_results`)
2. Match estricto por título con las palabras del usuario («la casa familiar») — ambiguo devuelve None (el agente pregunta, no adivina)
3. La propiedad que el usuario miró por última vez («¿tiene piscina?»)

Con ref explícita: ordinales («segunda», «2ª»), UUID, código, o match contra `last_results`.

`app/memory/service.py:resolve_reference` resuelve «la segunda» / «la de 280 millones» contra los últimos resultados ANTES de decidir la herramienta. Nunca adivina: sin match → None.

## Contexto de ejecución (ToolContext)

```python
@dataclass
class ToolContext:
    session: AsyncSession
    user_id: int
    conversation_id: uuid.UUID
    state: dict                    # last_results, last_filters, last_property_id, last_appointment_id
    executed: list[dict]           # auditoría: tool, args, ok
    retrieved_property_ids: list[str]
    retrieved_chunk_ids: list[str]
    user_text: str
```

## Flujo tool-calling (con NVIDIA)

```
User → LLM (con TOOL_SPECS) → tool_calls[] → run_tool() por cada una
     → results en el contexto → LLM → respuesta final
```

Máximo 4 rondas. El resultado de cada tool se trunca (4000 chars) para mantener el contexto acotado.

## Preferencias persistentes

`memory_service.update_preferences` guarda SOLO hechos observables y estructurados (ciudad, tipo, operación, presupuesto, habitaciones, baños, parking) derivados de los filtros reales de búsqueda — nunca conjeturas del modelo.
