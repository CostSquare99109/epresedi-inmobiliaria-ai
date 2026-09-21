"""Regression test: brand name must be 'epresedi' in all user-facing outputs."""
from __future__ import annotations

import pytest

from app.agents.prompts_v2 import SYSTEM_PROMPT, build_system_prompt
from app.agents.prompts import SYSTEM_PROMPT as LEGACY_SYSTEM_PROMPT
from app.agents.tool_specs import TOOL_SPECS
from app.core.bizconfig import SETTING_DEFAULTS


def test_system_prompt_v2_uses_canonical_brand():
    """SYSTEM_PROMPT v2 must identify as 'epresedi' (lowercase)."""
    assert "Eres epresedi" in SYSTEM_PROMPT
    assert "como epresedi" in SYSTEM_PROMPT
    assert "Expresedi" not in SYSTEM_PROMPT
    assert "EXPRESEDI" not in SYSTEM_PROMPT


def test_legacy_system_prompt_uses_canonical_brand():
    """Legacy SYSTEM_PROMPT must identify as 'epresedi'."""
    assert "asistente virtual de epresedi" in LEGACY_SYSTEM_PROMPT
    assert "Expresedi" not in LEGACY_SYSTEM_PROMPT
    assert "EXPRESEDI" not in LEGACY_SYSTEM_PROMPT


def test_tool_specs_agent_introduced_description():
    """update_conversation_state tool must reference 'epresedi'."""
    tool = next(t for t in TOOL_SPECS if t["function"]["name"] == "update_conversation_state")
    desc = tool["function"]["parameters"]["properties"]["agent_introduced"]["description"]
    assert "epresedi" in desc.lower()
    assert "Expresedi" not in desc
    assert "EXPRESEDI" not in desc


def test_bizconfig_default_company_name():
    """Default company name must be 'epresedi Inmobiliaria'."""
    assert SETTING_DEFAULTS["company_name"] == "epresedi Inmobiliaria"
    assert "EXPRESEDI" not in SETTING_DEFAULTS["company_name"]


def test_greeting_contains_canonical_brand():
    """Greeting in prompt must use 'epresedi'."""
    prompt = build_system_prompt(
        turn_context="Conversación nueva: sí\nAgente ya presentado: no"
    )
    # The prompt includes guidance for greeting
    assert "epresedi" in prompt.lower()
    assert "Expresedi" not in prompt
    assert "EXPRESEDI" not in prompt


if __name__ == "__main__":
    pytest.main([__file__, "-v"])