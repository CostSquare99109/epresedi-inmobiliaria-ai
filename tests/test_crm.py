"""CRM: favorites, saved searches, leads, per-user isolation."""
from __future__ import annotations

from sqlalchemy import select

from app.crm import service as crm
from app.database.models import LeadStatus, Property
from app.memory import service as memory_service


async def _ensure_user(session, user_id: int) -> int:
    """CRM rows reference users.id (FK): ensure the AppUser row exists."""
    await memory_service.get_or_create_user(session, user_id, "crm", "CRM")
    return user_id


async def _some_property(session) -> Property:
    return (await session.execute(
        select(Property).where(Property.code == "PROP-0001")
    )).scalar_one()


async def test_favorite_add_list_remove(session, user_id):
    await _ensure_user(session, user_id)
    prop = await _some_property(session)
    assert await crm.add_favorite(session, user_id, prop.id) is True
    assert await crm.add_favorite(session, user_id, prop.id) is False  # no duplicate
    favorites = await crm.list_favorites(session, user_id)
    assert [p.id for p in favorites] == [prop.id]
    assert await crm.is_favorite(session, user_id, prop.id) is True
    assert await crm.remove_favorite(session, user_id, prop.id) is True
    assert await crm.remove_favorite(session, user_id, prop.id) is False
    assert await crm.list_favorites(session, user_id) == []


async def test_favorites_are_isolated_per_user(session, user_id):
    await _ensure_user(session, user_id)
    prop = await _some_property(session)
    other_user = user_id + 777_777
    await crm.add_favorite(session, user_id, prop.id)
    assert await crm.is_favorite(session, other_user, prop.id) is False


async def test_saved_search_save_list_deactivate(session, user_id):
    await _ensure_user(session, user_id)
    filters = {"property_type": "casa", "max_price": 300_000_000, "bedrooms": 3}
    ss = await crm.save_search(session, user_id, "Casa 300M", filters)
    items = await crm.list_saved_searches(session, user_id)
    assert ss.id in {s.id for s in items}
    found = next(s for s in items if s.id == ss.id)
    assert found.filters == filters
    assert found.active is True
    assert await crm.deactivate_saved_search(session, user_id, ss.id) is True
    assert await crm.list_saved_searches(session, user_id) == []


async def test_saved_searches_are_isolated_per_user(session, user_id):
    await _ensure_user(session, user_id)
    await crm.save_search(session, user_id, "mía", {"city": "Carepa"})
    other = await crm.list_saved_searches(session, user_id + 888_888)
    assert other == []


async def test_lead_create_update_status_flow(session, user_id):
    await _ensure_user(session, user_id)
    lead = await crm.get_or_create_lead(session, user_id)
    assert lead.status == LeadStatus.NEW
    again = await crm.get_or_create_lead(session, user_id)
    assert again.id == lead.id  # same lead reused

    updated = await crm.update_lead(session, lead.id, {
        "name": "Ana", "phone": "+573001112233", "budget": 300_000_000, "status": "INTERESTED",
    })
    assert updated.name == "Ana"
    assert updated.phone == "+573001112233"
    assert updated.status == LeadStatus.INTERESTED

    profile = await crm.get_customer_profile(session, user_id)
    assert profile["lead_id"] == str(lead.id)
    assert profile["name"] == "Ana"

    await crm.set_lead_status_from_appointment(session, lead.id)
    refreshed = await crm.get_or_create_lead(session, user_id)
    assert refreshed.status == LeadStatus.VISIT_SCHEDULED


async def test_lead_rejects_invalid_status(session, user_id):
    await _ensure_user(session, user_id)
    lead = await crm.get_or_create_lead(session, user_id)
    updated = await crm.update_lead(session, lead.id, {"status": "SUPERNOVA"})
    assert updated.status != "SUPERNOVA"  # invalid statuses ignored
    assert updated.status == lead.status
