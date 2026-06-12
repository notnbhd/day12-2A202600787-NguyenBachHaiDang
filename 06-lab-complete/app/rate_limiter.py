"""
Per-user sliding-window rate limiter.

Redis-backed (sorted set of request timestamps) so the limit is enforced
across all instances; falls back to an in-memory window per process when
Redis is unavailable.
"""
import time
import logging
import threading
from uuid import uuid4
from collections import defaultdict, deque

from fastapi import HTTPException

from app.config import settings
from app.store import get_redis

logger = logging.getLogger(__name__)

_WINDOW = 60  # seconds

# In-memory fallback state
_lock = threading.Lock()
_windows: dict[str, deque] = defaultdict(deque)


def _reject():
    raise HTTPException(
        status_code=429,
        detail=f"Rate limit exceeded: {settings.rate_limit_per_minute} req/min",
        headers={"Retry-After": "60"},
    )


def _check_redis(r, user_id: str, limit: int):
    key = f"ratelimit:{user_id}"
    now = time.time()
    cutoff = now - _WINDOW

    pipe = r.pipeline()
    pipe.zremrangebyscore(key, 0, cutoff)
    pipe.zcard(key)
    _, count = pipe.execute()

    if count >= limit:
        _reject()

    pipe = r.pipeline()
    pipe.zadd(key, {f"{now}:{uuid4().hex}": now})
    pipe.expire(key, _WINDOW)
    pipe.execute()


def _check_memory(user_id: str, limit: int):
    now = time.time()
    with _lock:
        window = _windows[user_id]
        while window and window[0] < now - _WINDOW:
            window.popleft()
        if len(window) >= limit:
            _reject()
        window.append(now)


def check_rate_limit(user_id: str):
    """Raise 429 if `user_id` exceeds the configured per-minute limit."""
    limit = settings.rate_limit_per_minute
    r = get_redis()
    if r is not None:
        try:
            _check_redis(r, user_id, limit)
            return
        except HTTPException:
            raise
        except Exception:
            logger.warning('{"event":"ratelimit_redis_error","fallback":"in-memory"}')
    _check_memory(user_id, limit)
