"""Short-term memory (recent messages) + persistent preferences + context references."""
from __future__ import annotations

import re
import uuid as uuid_mod
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import AppUser, Conversation, Message, Role, UserPreference

PREF_FIELDS = {"city", "property_type", "operation", "min_budget", "max_budget", "bedrooms", "bathrooms", "parking"}

ORDINALS = {
    "primera": 1, "primer": 1, "primero": 1, "segunda": 2, "segundo": 2, "tercera": 3,
    "tercer": 3, "tercero": 3, "cuarta": 4, "cuarto": 4, "quinta": 5, "quinto": 5,
    "1": 1, "2": 2, "3": 3, "4": 4, "5": 5,
}

REFERENCE_RE = re.compile(
    r"\b(?:la|el|los|las|esa|ese|esas|eses|aquel|aquella)?\s*"
    r"(?:primera?|segund[ao]|tercer[ao]|cuart[ao]|quint[ao]|opci[oó]n\s*\d+|\d+[oa]?)\b",
    re.IGNORECASE,
)


async def get_or_create_user(
    session: AsyncSession, telegram_user_id: int, username: str = "", first_name: str = ""
) -> AppUser:
    user = (await session.execute(
        select(AppUser).where(AppUser.id == telegram_user_id)
    )).scalar_one_or_none()
    if user is None:
        user = AppUser(id=telegram_user_id, username=username or "", first_name=first_name or "")
        session.add(user)
        await session.flush()
    else:
        await session.execute(
            update(AppUser).where(AppUser.id == user.id).values(
                username=username or user.username,
                first_name=first_name or user.first_name,
                last_seen_at=datetime.now(UTC),
            )
        )
        await session.refresh(user)
    return user


async def get_or_create_conversation(session: AsyncSession, user_id: int) -> Conversation:
    conv = (await session.execute(
        select(Conversation).where(Conversation.user_id == user_id).order_by(Conversation.updated_at.desc())
    )).scalars().first()
    if conv is None:
        conv = Conversation(user_id=user_id, state={}, summary="")
        session.add(conv)
        await session.flush()
    return conv


async def create_new_conversation(session: AsyncSession, user_id: int) -> Conversation:
    """Create a new conversation for the user, archiving the previous one.
    
    The previous conversation remains in the database for history/audit.
    The new conversation starts with empty state and summary.
    """
    conv = Conversation(user_id=user_id, state={}, summary="")
    session.add(conv)
    await session.flush()
    return conv


async def add_message(
    session: AsyncSession, conversation_id: uuid_mod.UUID, role: Role, content: str, meta: dict | None = None
) -> None:
    session.add(Message(conversation_id=conversation_id, role=role, content=content[:8000], meta=meta or {}))
    await session.flush()


async def recent_messages(session: AsyncSession, conversation_id: uuid_mod.UUID, limit: int = 12) -> list[Message]:
    rows = (await session.execute(
        select(Message).where(Message.conversation_id == conversation_id)
        .order_by(Message.id.desc()).limit(limit)
    )).scalars().all()
    return list(reversed(rows))


async def update_preferences(session: AsyncSession, user_id: int, filters_dict: dict) -> None:
    """Persists only observable, structured facts (never model guesses)."""
    pref = (await session.execute(
        select(UserPreference).where(UserPreference.user_id == user_id)
    )).scalar_one_or_none()
    if pref is None:
        pref = UserPreference(user_id=user_id, preferences={})
        session.add(pref)
    mapping = {
        "city": "city", "property_type": "property_type", "operation": "operation",
        "min_price": "min_budget", "max_price": "max_budget",
        "bedrooms": "bedrooms", "bathrooms": "bathrooms", "parking": "parking",
    }
    for src, dst in mapping.items():
        value = filters_dict.get(src)
        if value not in (None, "", 0):
            setattr(pref, dst, value)
    await session.flush()


async def get_preferences(session: AsyncSession, user_id: int) -> UserPreference | None:
    return (await session.execute(
        select(UserPreference).where(UserPreference.user_id == user_id)
    )).scalar_one_or_none()


def resolve_reference(text_msg: str, state: dict) -> tuple[int | None, str]:
    """Resolves 'la segunda', 'la de 280 millones', 'la primera' against last results.

    Returns (index_0based_or_None, how). Never guesses: unresolved → None."""
    low = (text_msg or "").lower()

    # price-based reference: "la de 280 millones"
    price_m = re.search(r"(?:la|el|ese|esa)?\s*(?:de\s*)?\$?(\d[\d.,]*)\s*(?:millones?|mill|mm)?", low)
    last_results = state.get("last_results") or []
    if price_m and any(k in low for k in ("de", "la", "el", "esa", "ese", "la que")):
        raw = price_m.group(1).replace(".", "").replace(",", "")
        try:
            value = float(raw)
            if value < 10_000:
                value *= 1_000_000
            for i, item in enumerate(last_results):
                if abs(float(item.get("price", 0)) - value) < 1000:
                    return i, "precio"
        except ValueError:
            pass

    # ordinal reference
    ordinal_m = re.search(r"(?:la|el|los|las|esa|ese)?\s*(?:opci[oó]n\s*)?(primera?|segund[ao]|tercer[ao]|cuart[ao]|quint[ao])\b", low)
    if not ordinal_m:
        ordinal_m = re.search(r"\b(opci[oó]n\s*([1-5])|([1-5])[oaª]\b)", low)
    if ordinal_m:
        groups = [g for g in ordinal_m.groups() if g]
        token = " ".join(groups).strip().lower()
        ordinal_map = {
            "primera": 0,
            "primer": 0,
            "primero": 0,
            "segunda": 1,
            "segundo": 1,
            "tercera": 2,
            "tercer": 2,
            "tercero": 2,
            "cuarta": 3,
            "cuarto": 3,
            "quinta": 4,
            "quinto": 4,
        }

        num = None
        for word, index in ordinal_map.items():
            if re.search(rf"\b{re.escape(word)}\b", token):
                num = index
                break

        if num is None:
            digit_match = re.search(r"\b([1-5])\b", token)
            if digit_match:
                num = int(digit_match.group(1)) - 1

        if num is not None and 0 <= num < len(last_results):
            return num, "ordinal"
    return None, ""
