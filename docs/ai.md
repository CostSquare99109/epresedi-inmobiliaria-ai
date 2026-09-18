# IA (LLM y Embeddings)

## LLMProvider (abstracción)

```python
class LLMProvider(Protocol):
    name: str
    model: str
    async def chat(messages, tools=None, temperature=0.2, max_tokens=900) -> LLMResponse
```

Implementación actual: `NVIDIAProvider` (`app/ai/llm.py`) — NVIDIA Build vía API compatible OpenAI (`POST {NVIDIA_BASE_URL}/chat/completions`) con tool calling estructurado (`tool_choice: auto`).

Cambiar de proveedor = implementar `LLMProvider`. El resto de la app no cambia.

## Configuración (solo .env)

```
NVIDIA_API_KEY=...
NVIDIA_BASE_URL=https://integrate.api.nvidia.com/v1
NVIDIA_MODEL=meta/llama-3.3-70b-instruct
NVIDIA_TIMEOUT=60
LLM_MODE=auto        # auto | nvidia | deterministic
```

- `auto`: NVIDIA si hay key+modelo; motor determinista si no.
- `deterministic`: nunca llama a la red; respuestas basadas 100% en datos reales.

## Fallbacks de NVIDIA

| Fallo | Comportamiento |
|---|---|
| timeout | `LLMError("timeout")` → el orquestador informa al usuario, no inventa respuesta |
| 401/403 | `LLMError("auth")` |
| 429 | `LLMError("rate_limit")` |
| 5xx | `LLMError("server")` |
| network error | `LLMError("network")` |

En todos los casos: registra el error (`ai_events.status=llm_error:*`), responde con un mensaje controlado y permite recuperarse. No crea un proveedor cloud secundario automáticamente.

## Anti-alucinación (regla absoluta)

La IA NO puede inventar propiedades, precios, disponibilidad, características, áreas, direcciones, financiación, documentos, citas ni reglas. Mecanismos:

1. **System prompt versionado** (`app/agents/prompts.py`, PROMPT_VERSION en `ai_events`): «Si un dato no está en la información recuperada, di exactamente: "No tengo información confirmada sobre eso."»
2. **Los filtros críticos los resuelve el código** (`extract_filters` + SQL), no el modelo.
3. **Respuesta determinista solo desde tool output** (sin LLM): las fichas/comparaciones se renderizan desde datos reales.
4. **Atributos ambiguos → "no informado"**: una columna NULL es «No informado», nunca «no». Un 0 es un «no» confirmado.
5. **Puerta de entidad en RAG**: si el documento no menciona la entidad preguntada, no hay respuesta.
6. Tests de alucinación: `tests/test_e2e.py` y `tests/test_agent.py` (piscina, precio, parqueadero, financiación, disponibilidad, área).

## Tool calling

Si el modelo lo soporta (NVIDIA sí):

```
User → LLM → tool call → run_tool() → result → LLM → respuesta final
```

Loop de máximo 4 rondas (`MAX_TOOL_ROUNDS`); si se excede → fallback determinista. El modelo nunca genera JSON arbitrario: usa los esquemas de `app/agents/tool_specs.py`.

Sin LLM: el orquestador ejecuta el mismo plan de herramientas de forma determinista y renderiza la respuesta desde el output.

## Embeddings

```python
class EmbeddingProvider(Protocol):
    name: str
    dim: int
    async def embed(texts: list[str]) -> list[list[float]]
```

- `NVIDIAEmbedding` (`nvidia/nv-embedqa-e5-v5`): semántica real, se selecciona automáticamente con NVIDIA configurado (`EMBEDDING_PROVIDER=auto`).
- `LocalHashEmbedding`: determinista 256-dim (bag-of-tokens con numpy, dos buckets por token, norma coseno). Offline, sin descargas. Suficiente para la recuperación léxico-semántica del prototipo.

La dimensión debe coincidir con la columna pgvector (`EMBEDDING_DIM=256`). Cambiar el proveedor no toca la arquitectura; si cambia la dimensión, requiere migración + reprocesar embeddings.

## Contexto

- Mensajes recientes (6) + preferencias persistentes + resumen rodante (`_summarize`).
- Nunca se envía toda la conversación histórica indefinidamente.
- Nunca se envían 1000 propiedades al modelo: primero candidatos SQL (límite 8), después solo la información necesaria.
