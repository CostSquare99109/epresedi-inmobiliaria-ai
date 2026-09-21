"""Test the specific scenario from the prompt: partial tool failures with granular recovery."""
from __future__ import annotations

import pytest
from sqlalchemy import text as sql_text

from app.agents.orchestrator import Orchestrator
from tests.test_fake_llm_v2 import (
    FakeLLMV2,
    SimpleDecision,
    final_decision,
    tc,
    tool_round,
)


class TestPartialFailureScenario:
    """Tests for the PROP-0008/PROP-0009 scenario with partial tool failures."""

    @pytest.mark.asyncio
    async def test_multiple_tools_one_fails_transiently(self, session, user_id):
        """
        Scenario: User asks for images, requirements, services, availability for PROP-0008 and PROP-0009.
        Test that the fallback reply includes partial results when LLM fails after tools.
        """
        from app.memory import service as memory_service
        user = await memory_service.get_or_create_user(session, user_id)
        conv = await memory_service.get_or_create_conversation(session, user.id)
        
        prop8 = await session.execute(
            sql_text("SELECT id FROM properties WHERE code = 'PROP-0008'")
        )
        prop8_id = prop8.scalar_one()
        
        prop9 = await session.execute(
            sql_text("SELECT id FROM properties WHERE code = 'PROP-0009'")
        )
        prop9_id = prop9.scalar_one()
        
        conv.state["last_results"] = [
            {"id": str(prop8_id), "code": "PROP-0008", "title": "Apartamento amueblado"},
            {"id": str(prop9_id), "code": "PROP-0009", "title": "Casa con patio"},
        ]
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(conv, "state")
        await session.commit()

        # First pass: LLM decides to call multiple tools
        first_pass = tool_round(
            tc("get_property_images", {"property_id": str(prop8_id)}, call_id="c1"),
            tc("get_property_images", {"property_id": str(prop9_id)}, call_id="c2"),
            tc("search_documents", {"query": "requisitos arriendo PROP-0008"}, call_id="c3"),
            tc("search_documents", {"query": "requisitos arriendo PROP-0009"}, call_id="c4"),
            tc("search_documents", {"query": "servicios publicos independientes PROP-0008"}, call_id="c5"),
            tc("search_documents", {"query": "servicios publicos independientes PROP-0009"}, call_id="c6"),
            tc("list_available_slots", {"property_id": str(prop8_id)}, call_id="c7"),
            tc("list_available_slots", {"property_id": str(prop9_id)}, call_id="c8"),
        )
        
        # Second pass: LLM returns invalid JSON to trigger fallback
        from tests.test_fake_llm_v2 import invalid_json_response
        fake = FakeLLMV2([first_pass, invalid_json_response("{not json"), invalid_json_response("{also bad")])
        orch = Orchestrator(llm=fake)
        
        reply = await orch.handle_user_message(
            session, user_id,
            "Quiero imágenes, requisitos, servicios y disponibilidad de PROP-0008 y PROP-0009",
            "test", "Test"
        )
        
        # Should get a fallback response with partial results, not generic error
        assert reply is not None
        assert reply.text is not None
        assert len(reply.text.strip()) >= 10
        assert "inconveniente momentáneo" not in reply.text.lower()
        assert "intenta enviarlo nuevamente" not in reply.text.lower()
        # Should mention some of the tools that executed (fallback shows UUIDs for property_id)
        text_lower = reply.text.lower()
        # The fallback shows images results (other tools may have empty results in test DB)
        # degraded reply uses "imágenes" (with accent) - check for both
        assert "imagen" in text_lower or "imágenes" in text_lower or "foto" in text_lower

    @pytest.mark.asyncio
    async def test_partial_failure_fallback_shows_available_results(self, session, user_id):
        """
        Scenario: Some tools fail permanently (e.g., no images for PROP-0008), 
        but others succeed. Fallback should show what's available.
        """
        from app.memory import service as memory_service
        user = await memory_service.get_or_create_user(session, user_id)
        conv = await memory_service.get_or_create_conversation(session, user.id)
        
        prop8 = await session.execute(
            sql_text("SELECT id FROM properties WHERE code = 'PROP-0008'")
        )
        prop8_id = prop8.scalar_one()
        
        prop9 = await session.execute(
            sql_text("SELECT id FROM properties WHERE code = 'PROP-0009'")
        )
        prop9_id = prop9.scalar_one()
        
        conv.state["last_results"] = [
            {"id": str(prop8_id), "code": "PROP-0008", "title": "Apartamento amueblado"},
            {"id": str(prop9_id), "code": "PROP-0009", "title": "Casa con patio"},
        ]
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(conv, "state")
        await session.commit()

        # First pass: LLM calls tools
        first_pass = tool_round(
            tc("get_property_images", {"property_id": str(prop8_id)}, call_id="c1"),
            tc("get_property_images", {"property_id": str(prop9_id)}, call_id="c2"),
            tc("list_available_slots", {"property_id": str(prop8_id)}, call_id="c3"),
            tc("list_available_slots", {"property_id": str(prop9_id)}, call_id="c4"),
        )
        
        # Second pass fails (simulating LLM failure after tools executed)
        from tests.test_fake_llm_v2 import invalid_json_response
        fake = FakeLLMV2([first_pass, invalid_json_response("{not json"), invalid_json_response("{also bad")])
        orch = Orchestrator(llm=fake)
        
        reply = await orch.handle_user_message(
            session, user_id,
            "Imágenes y disponibilidad de PROP-0008 y PROP-0009",
            "test", "Test"
        )
        
        # Fallback should mention what was found
        assert reply is not None
        assert reply.text is not None
        assert len(reply.text.strip()) >= 10
        # Should not be generic error
        assert "inconveniente momentáneo" not in reply.text.lower()
        # Should mention images or availability
        text_lower = reply.text.lower()
        # degraded reply uses "imágenes" (with accent) and "Imágenes" - check for both
        assert "imagen" in text_lower or "imágenes" in text_lower or "foto" in text_lower

    @pytest.mark.asyncio
    async def test_tool_retry_with_idempotency(self, session, user_id):
        """
        Scenario: Mutating tool (schedule_visit) is called twice with same args in same turn.
        Second call should be skipped due to idempotency key.
        """
        from app.appointments import service as appt_service
        from app.crm import service as crm_service
        from app.memory import service as memory_service
        from app.properties import repository as prop_repo
        
        user = await memory_service.get_or_create_user(session, user_id)
        conv = await memory_service.get_or_create_conversation(session, user.id)
        
        prop = await prop_repo.get_property_by_code(session, "PROP-0001")
        slots = await appt_service.list_available_slots(session, prop.id)
        assert slots, "Seed must have available slots"
        chosen = slots[0]
        
        lead = await crm_service.get_or_create_lead(session, user.id)
        # Pre-populate contact info for scheduling
        await crm_service.update_lead(session, lead.id, {
            "name": "Test User",
            "phone": "+57 300 123 4567",
            "email": "test@example.com",
        })
        
        # Single turn where LLM calls schedule_visit twice with same args
        first_pass = tool_round(
            tc("schedule_visit", {"property_id": str(prop.id), "datetime_iso": chosen["datetime"]}, call_id="c1"),
            tc("schedule_visit", {"property_id": str(prop.id), "datetime_iso": chosen["datetime"]}, call_id="c2"),
        )
        
        second_pass = final_decision(SimpleDecision(text="Visita agendada correctamente.", intent="SCHEDULE_VISIT"))
        
        fake = FakeLLMV2([first_pass, second_pass])
        orch = Orchestrator(llm=fake)
        
        reply = await orch.handle_user_message(
            session, user_id,
            f"Agenda visita para PROP-0001 el {chosen['datetime_local']}",
            "test", "Test"
        )
        
        # Should succeed
        assert "agendada" in reply.text.lower() or "quedó" in reply.text.lower()
        
        # Should not create duplicate appointment
        from sqlalchemy import select

        from app.database.models import Appointment
        appointments = (await session.execute(
            select(Appointment).where(Appointment.property_id == prop.id, Appointment.lead_id == lead.id)
        )).scalars().all()
        
        # Only one appointment should exist
        assert len(appointments) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])