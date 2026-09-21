# Auditoría de "Segundo Cerebro" - Componentes que toman decisiones semánticas independientemente del LLM

## Resumen Ejecutivo

El proyecto actualmente tiene una arquitectura **híbrida** donde coexisten dos "cerebros":
1. **LLM-FIRST** (`llm_orchestrator.py`) - Cuando hay credenciales NVIDIA
2. **Pipeline Determinista** (`orchestrator.py`) - Como fallback Y como cerebro principal cuando no hay LLM

El pipeline determinista contiene **extensa lógica de negocio semántica** que viola la regla arquitectónica: *"NINGUNA LÓGICA DE NEGOCIO PUEDE FUNCIONAR DE FORMA INDEPENDIENTE DEL LLM"*

---

## 1. Detección de Intención por Regex (`app/agents/intents.py`)

**Archivo**: `app/agents/intents.py`
**Función**: `detect_intent(message: str) -> Intent`
**Decisiones que toma**:
- Clasifica 28 intenciones distintas usando patrones regex
- `_VISIT`, `_COMP`, `_DOCQ`, `_PRICE`, `_LOC`, `_FIN`, `_SELL`, `_RENTOUT`, `_SEARCH_HINTS`, `_FAV`, `_UNFAV`, `_SAVE_SEARCH`, `_LIST_SAVED`, `_CANCEL`, `_CONTACT`, `_SLOTS`, `_FAQ`
- Prioridades complejas (ej: búsqueda con criterios + imágenes = SEARCH_PROPERTY)
- Detección de preguntas de atributos vs búsquedas nuevas

**Debe ser**: El LLM debe interpretar la intención del usuario completamente.

---

## 2. Extracción de Entidades por Regex (`app/agents/orchestrator.py`)

### `_extract_contact_data(text: str) -> dict[str, str]`
**Líneas**: 207-237
**Decisiones**:
- Extrae email con regex: `[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}`
- Extrae teléfono colombiano con regex complejo
- Extrae nombre por heurística: líneas capitalizadas, 2-4 palabras, sin dígitos/@
- Filtra líneas que contienen palabras clave de comandos

### `_validate_name(name: str) -> tuple[bool, str | None]`
**Líneas**: 164-177
**Decisiones**:
- Requiere mínimo 2 partes (`len(parts) < 2`)
- Valida caracteres permitidos (letras, espacios, guiones, apóstrofes, puntos)

### `_validate_phone(phone: str) -> tuple[bool, str | None, str | None]`
**Líneas**: 180-193
**Decisiones**:
- Normaliza formato colombiano (+57, espacios, guiones)
- Requiere 10 dígitos, inicia con 3

### `_validate_email(email: str) -> tuple[bool, str | None]`
**Líneas**: 196-204
**Decisiones**:
- Regex básico de email

**Debe ser**: El LLM debe extraer y validar semánticamente TODOS los campos.

---

## 3. Máquina de Estados de Citas (`app/agents/orchestrator.py`)

### `BOOKING_STATE` (11 estados)
**Líneas**: 54-65
```
ESPERANDO_INICIO → MOSTRANDO_HORARIOS → ESPERANDO_HORARIO → ESPERANDO_DATOS 
  → ESPERANDO_NOMBRE → ESPERANDO_CELULAR → ESPERANDO_CORREO 
  → LISTO_PARA_CONFIRMAR → CONFIRMANDO → AGENDADO
```

### `_handle_booking_contact_input()` - State Machine Compleja
**Líneas**: 1833-1964
**Decisiones que toma**:
- Detecta cambio de horario: `_detect_change_schedule()` con keywords
- Detecta confirmación afirmativa: `_detect_affirmative_confirmation()` con 20+ keywords
- Detecta confirmación negativa: `_detect_negative_confirmation()` con 10+ keywords
- Valida campos uno por uno (nombre → teléfono → correo)
- Maneja reintentos y errores de validación
- Avanza/retrocede estados basado en validaciones técnicas

### `_verify_and_show_confirmation()`, `_show_booking_confirmation()`, `_confirm_booking_action()`
**Líneas**: 1966-2156
**Decisiones**:
- Verifica disponibilidad real antes de confirmar
- Maneja conflictos de horario (slot ya reservado)
- Preserva datos de contacto entre intentos

**Debe ser**: El LLM debe gestionar TODO el flujo conversacional de citas.

---

## 4. Pipeline Determinista como Cerebro Principal (`app/agents/orchestrator.py`)

### `_intent_flow()` - Switch Case Masivo
**Líneas**: 544-633
**Decisiones para 20+ intenciones**:
- GREETING, SEARCH_PROPERTY, PROPERTY_DETAILS, PROPERTY_IMAGES, COMPARE_PROPERTIES
- PRICE_QUERY, LOCATION_QUERY, PROPERTY_DOCUMENT_QUESTION, FINANCING_QUESTION
- SAVE_PROPERTY, REMOVE_PROPERTY, SAVE_SEARCH, LIST_SAVED_SEARCHES
- SCHEDULE_VISIT, CANCEL_APPOINTMENT, CONTACT_AGENT, SELL_PROPERTY, RENT_PROPERTY, GENERAL_FAQ

### `_search_flow()` - Lógica de Búsqueda Completa
**Líneas**: 636-724
**Decisiones**:
- Extrae filtros con `extract_filters()` (regex)
- Resuelve ubicación con `_resolve_location()` (matching fuzzy)
- Expande búsqueda automáticamente ±30% si 0 resultados
- Decide cuándo mostrar imágenes basado en keywords en el mensaje
- Formatea respuesta con `property_line()`

### `_details_flow()`, `_images_action()`, `_visit_flow()`
**Decisiones**: Resolución de referencias, formateo de respuestas, navegación de horarios

### `_handle_search_refinement()` - Detección de Acuerdo por Regex
**Líneas**: 1097-1225
**Decisiones**:
- 15+ patrones regex para detectar "sí", "ok", "dale", "amplía", etc.
- Si NO coincide, asume que es nueva consulta y limpia flag
- Ejecuta búsqueda expandida automáticamente

### `_parse_datetime()` - Parsing de Fechas Complejo
**Líneas**: 1236-1375
**Decisiones**:
- Parsea ISO, "mañana", "pasado mañana", fechas relativas, meses, días de semana
- Maneja AM/PM, "de la tarde/mañana"
- Retorna datetime o None

---

## 5. Resolución de Referencias en Python (`app/agents/tools.py`)

### `_find_property()` 
**Líneas**: 50-95
**Decisiones**:
- Orden de resolución: único en contexto → match por texto → última vista
- Normaliza ordinales ("la primera", "opción 2") con diccionario `ORDINALS`
- Intenta UUID, luego código, luego match en últimos resultados

---

## 6. Formateo de Respuestas Hardcodeado (`app/agents/orchestrator.py`)

### `_format_slot_for_display()`, `_format_single_day_message()`, `_group_slots_by_day()`
**Líneas**: 118-161
**Decisiones**: Cómo presentar horarios al usuario (mañana/tarde, días en español)

### `_attribute_answer()` - Respuestas de Atributos desde Datos Estructurados
**Líneas**: 726-795
**Decisiones**: Mapea preguntas a columnas DB, decide qué decir si dato es NULL vs 0

---

## 7. Validaciones Técnicas que Deciden Flujo Conversacional

### En `_handle_booking_contact_input()`:
- Si `errors`: muestra errores y NO avanza
- Si `missing`: pregunta por faltantes y NO avanza  
- Solo si TODO válido → `_verify_and_show_confirmation()`

**Problema**: Python decide cuándo avanzar basándose en validaciones técnicas, no semánticas.

---

## 8. Modo Determinista Como "Cerebro Completo"

En `main.py` líneas 156-166:
```python
if llm is None:
    log.warning("llm_mode=%s provider=none — cerebro determinista...")
else:
    log.info("llm_mode=%s llm_first=%s provider=%s model=%s", ...)
```

El sistema **funciona completamente sin LLM** - el pipeline determinista ES el cerebro cuando no hay credenciales NVIDIA.

---

## 9. Tests que Validan Comportamiento Determinista

`tests/test_agent.py` valida:
- `detect_intent()` para TODAS las intenciones
- `is_attribute_question()` vs nueva búsqueda
- Flujo conversacional completo SIN LLM (`Orchestrator(llm=None)`)
- Resolución de referencias ordinales y por precio
- Saludos sin reintroducción
- Refinamiento de búsqueda con frases de acuerdo

---

## Mapa de Responsabilidades - Actual vs Objetivo

| Componente | Actualmente Decide | Debe Decidir | Acción |
|------------|-------------------|--------------|--------|
| `intents.py:detect_intent()` | Intención del usuario | **LLM** | Eliminar/consolidar en tool `update_conversation_state` |
| `orchestrator.py:_extract_contact_data()` | Extracción nombre/tel/email | **LLM** | Eliminar - LLM usa tool `update_conversation_state` |
| `orchestrator.py:_validate_name/phone/email()` | Validación semántica | **LLM** (backend solo valida formato técnico) | Mover validación técnica a tools; semántica al LLM |
| `orchestrator.py:BOOKING_STATE` | Máquina de estados cita | **LLM** (estado = contexto, no autoridad) | Eliminar state machine; LLM maneja flujo |
| `orchestrator.py:_handle_booking_contact_input()` | Flujo completo de cita | **LLM** | Eliminar - LLM orquesta con tools |
| `orchestrator.py:_intent_flow()` | Switch 20+ intenciones | **LLM** | Eliminar - LLM decide qué tools llamar |
| `orchestrator.py:_search_flow()` | Lógica búsqueda + expansión | **LLM** | LLM llama `search_properties` con filtros interpretados |
| `orchestrator.py:_handle_search_refinement()` | Detecta "sí/ok/dale" | **LLM** | Eliminar - LLM interpreta respuesta usuario |
| `orchestrator.py:_parse_datetime()` | Parsing fechas | **LLM** | Eliminar - LLM interpreta y pasa ISO a tool |
| `tools.py:_find_property()` | Resolución referencias | **LLM** (con ayuda de tool `get_property`) | LLM resuelve con contexto + tool |
| `orchestrator.py:_format_*()` | Formateo respuesta | **LLM** | LLM genera respuesta final |
| `orchestrator.py:_attribute_answer()` | Responde features desde DB | **LLM** | LLM usa `get_property` y responde |
| Modo `deterministic` | Cerebro completo sin LLM | **NO DEBE EXISTIR** | Eliminar - LLM es obligatorio |

---

## Próximos Pasos

1. **Diseñar contrato estructurado LLM** (JSON schema para decisiones)
2. **Reescribir `llm_orchestrator.py`** como ÚNICO punto de entrada
3. **Eliminar `orchestrator.py` pipeline determinista** (mantener solo infraestructura)
4. **Actualizar system prompt** para LLM-first puro
5. **Crear tools unificadas** que el LLM use para TODO
6. **Tests exhaustivos** que validen comportamiento LLM-first