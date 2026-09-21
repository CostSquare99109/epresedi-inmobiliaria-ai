"""Test bootstrap: isolated test database, local embeddings, no network.

Environment overrides happen BEFORE any ``app.*`` import so that
``get_settings()`` (lru_cached) picks up the test configuration.

Nothing here touches the development database: DATABASE_URL points at
``TEST_DATABASE_URL`` from .env, and storage/documents are redirected.
"""
from __future__ import annotations

import asyncio
import itertools
import os
import re
import uuid as uuid_mod
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_TEST_DB = "postgresql+psycopg://inmobiliaria:inmobiliaria@127.0.0.1:5432/inmobiliaria_test"


def _env_file_value(key: str) -> str:
    """Reads a single key from .env without importing the settings module."""
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        return ""
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        if name.strip() == key:
            return value.strip()
    return ""


TEST_DB_URL = (
    os.environ.get("TEST_DATABASE_URL")
    or _env_file_value("TEST_DATABASE_URL")
    or DEFAULT_TEST_DB
)

# --- environment pinning (must run before importing app.*) --------------------
os.environ["DATABASE_URL"] = TEST_DB_URL
os.environ["TEST_DATABASE_URL"] = TEST_DB_URL
os.environ["STORAGE_PATH"] = str(BASE_DIR / "storage_test")
os.environ["DOCUMENTS_PATH"] = str(BASE_DIR / "documents_test")
os.environ["LLM_MODE"] = "deterministic"       # never call NVIDIA from tests
os.environ["EMBEDDING_PROVIDER"] = "local"     # deterministic, offline
os.environ["NVIDIA_API_KEY"] = ""
os.environ["NVIDIA_MODEL"] = ""
os.environ["TELEGRAM_BOT_TOKEN"] = ""
os.environ["ADMIN_TOKEN"] = "test-admin-token"
os.environ["RATE_LIMIT_PER_MINUTE"] = "100000"
os.environ["LOG_LEVEL"] = "WARNING"

from app.ai.embeddings import LocalHashEmbedding, set_embedding_provider
from app.core.settings import get_settings
from app.database.base import AsyncSessionLocal

set_embedding_provider(LocalHashEmbedding(int(_env_file_value("EMBEDDING_DIM") or 256)))


# --------------------------------------------------------------------- database
def _ensure_database() -> None:
    from sqlalchemy import create_engine, text

    from app.database.base import server_admin_url

    admin_url = server_admin_url()
    db_name = get_settings().DATABASE_URL.rsplit("/", 1)[-1]
    if not re.fullmatch(r"[A-Za-z0-9_]+", db_name):  # pragma: no cover - guard
        raise RuntimeError(f"nombre de base de datos inválido: {db_name!r}")
    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": db_name}
            ).scalar()
            if not exists:
                conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    finally:
        engine.dispose()


def _run_migrations() -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(BASE_DIR / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", TEST_DB_URL)
    command.upgrade(cfg, "head")


@pytest.fixture(scope="session", autouse=True)
def prepared_db():
    """Creates + migrates + seeds the test database exactly once per session.

    Autouse: cada proceso pytest (incluidos los tests que abren
    ``AsyncSessionLocal`` directamente, como los E2E) arranca sobre una BD de
    tests recién sembrada y limpia. Sin esto, los tests quedan a merced del
    estado residual de la BD compartida (por ejemplo, chunks RAG huérfanos que
    otros tests dejaron commiteados) y el resultado depende del orden.
    """
    _ensure_database()
    _run_migrations()
    from scripts.seed import seed

    asyncio.run(seed())
    _ensure_admin_users()
    yield


def _ensure_admin_users() -> None:
    """RBAC test users: one per role, password known (test suite only)."""
    from sqlalchemy import select

    from app.database.models import AdminRole, AdminUser
    from app.security.auth import hash_password

    async def _create() -> None:
        async with AsyncSessionLocal() as s:
            for role in AdminRole:
                email = f"{role.value}@test.local"
                existing = (await s.execute(
                    select(AdminUser).where(AdminUser.email == email)
                )).scalar_one_or_none()
                if existing is None:
                    s.add(AdminUser(
                        email=email, name=f"Test {role.value}",
                        password_hash=hash_password("test-password-123"),
                        role=role,
                    ))
            await s.commit()

    asyncio.run(_create())


# ------------------------------------------------------------------- fixtures
@pytest.fixture(scope="session")
def settings():
    return get_settings()


@pytest.fixture
async def session(prepared_db):
    async with AsyncSessionLocal() as s:
        yield s
        try:
            await s.rollback()
        except Exception:  # pragma: no cover - already closed
            pass


_counter = itertools.count(1)


@pytest.fixture(scope="session")
def admin_users():
    """RBAC test users keyed by role value (created by prepared_db)."""
    from sqlalchemy import select

    from app.database.models import AdminUser

    async def _load() -> dict[str, AdminUser]:
        async with AsyncSessionLocal() as s:
            rows = (await s.execute(select(AdminUser))).scalars().all()
            return {u.role.value: u for u in rows}

    return asyncio.run(_load())


@pytest.fixture
def admin_token(admin_users):
    """Bearer auth headers for an admin role: admin_token('superadmin')."""
    from app.security.auth import create_access_token

    def _token(role: str = "superadmin") -> dict[str, str]:
        u = admin_users[role]
        claims = {"sub": str(u.id), "email": u.email, "role": u.role.value, "name": u.name}
        return {"Authorization": f"Bearer {create_access_token(claims)}"}

    return _token


@pytest.fixture
def user_id() -> int:
    """Unique Telegram id per test: committed rows can never collide."""
    return 1_000_000_000 + (int(uuid_mod.uuid4().int % 10**8) * 100) + next(_counter)


@pytest.fixture
def ask():
    """Sends a natural-language message through the agent and returns the reply."""
    from app.agents.orchestrator import Orchestrator
    from tests.test_fake_llm_v2 import FakeLLMV2, search_then_send

    async def _ask(text: str, user_id: int = 1_000_000_777, **kw):
        orch = kw.pop("orchestrator", None)
        if orch is None:
            fake = FakeLLMV2(search_then_send("Respuesta de prueba del agente."))
            orch = Orchestrator(llm=fake)
        async with AsyncSessionLocal() as s:
            return await orch.handle_user_message(s, user_id, text, "tester", "Test")

    return _ask


@pytest.fixture
def property_by_code():
    from app.properties import repository as repo

    async def _get(code: str, session):
        return await repo.get_property_by_code(session, code)

    return _get
