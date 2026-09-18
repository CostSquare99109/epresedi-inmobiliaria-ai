"""Per-user token bucket rate limiting (Redis when available, memory fallback)."""
from __future__ import annotations

import time

from app.core.settings import get_settings

try:
    import redis.asyncio as aioredis
except Exception:  # pragma: no cover
    aioredis = None

_redis = None
_memory_buckets: dict[str, tuple[float, int]] = {}


def _get_redis():
    global _redis
    if _redis is not None:
        return _redis
    if aioredis is None:
        return None
    try:
        _redis = aioredis.from_url(get_settings().REDIS_URL, decode_responses=True)
    except Exception:
        _redis = None
    return _redis


class RateLimited(Exception):
    pass


async def check_rate_limit(key: str, limit: int | None = None) -> None:
    """Raises RateLimited when the user exceeds the per-minute budget."""
    s = get_settings()
    limit = limit or s.RATE_LIMIT_PER_MINUTE
    window = 60.0
    client = _get_redis()
    if client is not None:
        try:
            bucket = f"rl:{key}:{int(time.time() // window)}"
            n = await client.incr(bucket)
            if n == 1:
                await client.expire(bucket, int(window) + 5)
            if n > limit:
                raise RateLimited()
            return
        except RateLimited:
            raise
        except Exception:
            pass  # redis down → memory fallback
    now = time.monotonic()
    hit, count = _memory_buckets.get(key, (0.0, 0))
    if now - hit >= window:
        _memory_buckets[key] = (now, 1)
        return
    if count >= limit:
        raise RateLimited()
    _memory_buckets[key] = (hit, count + 1)
