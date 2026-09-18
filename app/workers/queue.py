"""Local Redis-backed job queue with in-memory fallback; non-blocking by design."""
from __future__ import annotations

import asyncio
import json
import time

from app.core.logging import get_logger
from app.core.settings import get_settings

log = get_logger(__name__)

QUEUE_KEY = "inmobiliaria:jobs"

try:
    import redis.asyncio as aioredis
except Exception:  # pragma: no cover
    aioredis = None

_redis = None
_memory_queue: asyncio.Queue | None = None


def _get_redis():
    global _redis
    if _redis is not None:
        return _redis
    if aioredis is None:
        return None
    try:
        _redis = aioredis.from_url(get_settings().REDIS_URL, decode_responses=True)
        return _redis
    except Exception:
        return None


async def enqueue(job: str, payload: dict | None = None) -> None:
    """Push a job. Uses Redis when available; otherwise an in-process queue."""
    item = json.dumps({"job": job, "payload": payload or {}, "ts": time.time()})
    client = _get_redis()
    if client is not None:
        try:
            await client.lpush(QUEUE_KEY, item)
            return
        except Exception as e:
            log.warning("redis_enqueue_failed_fallback_memory error=%s", e)
    global _memory_queue
    if _memory_queue is None:
        _memory_queue = asyncio.Queue()
    await _memory_queue.put(item)


async def dequeue(timeout: float = 2.0) -> dict | None:
    client = _get_redis()
    if client is not None:
        try:
            item = await client.brpop(QUEUE_KEY, timeout=int(timeout))
            if item:
                return json.loads(item[1])
            return None
        except Exception as e:
            log.warning("redis_dequeue_failed_fallback_memory error=%s", e)
    global _memory_queue
    if _memory_queue is None:
        _memory_queue = asyncio.Queue()
    try:
        item = await asyncio.wait_for(_memory_queue.get(), timeout=timeout)
        return json.loads(item)
    except asyncio.TimeoutError:
        return None


async def redis_healthy() -> bool:
    client = _get_redis()
    if client is None:
        return False
    try:
        return bool(await client.ping())
    except Exception:
        return False
