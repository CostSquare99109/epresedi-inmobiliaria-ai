"""Environment doctor: python -m scripts.doctor — check table with fixes."""
from __future__ import annotations

import asyncio
import sys

from app.core.settings import get_settings

CHECKS: list[tuple[str, str]] = []


def _ok(name: str, detail: str = "") -> None:
    CHECKS.append((name, f"OK    {detail}"))


def _err(name: str, problem: str, fix: str) -> None:
    CHECKS.append((name, f"ERROR {problem}\n        FIX: {fix}"))


def check_python() -> None:
    v = sys.version_info
    if v >= (3, 11):
        _ok("Python", f"{v.major}.{v.minor}.{v.micro}")
    else:
        _err("Python", f"versión {v.major}.{v.minor} < 3.11", "instala Python 3.11+")


def _sync_scalar(query: str):
    from sqlalchemy import text

    from app.database.base import make_sync_engine

    engine = make_sync_engine()
    try:
        with engine.connect() as conn:
            return conn.execute(text(query)).scalar()
    finally:
        engine.dispose()


def check_postgres() -> bool:
    try:
        _sync_scalar("SELECT 1")
        _ok("PostgreSQL")
        return True
    except Exception as e:
        _err("PostgreSQL", str(e)[:120],
             "pg_ctl -D ~/pgdata-inmob start · revisa DATABASE_URL en .env")
        return False


def check_pgvector() -> bool:
    try:
        version = _sync_scalar("SELECT extversion FROM pg_extension WHERE extname='vector'")
        if version:
            _ok("pgvector", version)
            return True
        _err("pgvector", "extensión no instalada",
             "CREATE EXTENSION vector; (compila pgvector; ver docs/local-development.md)")
        return False
    except Exception as e:
        _err("pgvector", str(e)[:120], "verifica PostgreSQL primero")
        return False


def check_schema() -> bool:
    try:
        n = _sync_scalar("SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")
        if (n or 0) >= 14:
            _ok("Database Schema", f"{n} tablas")
            return True
        _err("Database Schema", f"solo {n} tablas",
             "python -c \"from alembic.config import Config; from alembic import command; "
             "command.upgrade(Config('alembic.ini'), 'head')\"")
        return False
    except Exception as e:
        _err("Database Schema", str(e)[:120], "ejecuta migraciones con alembic")
        return False


async def check_redis() -> None:
    try:
        from app.workers.queue import redis_healthy

        if await redis_healthy():
            _ok("Redis")
        else:
            _err("Redis", "no responde PING",
                 "redis-server --daemonize yes --port 6379 "
                 "· (sin Redis la app usa cola en memoria: funcional pero no recomendado)")
    except Exception as e:
        _err("Redis", str(e)[:120], "instala/arranca Redis")


async def check_nvidia() -> None:
    s = get_settings()
    if not s.nvidia_configured:
        _err("NVIDIA API", "NVIDIA_API_KEY o NVIDIA_MODEL vacíos",
             "crea una API key en https://build.nvidia.com, ponla en .env junto a NVIDIA_MODEL "
             "(ej: meta/llama-3.3-70b-instruct). Sin key el bot funciona en modo determinista.")
        return
    try:
        from app.ai.llm import NVIDIAProvider

        await NVIDIAProvider().chat([{"role": "user", "content": "ping"}], max_tokens=5)
        _ok("NVIDIA API", s.NVIDIA_MODEL)
    except Exception as e:
        kind = getattr(e, "kind", "unknown")
        _err("NVIDIA API", f"[{kind}] {e}"[:160],
             "revisa NVIDIA_API_KEY/NVIDIA_BASE_URL y conectividad; si es 429 espera y reintenta")


def check_telegram() -> None:
    s = get_settings()
    if s.TELEGRAM_BOT_TOKEN:
        _ok("Telegram Config")
    else:
        _err("Telegram Config", "TELEGRAM_BOT_TOKEN vacío",
             "crea un bot con @BotFather y pon el token en .env")


async def check_storage() -> None:
    s = get_settings()
    try:
        probe = s.storage_dir / ".probe"
        probe.write_text("ok")
        probe.unlink()
        _ok("Storage", s.STORAGE_PATH)
    except Exception as e:
        _err("Storage", str(e)[:120], f"verifica permisos de {s.STORAGE_PATH}")

async def check_rag() -> bool:
    try:
        from sqlalchemy import func, select

        from app.database.base import AsyncSessionLocal
        from app.database.models import Document, DocumentChunk

        async with AsyncSessionLocal() as session:
            ndocs = (await session.execute(select(func.count()).select_from(Document))).scalar()
            nchunks = (await session.execute(select(func.count()).select_from(DocumentChunk))).scalar()
        if ndocs and nchunks:
            _ok("RAG", f"{ndocs} documentos, {nchunks} chunks")
            return True
        _err("RAG", "sin documentos procesados", "python -m scripts.seed  (o)  python -m scripts.ingest")
        return False
    except Exception as e:
        _err("RAG", str(e)[:120], "revisa la base de datos y ejecuta python -m scripts.ingest")
        return False


async def run() -> int:
    check_python()
    if check_postgres():
        check_pgvector()
        check_schema()
        await check_rag()
    await check_redis()
    await check_nvidia()
    check_telegram()
    await check_storage()

    errors = [c for c in CHECKS if c[1].startswith("ERROR")]
    print("\n== DOCTOR ==")
    for name, line in CHECKS:
        print(f"{name:20s} {line}")
    print(f"\n{len(CHECKS) - len(errors)} OK · {len(errors)} ERROR")
    return 1 if errors else 0


def main() -> None:
    sys.exit(asyncio.run(run()))


if __name__ == "__main__":
    main()

