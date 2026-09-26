"""OpenAI-style tool schemas for NVIDIA tool calling (see docs/agent-tools.md).

`send_response` es la tool TERMINAL: cuando el agente tiene todo lo que necesita,
la llama y el runtime entrega la respuesta al usuario (sin otra llamada al LLM).
Cada descripción explica qué hace la tool, qué NO hace y cuándo usarla.
"""
from __future__ import annotations

import json

TOOL_SPECS: list[dict] = [
    {"type": "function", "function": {
        "name": "send_response",
        "description": (
            "ENTREGA TU RESPUESTA FINAL AL USUARIO Y TERMINA EL TURNO. Llámala "
            "cuando ya tengas suficiente información confirmada (tras ejecutar las "
            "tools que necesites) o cuando debas pedir aclaración al usuario. "
            "El texto es Markdown para Telegram, en español. NO la llames junto con "
            "otras tools en el mismo lote: primero deja que las otras tools terminen. "
            "Si un argumento es inválido recibirás el error como resultado y podrás "
            "reintentarla."
        ),
        "parameters": {"type": "object", "properties": {
            "text": {"type": "string", "description": "Respuesta final al usuario (Markdown, español)"},
            "intent": {
                "type": "string",
                "description": "Intención principal del turno (auditoría)",
                "enum": [
                    "SEARCH_PROPERTY", "PROPERTY_DETAILS", "PROPERTY_IMAGES", "COMPARE_PROPERTIES",
                    "PROPERTY_DOCUMENT_QUESTION", "PRICE_QUERY", "LOCATION_QUERY", "SAVE_PROPERTY",
                    "REMOVE_PROPERTY", "SAVE_SEARCH", "LIST_SAVED_SEARCHES", "SCHEDULE_VISIT",
                    "CANCEL_APPOINTMENT", "CONTACT_AGENT", "FINANCING_QUESTION", "SELL_PROPERTY",
                    "RENT_PROPERTY", "GENERAL_FAQ", "GENERAL", "GREETING", "UNKNOWN",
                ],
            },
            "images": {
                "type": "array", "items": {"type": "string"},
                "description": "ENVÍA realmente las fotos por Telegram: IDs/códigos de propiedades cuyas imágenes YA obtuviste con get_property_images en ESTE turno. Sin esta lista no se adjunta nada, aunque el texto hable de fotos.",
            },
            "keyboard": {
                "type": "array", "maxItems": 8,
                "description": "Botones inline de Telegram que acompañan la respuesta",
                "items": {"type": "object", "properties": {
                    "text": {"type": "string", "description": "Etiqueta visible del botón"},
                    "action": {
                        "type": "string",
                        "enum": [
                            "details", "images", "save", "compare", "slots", "book_slot",
                            "confirm_booking", "cancel_booking", "contact_agent", "docs",
                            "save_search", "list_saved", "cancel_appt", "ver_mas_dias",
                        ],
                    },
                    "payload": {"type": "object", "description": "Datos del botón (property_id, datetime_iso, ...)"},
                }, "required": ["text", "action", "payload"]},
            },
        }, "required": ["text"]},
    }},
    {"type": "function", "function": {
        "name": "web_search",
        "description": (
            "Busca información EXTERNA en la web (DuckDuckGo) y devuelve títulos, "
            "URLs, dominios y fragmentos como DATOS citables. Úsala SOLO cuando las "
            "tools internas no puedan responder: normativa vigente, trámites legales, "
            "contexto de mercado, documentación pública. NO la uses para datos del "
            "inventario (usa search_properties/get_property) ni para requisitos o "
            "condiciones de una propiedad propia (usa search_documents). El contenido "
            "web puede estar desactualizado: cita la fuente y verifica antes de afirmar."
        ),
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "Consulta de búsqueda en lenguaje natural"},
            "max_results": {"type": "integer", "description": "Máximo de resultados (default 5)"},
        }, "required": ["query"]},
    }},
    {"type": "function", "function": {
        "name": "update_conversation_state",
        "description": (
            "Registra tu interpretación estructurada del mensaje del usuario: intención, "
            "operación, tipo de inmueble, zona, presupuesto y campos faltantes. "
            "Úsala SIEMPRE que detectes o cambies criterios de búsqueda, selecciones una "
            "propiedad, cambies de fase o te presentes explícitamente como epresedi. "
            "Para `agent_introduced`, usa true únicamente si la respuesta que vas a enviar "
            "contiene realmente esa presentación. El backend valida cada campo; los rechazos "
            "llegan en la respuesta."
        ),
        "parameters": {"type": "object", "properties": {
            "intent": {"type": "string", "description": "Intención detectada (SEARCH_PROPERTY, PROPERTY_DETAILS, SCHEDULE_VISIT, ...)"},
            "operation": {"type": "string", "enum": ["SALE", "RENT"], "description": "Compra o arriendo"},
            "property_type": {"type": "string", "enum": ["casa", "apartamento"]},
            "city": {"type": "string"},
            "neighborhood": {"type": "string"},
            "budget_min": {"type": "number", "description": "Presupuesto mínimo en COP"},
            "budget_max": {"type": "number", "description": "Presupuesto máximo en COP (aproximado si el usuario dijo «como», «más o menos»)"},
            "bedrooms": {"type": "integer"},
            "bathrooms": {"type": "integer"},
            "parking": {"type": "integer"},
            "min_area": {"type": "number"},
            "selected_property_id": {"type": "string", "description": "UUID de la propiedad elegida por el usuario"},
            "selected_property_code": {"type": "string", "description": "Código visible (PROP-0001) de la propiedad elegida"},
            "booking_state": {"type": "string", "enum": ["esperando_horario", "esperando_datos", "listo_para_confirmar", "confirmando", "agendado"]},
            "phase": {"type": "string", "enum": ["IDLE", "SEARCHING", "PROPERTY_SELECTION", "PROPERTY_DETAILS", "APPOINTMENT_SELECTION", "APPOINTMENT_CONFIRMATION", "APPOINTMENT_COMPLETED", "GENERAL", "ERROR"]},
            "missing_fields": {"type": "array", "items": {"type": "string", "enum": ["operation", "property_type", "city", "budget_max", "bedrooms", "property", "datetime", "contact"]}},
            "notes": {"type": "string", "description": "Nota breve de contexto (máx. 300 caracteres)"},
            "agent_introduced": {
                "type": "boolean",
                "description": "Usa true únicamente cuando tu respuesta actual se presenta explícitamente como epresedi. Una vez verdadero, no lo vuelvas a poner en false."
            },
        }},
    }},

    {"type": "function", "function": {
        "name": "search_properties",
        "description": (
            "Busca el inventario REAL (solo propiedades disponibles). Devuelve datos reales: "
            "nunca inventes precios ni fichas. Incluye SOLO los filtros que el usuario mencionó "
            "explícitamente en este turno o que ya están confirmados en el estado/preferencias — "
            "NUNCA rellenes min_price/max_price (ni ningún otro filtro) con un valor supuesto, "
            "típico o 'razonable' cuando el usuario no dio presupuesto. Si el usuario dijo un "
            "presupuesto aproximado, envíalo en max_price; si no mencionó presupuesto, omite "
            "min_price y max_price por completo (busca sin tope de precio). Si no hubo resultados, "
            "amplía criterios explícitamente y vuelve a llamar. "
            "REGLA PREVIA OBLIGATORIA: el inventario solo tiene casa y apartamento. Si el usuario "
            "pidió otro tipo (finca, lote, bodega, local, oficina, parcela, proyecto, etc.), NO "
            "llames esta tool ni muestres fichas de otro tipo: aclara primero que ese tipo no está "
            "disponible y pregunta si quiere ver alternativas o que le avisemos."
        ),
        "parameters": {"type": "object", "properties": {
            "filters": {"type": "object", "description": "Filtros estructurados", "properties": {
                "property_type": {"type": "string", "enum": ["casa", "apartamento"]},
                "operation": {"type": "string", "enum": ["SALE", "RENT"]},
                "city": {"type": "string"},
                "min_price": {"type": "number"}, "max_price": {"type": "number"},
                "bedrooms": {"type": "integer"}, "bathrooms": {"type": "integer"},
                "parking": {"type": "integer"}, "min_area": {"type": "number"},
                "floors": {"type": "integer", "description": "Número mínimo de pisos totales de la propiedad"},
                "offered_floor": {"type": "integer", "description": "El usuario quiere ofertado ESE piso («solo el segundo piso», «piso 1»). Distingue floor_offer_type en cada resultado: single_floor/multiple_floors con ese piso ≠ propiedad completa."},
                "floor_offer_type": {"type": "string", "enum": ["full_property", "single_floor", "multiple_floors", "partial"], "description": "Qué parte se ofrece: propiedad completa, un piso, varios pisos o una parte (anexo/apartamento interior)"},
            }},
            "semantic_query": {"type": "string"},
        }},
    }},
    {"type": "function", "function": {
        "name": "get_property",
        "description": (
            "Ficha completa de una propiedad: código (PROP-0001), id, ordinal («la segunda») o "
            "referencia contextual («la que me mostraste»). Úsala cuando el usuario pida "
            "detalles, precio, características o seleccione «esa» propiedad."
        ),
        "parameters": {"type": "object", "properties": {"property_ref": {"type": "string"}}},
    }},
    {"type": "function", "function": {
        "name": "compare_properties", "description": "Compara 2-4 propiedades reales por sus datos almacenados.",
        "parameters": {"type": "object", "properties": {"property_refs": {"type": "array", "items": {"type": "string"}}}},
    }},
    {"type": "function", "function": {
        "name": "search_documents",
        "description": (
            "Recupera información de documentos/proyectos/políticas (RAG). Devuelve chunks con "
            "fuente, página y relevancia. Úsala solo cuando la pregunta requiera conocimiento "
            "documental que no está en el inventario (requisitos, financiación, reglamentos)."
        ),
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "property_id": {"type": "string"}}},
    }},
    {"type": "function", "function": {
        "name": "get_property_images",
        "description": (
            "Obtiene las FOTOS REALES de una propiedad para ENVIARLAS por Telegram. "
            "Resuelve código (PROP-XXXX), UUID u ordinal («la segunda»); si el usuario dice "
            "«esa/la casa» sin código, omite property_id y se usa la propiedad en foco. "
            "Usa 'limit' para cardinalidad (1 = «una imagen», N = «N fotos», sin limit = todas). "
            "Cada imagen trae 'group' (portada, piso, bano, cocina, lavadero, parqueadero, "
            "extra, general), 'extra_name' (p. ej. Piscina/Chimenea cuando group=extra), "
            "'name', 'filename' y 'description'. "
            "Si el usuario pide una característica («muéstrame el baño», «foto de la cocina», "
            "«la piscina»), pasa 'group' (bano, cocina, lavadero, piso, portada, parqueadero, "
            "extra) y, para extras, 'extra_name'. Envía SOLO imágenes del grupo pedido: nunca "
            "sustituyas con fotos de otra característica. "
            "Después DEBES poner ese property_id en send_response.images para que el envío ocurra. "
            "Si devuelve error NO_IMAGES/IMAGE_FILES_MISSING, la propiedad no tiene fotos enviables "
            "(de ese grupo): dilo honestamente y NUNCA afirmes un envío."
        ),
        "parameters": {"type": "object", "properties": {"property_id": {"type": "string", "description": "Código PROP-XXXX, UUID u ordinal; omítelo para «esa/la casa» (contexto)"}, "limit": {"type": "integer", "description": "Máximo número de imágenes a devolver (opcional, default: todas)"}, "group": {"type": "string", "enum": ["portada", "piso", "bano", "cocina", "lavadero", "parqueadero", "extra", "general"], "description": "Filtra por característica: bano («muéstrame el baño»), cocina, lavadero, piso («segundo piso»), portada, parqueadero o extra (piscina, chimenea...)"}, "extra_name": {"type": "string", "description": "Nombre del extra personalizado cuando group=extra (p. ej. Piscina)"}}},
    }},
    {"type": "function", "function": {
        "name": "get_branch_info", "description": "Obtiene la información de la sede (oficina) asociada a una propiedad: nombre, ciudad, barrio, dirección completa.",
        "parameters": {"type": "object", "properties": {"property_id": {"type": "string"}}, "required": ["property_id"]},
    }},
    {"type": "function", "function": {
        "name": "get_business_hours", "description": "Obtiene el horario de atención de una sede. Puede llamarse con property_id (usa la sede de la propiedad) o branch_id directo. Devuelve horarios por día de la semana en zona horaria America/Bogota.",
        "parameters": {"type": "object", "properties": {"property_id": {"type": "string"}, "branch_id": {"type": "string"}}},
    }},
    {"type": "function", "function": {
        "name": "list_branches", "description": "Lista todas las sedes/oficinas de la inmobiliaria con su información de contacto y ubicación.",
        "parameters": {"type": "object", "properties": {"active_only": {"type": "boolean", "description": "Solo sedes activas (default: true)"}}},
    }},
    {"type": "function", "function": {
        "name": "save_property", "description": "Guarda en favoritos.",
        "parameters": {"type": "object", "properties": {"property_id": {"type": "string"}}},
    }},
    {"type": "function", "function": {
        "name": "remove_saved_property", "description": "Quita de favoritos.",
        "parameters": {"type": "object", "properties": {"property_id": {"type": "string"}}},
    }},
    {"type": "function", "function": {
        "name": "list_favorites", "description": "Lista las propiedades guardadas en favoritos del usuario.",
        "parameters": {"type": "object", "properties": {}},
    }},
    {"type": "function", "function": {
        "name": "save_search", "description": "Guarda búsqueda estructurada para alertas.",
        "parameters": {"type": "object", "properties": {"name": {"type": "string"}, "filters": {"type": "object"}}},
    }},
    {"type": "function", "function": {
        "name": "list_saved_searches", "description": "Lista búsquedas guardadas.", "parameters": {"type": "object", "properties": {}},
    }},
    {"type": "function", "function": {
        "name": "create_alert", "description": (
            "CREA una alerta persistente de propiedades. Úsala SOLO cuando el usuario haya confirmado "
            "explícitamente los criterios y quiera ser notificado en el futuro. Requiere: name (nombre "
            "descriptivo), filters (criterios estructurados: operation, property_type, city, "
            "min_price, max_price, bedrooms, bathrooms, parking, min_area), frequency_hours (opcional, "
            "default 1, rango 1-168). El sistema valida y persiste la alerta; luego el scheduler la "
            "evalúa automáticamente y notifica por Telegram cuando aparecen propiedades nuevas que coinciden. "
            "NO la uses para búsquedas puntuales (usa search_properties)."
        ),
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string", "description": "Nombre descriptivo de la alerta (ej: 'Casas Carepa arriendo < 1.5M')"},
            "filters": {"type": "object", "description": "Criterios estructurados", "properties": {
                "property_type": {"type": "string", "enum": ["casa", "apartamento"]},
                "operation": {"type": "string", "enum": ["SALE", "RENT"]},
                "city": {"type": "string"},
                "min_price": {"type": "number"}, "max_price": {"type": "number"},
                "bedrooms": {"type": "integer"}, "bathrooms": {"type": "integer"},
                "parking": {"type": "integer"}, "min_area": {"type": "number"},
            }},
            "frequency_hours": {"type": "integer", "description": "Frecuencia de evaluación en horas (1-168, default 1)"},
        }, "required": ["name", "filters"]},
    }},
    {"type": "function", "function": {
        "name": "list_alerts", "description": "Lista alertas del usuario. Opcional: filtrar por status (active, paused, cancelled).",
        "parameters": {"type": "object", "properties": {"status": {"type": "string", "enum": ["active", "paused", "cancelled"]}}},
    }},
    {"type": "function", "function": {
        "name": "get_alert", "description": "Obtiene detalles de una alerta específica por su ID.",
        "parameters": {"type": "object", "properties": {"alert_id": {"type": "string"}}, "required": ["alert_id"]},
    }},
    {"type": "function", "function": {
        "name": "update_alert", "description": "Actualiza una alerta existente: name, filters, frequency_hours, status.",
        "parameters": {"type": "object", "properties": {
            "alert_id": {"type": "string"},
            "name": {"type": "string"},
            "filters": {"type": "object"},
            "frequency_hours": {"type": "integer"},
            "status": {"type": "string", "enum": ["active", "paused", "cancelled"]},
        }, "required": ["alert_id"]},
    }},
    {"type": "function", "function": {
        "name": "pause_alert", "description": "Pausa una alerta (deja de generar notificaciones).",
        "parameters": {"type": "object", "properties": {"alert_id": {"type": "string"}}, "required": ["alert_id"]},
    }},
    {"type": "function", "function": {
        "name": "resume_alert", "description": "Reactiva una alerta pausada.",
        "parameters": {"type": "object", "properties": {"alert_id": {"type": "string"}}, "required": ["alert_id"]},
    }},
    {"type": "function", "function": {
        "name": "delete_alert", "description": "Cancela (elimina) una alerta permanentemente.",
        "parameters": {"type": "object", "properties": {"alert_id": {"type": "string"}}, "required": ["alert_id"]},
    }},
    {"type": "function", "function": {
        "name": "get_notification_history", "description": "Historial de notificaciones enviadas por alerta.",
        "parameters": {"type": "object", "properties": {"alert_id": {"type": "string"}, "limit": {"type": "integer", "description": "Máximo resultados (default 50)"}}},
    }},
    {"type": "function", "function": {
        "name": "create_lead", "description": "Crea/actualiza el lead del usuario con datos observables. Incluye SIEMPRE el email cuando el usuario lo dé: es obligatorio para agendar.",
        "parameters": {"type": "object", "properties": {"name": {"type": "string"}, "phone": {"type": "string"}, "email": {"type": "string", "description": "Correo electrónico del usuario (obligatorio para agendar)"}, "budget": {"type": "number"}, "status": {"type": "string"}, "notes": {"type": "string"}}},
    }},
    {"type": "function", "function": {
        "name": "get_customer_profile", "description": "Perfil del cliente.", "parameters": {"type": "object", "properties": {}},
    }},
    {"type": "function", "function": {
        "name": "list_available_slots",
        "description": (
            "Horarios REALES disponibles para visitar una propiedad. Úsala antes de agendar: "
            "nunca ofrezcas horarios que no vengan de aquí. Devuelve datetime (ISO UTC) y label. "
            "Si el usuario ya dio una fecha/hora concreta, pásala en 'requested_datetime' para "
            "verificar disponibilidad exacta y obtener alternativas cercanas reales."
        ),
        "parameters": {"type": "object", "properties": {
            "property_id": {"type": "string"},
            "requested_datetime": {"type": "string", "description": "Datetime ISO (zona horaria del negocio) que el usuario solicita, ej: '2026-09-21T14:00'. Opcional."},
            "window_hours": {"type": "integer", "description": "Ventana en horas alrededor de requested_datetime para buscar alternativas cercanas (default: 2). Opcional."}
        }, "required": ["property_id"]},
    }},
    {"type": "function", "function": {
        "name": "schedule_visit",
        "description": (
            "CREA la cita solo si ya elegiste un slot real y el usuario confirmó. No la llames "
            "para 'proponer': primero list_available_slots y espera la elección. Pasa SIEMPRE "
            "name, phone y email con los datos de contacto que dio el usuario (son obligatorios; "
            "si faltan, la tool devuelve MISSING_CONTACT_INFO y debes pedirlos, no decir "
            "'problema técnico'). Si la respuesta no trae appointment, la cita NO existe: no la "
            "anuncies como agendada. Si la respuesta SÍ trae appointment, la cita SÍ existe: "
            "confírmala con esos datos reales, nunca digas que falló."
        ),
        "parameters": {"type": "object", "properties": {"property_id": {"type": "string"}, "datetime_iso": {"type": "string"}, "notes": {"type": "string"}, "name": {"type": "string", "description": "Nombre completo del usuario (mínimo nombre + apellido)"}, "phone": {"type": "string", "description": "Teléfono/celular del usuario"}, "email": {"type": "string", "description": "Correo electrónico del usuario"}}},
    }},
    {"type": "function", "function": {
        "name": "cancel_appointment", "description": "Cancela cita por id.",
        "parameters": {"type": "object", "properties": {"appointment_id": {"type": "string"}}},
    }},
    {"type": "function", "function": {
        "name": "recommend_similar", "description": "Propiedades similares a una dada (recomendación real desde datos).",
        "parameters": {"type": "object", "properties": {"property_id": {"type": "string"}}},
    }},
    {"type": "function", "function": {
        "name": "reschedule_appointment",
        "description": (
            "Reprograma una cita activa validando disponibilidad. Solo cuando el usuario pida "
            "cambiar de horario y exista un appointment_id real."
        ),
        "parameters": {"type": "object", "properties": {
            "appointment_id": {"type": "string"}, "datetime_iso": {"type": "string"},
        }, "required": ["appointment_id", "datetime_iso"]},
    }},
    {"type": "function", "function": {
        "name": "list_appointments",
        "description": "Lista las citas/visitas reales del usuario. Úsala cuando pregunte por sus citas.",
        "parameters": {"type": "object", "properties": {}},
    }},
]


def tool_call_request_example() -> str:
    return json.dumps(TOOL_SPECS[0])
