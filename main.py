"""Single entry point: python main.py

Composition root only — all logic stays in app/* modules.
Boot order: config → logging → infra checks (postgres/redis) → migrations →
services → bot → API → workers → scheduler → graceful shutdown.
"""
from __future__ import annotations

import asyncio
import os
import shutil
import signal
import socket
import subprocess
import sys

from app.core.logging import get_logger, setup_logging
from app.core.settings import get_settings

log = get_logger("main")


def check_port(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def try_start_postgres() -> bool:
    """Termux/native convenience: start the local cluster if configured and down."""
    s = get_settings()
    if check_port("127.0.0.1", 5432):
        return True
    pg_ctl = shutil.which("pg_ctl")
    if not pg_ctl:
        return False
    pgdata = os.path.abspath(os.path.expanduser(s.PGDATA))
    candidates = [pgdata, os.path.expanduser("~/pgdata-inmob")]
    for d in candidates:
        if os.path.isdir(d) and os.path.exists(os.path.join(d, "PG_VERSION")):
            log.info("starting local postgres from %s", d)
            subprocess.run(
                [pg_ctl, "-D", d, "-l", os.path.join(d, "pg.log"), "start"],
                capture_output=True, text=True, timeout=30,
            )
            import time

            for _ in range(20):
                if check_port("127.0.0.1", 5432):
                    return True
                time.sleep(0.5)
    return False


def try_start_redis() -> bool:
    if check_port("127.0.0.1", 6379):
        return True
    redis_server = shutil.which("redis-server")
    if not redis_server:
        return False
    log.info("starting local redis")
    subprocess.run(
        [redis_server, "--daemonize", "yes", "--port", "6379"],
        capture_output=True, text=True, timeout=10,
    )
    import time

    for _ in range(10):
        if check_port("127.0.0.1", 6379):
            return True
        time.sleep(0.3)
    return False


def run_migrations() -> None:
    from alembic import command
    from alembic.config import Config

    s = get_settings()
    root = os.path.dirname(os.path.abspath(__file__))
    cfg = Config(os.path.join(root, "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", s.DATABASE_URL)
    command.upgrade(cfg, "head")
    # Alembic reconfigura el logging raíz al cargar alembic.ini (env.py):
    # restauramos el formato y el nivel de la app para no quedarnos mudos.
    setup_logging(s.LOG_LEVEL)
    log.info("migrations_ok")


async def wait_for_postgres(timeout: float = 15.0) -> None:
    from sqlalchemy import text

    from app.database.base import make_sync_engine

    deadline = asyncio.get_event_loop().time() + timeout
    last_err = None
    while asyncio.get_event_loop().time() < deadline:
        try:
            engine = make_sync_engine()
            try:
                with engine.connect() as conn:
                    conn.execute(text("SELECT 1"))
            finally:
                engine.dispose()
            return
        except Exception as e:
            last_err = e
            await asyncio.sleep(1)
    raise RuntimeError(f"PostgreSQL no accesible: {last_err}")

async def bootstrap() -> None:
    s = get_settings()
    setup_logging(s.LOG_LEVEL)
    log.info("boot env=%s host=%s:%s", s.APP_ENV, s.APP_HOST, s.APP_PORT)

    if not try_start_postgres():
        log.warning("postgres not auto-started (docker or manual start expected)")
    if not try_start_redis():
        log.warning("redis not auto-started; queue falls back to memory (see docs)")
    await wait_for_postgres()
    log.info("postgres_ok")

    run_migrations()

    from sqlalchemy import text

    from app.database.base import make_sync_engine

    engine = make_sync_engine()
    try:
        with engine.connect() as conn:
            version = conn.execute(
                text("SELECT extversion FROM pg_extension WHERE extname='vector'")
            ).scalar()
        if not version:
            raise RuntimeError(
                "pgvector no instalado. En Termux: make+install manual (docs/local-development.md); "
                "con Docker usa la imagen pgvector/pgvector."
            )
        log.info("pgvector_ok version=%s", version)
    finally:
        engine.dispose()


async def run() -> None:
    # Arranque real: infra checks (postgres/redis) → migrations → pgvector.
    # Sin esta llamada el proceso arranca degradado y en silencio.
    await bootstrap()

    from app.agents.orchestrator import Orchestrator
    from app.ai.llm import get_llm_provider
    from app.bot import handlers

    s = get_settings()
    llm = get_llm_provider()
    if llm is None:
        log.error(
            "LLM obligatorio: no hay proveedor configurado. "
            "La arquitectura LLM-FIRST PURO requiere NVIDIA_API_KEY + NVIDIA_MODEL. "
            "Configura las credenciales en .env."
        )
        raise RuntimeError("LLM provider not configured. Set NVIDIA_API_KEY and NVIDIA_MODEL in .env")
    log.info(
        "llm_mode=%s provider=%s model=%s",
        s.LLM_MODE, llm.name, llm.model,
    )
    orchestrator = Orchestrator(llm=llm)
    handlers.register_orchestrator(orchestrator)
    from app.api import routes

    routes.set_orchestrator(orchestrator)

    stop_event = asyncio.Event()

    bot_app = None
    if s.TELEGRAM_BOT_TOKEN:
        bot_app = handlers.build_application()
        await bot_app.initialize()
        await bot_app.start()
        await bot_app.updater.start_polling(drop_pending_updates=True)
        log.info("telegram_bot_started")
    else:
        log.warning(
            "TELEGRAM_BOT_TOKEN vacío: arrancando SIN bot de Telegram "
            "(API, workers y scheduler activos). Configura el token en .env para activarlo."
        )

    import uvicorn

    server_cfg = uvicorn.Config(
        routes.app, host=s.APP_HOST, port=s.APP_PORT,
        log_level=s.LOG_LEVEL.lower(), access_log=False,
    )
    server = uvicorn.Server(server_cfg)
    api_task = asyncio.create_task(server.serve())
    log.info("api_started http://%s:%s", s.APP_HOST, s.APP_PORT)

    from app.workers.queue import enqueue
    from app.workers.runner import run_scheduler, run_worker

    worker_task = asyncio.create_task(run_worker(stop_event))
    scheduler_task = asyncio.create_task(run_scheduler(stop_event, interval_seconds=3600))
    await enqueue("document_ingestion", {})

    def _stop(*_a) -> None:
        log.info("shutdown_signal_received")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _stop)
        except NotImplementedError:  # pragma: no cover
            pass

    await stop_event.wait()

    scheduler_task.cancel()
    worker_task.cancel()
    if bot_app is not None:
        try:
            await bot_app.updater.stop()
            await bot_app.stop()
            await bot_app.shutdown()
        except Exception as e:
            log.warning("bot_shutdown_warning error=%s", e)
    log.info("telegram_bot_stopped")
    server.should_exit = True
    try:
        await asyncio.wait_for(api_task, timeout=10)
    except (TimeoutError, asyncio.CancelledError):
        pass
    for task in (worker_task, scheduler_task):
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
    from app.database.base import make_async_engine

    engine = make_async_engine()
    await engine.dispose()
    log.info("shutdown_complete")


def main() -> None:
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass
    except RuntimeError as e:
        log.error("boot_failed error=%s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()

