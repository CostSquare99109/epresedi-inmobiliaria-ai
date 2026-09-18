"""OpenAI-style tool schemas for NVIDIA tool calling (see docs/agent-tools.md)."""
from __future__ import annotations

import json

TOOL_SPECS: list[dict] = [
    {"type": "function", "function": {
        "name": "search_properties",
        "description": "Busca propiedades con filtros estructurados y consulta semántica.",
        "parameters": {"type": "object", "properties": {
            "filters": {"type": "object", "description": "Filtros estructurados", "properties": {
                "property_type": {"type": "string", "enum": ["casa", "apartamento", "lote", "local", "oficina", "finca", "proyecto"]},
                "operation": {"type": "string", "enum": ["SALE", "RENT"]},
                "city": {"type": "string"},
                "min_price": {"type": "number"}, "max_price": {"type": "number"},
                "bedrooms": {"type": "integer"}, "bathrooms": {"type": "integer"},
                "parking": {"type": "integer"}, "min_area": {"type": "number"},
            }},
            "semantic_query": {"type": "string"},
        }},
    }},
    {"type": "function", "function": {
        "name": "get_property", "description": "Ficha completa de una propiedad por código, id o referencia contextual.",
        "parameters": {"type": "object", "properties": {"property_ref": {"type": "string"}}},
    }},
    {"type": "function", "function": {
        "name": "compare_properties", "description": "Compara varias propiedades.",
        "parameters": {"type": "object", "properties": {"property_refs": {"type": "array", "items": {"type": "string"}}}},
    }},
    {"type": "function", "function": {
        "name": "search_documents", "description": "Búsqueda RAG en documentos oficiales. Devuelve chunks citables.",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "property_id": {"type": "string"}}},
    }},
    {"type": "function", "function": {
        "name": "get_property_images", "description": "Lista imágenes locales de una propiedad.",
        "parameters": {"type": "object", "properties": {"property_id": {"type": "string"}}},
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
        "name": "save_search", "description": "Guarda búsqueda estructurada para alertas.",
        "parameters": {"type": "object", "properties": {"name": {"type": "string"}, "filters": {"type": "object"}}},
    }},
    {"type": "function", "function": {
        "name": "list_saved_searches", "description": "Lista búsquedas guardadas.", "parameters": {"type": "object", "properties": {}},
    }},
    {"type": "function", "function": {
        "name": "create_lead", "description": "Crea/actualiza el lead del usuario con datos observables.",
        "parameters": {"type": "object", "properties": {"name": {"type": "string"}, "phone": {"type": "string"}, "budget": {"type": "number"}, "status": {"type": "string"}, "notes": {"type": "string"}}},
    }},
    {"type": "function", "function": {
        "name": "get_customer_profile", "description": "Perfil del cliente.", "parameters": {"type": "object", "properties": {}},
    }},
    {"type": "function", "function": {
        "name": "list_available_slots", "description": "Horarios disponibles para visita.",
        "parameters": {"type": "object", "properties": {"property_id": {"type": "string"}}},
    }},
    {"type": "function", "function": {
        "name": "schedule_visit", "description": "Agenda visita (property_id + datetime ISO).",
        "parameters": {"type": "object", "properties": {"property_id": {"type": "string"}, "datetime_iso": {"type": "string"}, "notes": {"type": "string"}}},
    }},
    {"type": "function", "function": {
        "name": "cancel_appointment", "description": "Cancela cita por id.",
        "parameters": {"type": "object", "properties": {"appointment_id": {"type": "string"}}},
    }},
    {"type": "function", "function": {
        "name": "recommend_similar", "description": "Propiedades similares a una dada.",
        "parameters": {"type": "object", "properties": {"property_id": {"type": "string"}}},
    }},
]


def tool_call_request_example() -> str:
    return json.dumps(TOOL_SPECS[0])
