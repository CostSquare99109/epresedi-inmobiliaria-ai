from app.agents.prompts_v2 import SYSTEM_PROMPT, build_system_prompt
from app.agents.tool_specs import TOOL_SPECS


def _tool(name: str) -> dict:
    for spec in TOOL_SPECS:
        fn = spec.get("function", {})
        if fn.get("name") == name:
            return fn
    raise AssertionError(f"Tool no encontrada: {name}")


def test_active_prompt_has_explicit_greeting_policy():
    assert "# SALUDOS Y SMALL TALK" in SYSTEM_PROMPT
    assert "«Hola, busco un apartamento en Carepa»" in SYSTEM_PROMPT
    assert "saludo puro" in SYSTEM_PROMPT
    assert "Nunca conviertas un saludo simple en una presentación comercial." in SYSTEM_PROMPT


def test_active_prompt_exposes_turn_context():
    prompt = build_system_prompt(
        turn_context="Conversación nueva: sí\nAgente ya presentado: no"
    )
    assert "# Contexto de turno" in prompt
    assert "Conversación nueva: sí" in prompt
    assert "Agente ya presentado: no" in prompt


def test_update_state_allows_agent_introduced():
    tool = _tool("update_conversation_state")
    props = tool["parameters"]["properties"]
    assert props["agent_introduced"]["type"] == "boolean"
    assert "presenta explícitamente como epresedi" in props["agent_introduced"]["description"]
