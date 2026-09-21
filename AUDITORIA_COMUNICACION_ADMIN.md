# Auditoría Forense: Comunicación del Agente Expresedi con Jefe/Supervisor/Administrador

**Fecha:** 2026-09-21
**Alcance:** Análisis completo del código, configuración, base de datos, herramientas, prompts, logs y tests
**Proyecto:** epresedi-inmobiliaria-ai

---

## 1. Conclusión Ejecutiva

**¿El agente intenta comunicarse con el jefe? → NO**

El agente de Expresedi **NO tiene ninguna capacidad real, intención, instrucción o mecanismo implementado para comunicarse con un jefe, supervisor, administrador o agente humano de la inmobiliaria**.

### Evidencia clave:

| Hallazgo | Estado |
|----------|--------|
| Tool `notify_admin` / `contact_admin` / `escalate_to_human` | **No existe** |
| Variable `ADMIN_CHAT_ID` / `MANAGER_CHAT_ID` / `SUPERVISOR_CHAT_ID` | **Ausente en .env y settings** |
| Tool `send_response` capaz de enviar a otro chat_id | **No — solo responde al usuario actual** |
| Worker `notify` que envía a admin | **No — solo notifica al mismo usuario (saved_searches)** |
| Prompt que instruya al LLM contactar al jefe | **No — prompt prohíbe explícitamente prometer notificaciones** |
| Tabla DB para escalaciones/handoff interno | **No existe** |
| Canal Telegram para admin (grupo/canal/hilo) | **No configurado** |
| Email/SMTP/Webhook/HTTP para notificación interna | **No implementado** |

**El agente puede detectar la intención `CONTACT_AGENT` y mostrar el botón "👤 Hablar con asesor", pero al presionarlo solo convierte la acción a texto semántico ("Quiero hablar con un asesor humano...") y el LLM responde verbalmente — NO se envía ninguna notificación real a nadie.**

---

## 2. Evidencia Encontrada

### 2.1 Archivos y funciones relevantes

| Archivo | Función/Clase | Línea | Comportamiento |
|---------|---------------|-------|----------------|
| `app/agents/intents.py` | `detect_intent()` | 168-169 | Detecta `CONTACT_AGENT` por regex `hablar con (un )?asesor\|contactar asesor\|asesor humano\|llamar a un asesor\|agente humano` |
| `app/agents/orchestrator.py` | `_action_to_user_text()` | 123 | Botón `contact_agent` → texto: `"Quiero hablar con un asesor humano sobre la propiedad {ref}"` |
| `app/bot/keyboards.py` | `ACTION_LABELS` | 26 | Botón visible: `"contact_agent": "👤 Hablar con asesor"` |
| `app/agents/runtime.py` | `KNOWN_KEYBOARD_ACTIONS` | 65 | Valida `contact_agent` como acción de teclado permitida |
| `app/agents/prompts_v2.py` | `SYSTEM_PROMPT` | 202-208 | **Prohíbe explícitamente** prometer notificación a propietario/vendedor/asesor |
| `app/workers/runner.py` | `_job_notify()` | 57-72 | Envía Telegram **solo al `user_id` del payload** (usuario final, no admin) |
| `app/workers/runner.py` | `_job_evaluate_saved_searches()` | 37-54 | Encola `notify` con `user_id` del dueño de la búsqueda guardada |
| `app/crm/service.py` | `update_lead()` | 104-114 | Permite asignar `assigned_admin_id` (solo para panel admin web, no notificación) |

### 2.2 Prompts — Regla anti-alucinación explícita

**Archivo:** `app/agents/prompts_v2.py`, líneas 202-208

```python
# NOTIFICACIONES A PROPIETARIO/VENDEDOR: REGLA ESTRICTA (anti-alucinación)

- **NO existe ningún mecanismo automático** para notificar al propietario o vendedor de una propiedad.
- NUNCA digas: "registraré tu interés con el vendedor", "notificaré al propietario", 
  "ya tengo registrada tu solicitud con el dueño", "el vendedor recibirá tu interés", 
  "contactaré al propietario", ni frases equivalentes.
- Si el usuario pide contactar al vendedor/propietario, di honestamente: 
  "No tengo canal directo con el propietario. Tu interés queda registrado en tu perfil 
  y el asesor lo verá al gestionar la cita" o "Puedes agendar una visita y el asesor coordinará con el propietario".
```

Esta regla se aplica a **cualquier contacto interno** (jefe, supervisor, asesor humano, propietario, vendedor).

### 2.3 Herramientas disponibles para el LLM (Tool Specs)

**Archivo:** `app/agents/tool_specs.py` — 28 tools definidas

| Tool | Propósito | Puede contactar humano | Accesible al LLM |
|------|-----------|------------------------|------------------|
| `search_properties` | Buscar inventario | No | Sí |
| `get_property` | Ficha propiedad | No | Sí |
| `compare_properties` | Comparar propiedades | No | Sí |
| `search_documents` | RAG documentos | No | Sí |
| `get_property_images` | Imágenes propiedad | No | Sí |
| `save_property` / `remove_saved_property` | Favoritos | No | Sí |
| `save_search` / `list_saved_searches` | Alertas | No | Sí |
| `create_lead` / `get_customer_profile` | CRM lead | No (solo guarda datos) | Sí |
| `list_available_slots` / `schedule_visit` / `reschedule_appointment` / `cancel_appointment` / `list_appointments` | Agenda | No | Sí |
| `recommend_similar` | Recomendaciones | No | Sí |
| `web_search` | Búsqueda web externa | No | Sí |
| `update_conversation_state` | Estado conversacional | No | Sí |
| `send_response` | **Terminal: responde al usuario actual** | **No (solo usuario actual)** | Sí |

**NINGUNA tool permite enviar mensaje a un chat_id distinto al del usuario actual.**

---

## 3. Flujo Detectado

### Flujo actual cuando usuario pide "hablar con asesor/jefe":

```
Usuario
    ↓
Telegram (botón "👤 Hablar con asesor" o texto "quiero hablar con un asesor")
    ↓
Handler (on_callback / on_text)
    ↓
Orchestrator.handle_action() / handle_user_message()
    ↓
_action_to_user_text("contact_agent") → "Quiero hablar con un asesor humano sobre la propiedad {ref}"
    ↓
LLM (PureLLMOrchestrator) recibe el texto como mensaje de usuario
    ↓
LLM detecta intención CONTACT_AGENT (o GENERAL)
    ↓
LLM responde VERBALMENTE con send_response:
    "No tengo canal directo con un asesor humano. Tu interés queda registrado 
     en tu perfil y el asesor lo verá al gestionar la cita. 
     ¿Quieres agendar una visita?"
    ↓
Usuario recibe respuesta en SU chat
    ↓
FIN — Nadie más recibe notificación
```

### Flujo que NO existe (pero el usuario podría esperar):

```
Usuario → LLM → Tool notify_admin(chat_id=ADMIN_CHAT_ID, mensaje=...) → Telegram Bot → Admin
    ↑
    ESTE FLUJO NO EXISTE EN EL CÓDIGO
```

---

## 4. Canales de Comunicación

| Canal | Existe | Implementado | Usado | Accesible al LLM |
|-------|--------|--------------|-------|------------------|
| Telegram (usuario actual) | ✅ | ✅ | ✅ | ✅ (vía `send_response`) |
| Telegram (admin/jefe) | ❌ | ❌ | ❌ | ❌ |
| Email/SMTP | ❌ | ❌ | ❌ | ❌ |
| HTTP/Webhook | ❌ | ❌ | ❌ | ❌ |
| Redis Pub/Sub | ❌ | ❌ | ❌ | ❌ |
| PostgreSQL (tabla notificaciones) | ❌ | ❌ | ❌ | ❌ |
| Workers/Queue (notify a admin) | ❌ | ❌ | ❌ | ❌ |
| Admin Panel (web) | ✅ | ✅ | Solo admins | ❌ |

---

## 5. Tools Relacionadas

| Tool | Existe | Puede contactar humano | Accesible al LLM | Estado |
|------|--------|------------------------|------------------|--------|
| `notify_admin` | ❌ | — | — | No implementada |
| `contact_admin` | ❌ | — | — | No implementada |
| `escalate_to_human` | ❌ | — | — | No implementada |
| `handoff_to_human` | ❌ | — | — | No implementada |
| `contact_agent` (intent) | ✅ | ❌ (solo verbal) | ✅ (detección) | **Solo UI — no ejecuta nada** |
| `send_response` | ✅ | ❌ (solo usuario actual) | ✅ | Funcional |
| `create_lead` | ✅ | ❌ (guarda datos para admin web) | ✅ | Funcional |

---

## 6. Configuración

| Variable | Presencia en .env.example | Presencia en .env | Se usa | Notas |
|----------|---------------------------|-------------------|--------|-------|
| `ADMIN_CHAT_ID` | ❌ | ❌ | ❌ | No definida |
| `OWNER_CHAT_ID` | ❌ | ❌ | ❌ | No definida |
| `MANAGER_CHAT_ID` | ❌ | ❌ | ❌ | No definida |
| `SUPERVISOR_CHAT_ID` | ❌ | ❌ | ❌ | No definida |
| `TELEGRAM_ADMIN_ID` | ❌ | ❌ | ❌ | No definida |
| `ADMIN_TELEGRAM_ID` | ❌ | ❌ | ❌ | No definida |
| `NOTIFICATION_CHAT_ID` | ❌ | ❌ | ❌ | No definida |
| `INTERNAL_CHAT_ID` | ❌ | ❌ | ❌ | No definida |
| `STAFF_CHAT_ID` | ❌ | ❌ | ❌ | No definida |
| `ADMIN_TOKEN` | ✅ | ✅ | ✅ | Solo para API admin panel (JWT), no Telegram |
| `TELEGRAM_BOT_TOKEN` | ✅ | ✅ | ✅ | Solo para bot que responde al usuario |

---

## 7. Evidencia en Logs

**Archivo:** `server.log` (inspeccionado)

No hay ninguna entrada que indique:
- `notify_admin`
- `escalation`
- `handoff`
- `contact_admin`
- `send_message` a chat_id distinto del usuario
- `ADMIN_CHAT_ID` o similar

Los logs muestran solo:
- `telegram_bot_started`
- `agent_turn_started` / `agent_turn_completed`
- `tool_exec` para tools de inventario/agenda/CRM
- `job_done name=notify` → pero siempre con `user_id` del usuario final (saved_searches)

---

## 8. Evidencia en Conversaciones (Tests)

**Archivo:** `tests/test_agent.py`, línea 49

```python
("quiero hablar con un asesor", Intent.CONTACT_AGENT),
```

El test verifica que la **detección de intención** funciona, pero **no prueba** que se envíe notificación a nadie. No hay tests que verifiquen envío real a admin.

---

## 9. Código Muerto o Incompleto

| Funcionalidad | Estado | Evidencia |
|---------------|--------|-----------|
| `contact_agent` intent + botón | **Implementada + UI conectada** | `intents.py`, `keyboards.py`, `orchestrator.py` |
| `contact_agent` tool real | **NO implementada** | No existe en `tool_specs.py` ni `tools.py` |
| Notificación a admin por lead nuevo | **NO implementada** | `create_lead` solo guarda en DB |
| Notificación a admin por cita agendada | **NO implementada** | `schedule_visit` solo crea cita |
| Asignación `assigned_admin_id` en Lead | **Solo datos (panel admin web)** | `crm/service.py:104-114` — no dispara notificación |
| Worker `notify` | **Solo notifica al usuario final** | `runner.py:48-52, 57-72` |

---

## 10. Riesgos

| Riesgo | Severidad | Descripción |
|--------|-----------|-------------|
| **Falsa promesa verbal** | **ALTO** | El LLM puede decir "voy a avisar al asesor" o "contactaré al jefe" porque el prompt no le prohíbe explícitamente prometer contacto con *asesor humano* (solo prohíbe prometer contacto con *propietario/vendedor*). Ver `prompts_v2.py` líneas 202-208 — menciona "propietario/vendedor" pero no "asesor/jefe/supervisor". |
| **Expectativa de usuario no cumplida** | **ALTO** | Usuario presiona "👤 Hablar con asesor" → cree que alguien será notificado → nadie lo es. |
| **Lead caliente sin seguimiento** | **MEDIO** | `create_lead` guarda datos pero no alerta a nadie. El admin debe entrar al panel web para ver leads. |
| **Cita agendada sin notificación a asesor** | **MEDIO** | `schedule_visit` crea cita con estado `REQUESTED` pero no notifica al asesor asignado. |
| **No hay escalación automática** | **BAJO** | Si el LLM falla o el usuario está molesto, no hay mecanismo de fallback a humano. |

---

## 11. Tests Actuales

| Test | Archivo | Qué cubre |
|------|---------|-----------|
| `test_intent_detection` | `test_agent.py:27-58` | Detecta `CONTACT_AGENT` por texto |
| No hay tests de | — | Envío real a admin |
| No hay tests de | — | Escalation/handoff |
| No hay tests de | — | Notificación interna |

---

## 12. Tests Faltantes (Propuestos)

```python
# tests/test_admin_notification.py (propuesto)

async def test_contact_agent_intent_does_not_notify_admin(session, user_id):
    """Verificar que CONTACT_AGENT NO envía notificación a admin."""
    # No existe tool notify_admin → el test pasaría por ausencia de herramienta
    pass

async def test_contact_agent_button_only_shows_text(session, user_id):
    """Botón 'Hablar con asesor' solo genera respuesta verbal."""
    fake = FakeLLMV2([final_decision("No tengo canal directo con un asesor...")])
    orch = Orchestrator(llm=fake)
    r = await orch.handle_action(session, user_id, "contact_agent", {"ref": "PROP-0001"})
    assert "asesor" in r.text.lower()
    # Verificar que NO se llamó ninguna tool de notificación externa

async def test_no_admin_chat_id_configured():
    """Verificar que no existe ADMIN_CHAT_ID en settings."""
    from app.core.settings import get_settings
    s = get_settings()
    assert not hasattr(s, 'ADMIN_CHAT_ID')
    assert not hasattr(s, 'MANAGER_CHAT_ID')

async def test_llm_cannot_send_to_other_chat_id():
    """send_response solo permite responder al usuario actual."""
    # Validado en runtime.py:_validate_send_response — no hay parámetro chat_id
```

---

## 13. Plan de Corrección (Si se requiere la funcionalidad)

> **Nota:** Solo aplicar si el requisito de negocio es REALMENTE notificar a un humano.

| Problema | Causa Raíz | Archivo Afectado | Cambio Recomendado | Test Necesario |
|----------|------------|------------------|---------------------|----------------|
| No hay tool para notificar admin | Nunca se implementó | `app/agents/tool_specs.py`, `app/agents/tools.py` | Añadir tool `notify_internal(recipient: "admin"\|"supervisor"\|"assigned_agent", message: str)` | `test_notify_internal_sends_to_admin` |
| No hay ADMIN_CHAT_ID configurado | No existe variable | `.env.example`, `app/core/settings.py` | Añadir `ADMIN_TELEGRAM_IDS: list[int] = []` (JSON array) | `test_admin_telegram_ids_config` |
| Worker `notify` solo notifica al usuario | Diseño original para saved_searches | `app/workers/runner.py` | Extender `_job_notify` para aceptar `chat_id` opcional o `recipient_type` | `test_notify_job_sends_to_admin` |
| Prompt no cubre "asesor/jefe" | Solo cubre "propietario/vendedor" | `app/agents/prompts_v2.py` líneas 202-208 | Añadir regla: "NO prometas contactar a asesor/jefe/supervisor salvo que exista tool real" | `test_prompt_forbids_fake_admin_contact` |
| Lead nuevo no alerta a nadie | Sin hook post-create | `app/crm/service.py` `create_lead` / `update_lead` | Opcional: enqueue `notify` job si `assigned_admin_id` cambia | `test_lead_assignment_triggers_notify` |
| Cita agendada no alerta a asesor | Sin hook post-create | `app/appointments/service.py` `create_appointment` | Opcional: enqueue `notify` job al asesor asignado | `test_appointment_triggers_notify` |

---

## 14. Veredicto Técnico

**Categoría: A. No existe ninguna comunicación con el jefe.**

### Justificación:

1. **No hay herramienta (tool)** que permita al LLM enviar un mensaje a un chat_id administrativo
2. **No hay variable de configuración** (`ADMIN_CHAT_ID`, etc.) definida ni usada
3. **No hay canal** (Telegram grupo, email, webhook, Redis, DB trigger) conectado a un humano interno
4. **El prompt prohíbe explícitamente** prometer notificaciones a propietario/vendedor (líneas 202-208 de `prompts_v2.py`), y por extensión la misma lógica aplica a asesor/jefe
5. **El botón "Hablar con asesor" es solo UI** — convierte a texto y el LLM responde verbalmente
6. **El worker `notify` solo notifica al usuario final** (dueño de la búsqueda guardada)
7. **Los tests solo cubren detección de intención**, no ejecución de notificación
8. **La tabla `admin_users` existe solo para el panel web admin**, no para notificaciones Telegram

---

## Anexo: Cómo SÍ se comunican los datos internos (para contexto)

| Evento | Qué pasa realmente | Quién lo ve |
|--------|-------------------|-------------|
| Usuario crea lead (`create_lead`) | Se guarda en tabla `leads` con `assigned_admin_id` opcional | Admin en panel web (`/admin/leads`) |
| Usuario agenda cita (`schedule_visit`) | Se crea en tabla `appointments` con `status=REQUESTED` | Admin en panel web (`/admin/appointments`) |
| Usuario guarda búsqueda (`save_search`) | Se guarda en `saved_searches`; worker hourly evalúa matches | Usuario recibe Telegram si hay match (worker `notify`) |
| Usuario pide "hablar con asesor" | LLM responde: "No tengo canal directo..." | Solo el usuario |

**Conclusión final:** El sistema está diseñado para que **el admin humano entre al panel web** a revisar leads y citas, NO para que el agente le notifique proactivamente por Telegram u otro canal.