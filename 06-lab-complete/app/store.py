"""
Shared state backend.

Stateless design (Part 6): when REDIS_URL is set, all per-user state
(rate-limit windows, monthly spend, conversation history) lives in Redis so
any instance can serve any request. When Redis is unavailable (e.g. a single
Render instance with no add-on), every consumer falls back to per-process
memory and the app keeps working — just not horizontally scalable.
"""
import logging

from app.config import settings

logger = logging.getLogger(__name__)

_redis = None
if settings.redis_url:
    try:
        import redis

        _redis = redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        _redis.ping()
        logger.info('{"event":"redis_connected"}')
    except Exception:  # any failure → in-memory fallback
        logger.warning('{"event":"redis_unavailable","fallback":"in-memory"}')
        _redis = None


def get_redis():
    """Return the Redis client, or None when callers should use their fallback."""
    return _redis


def redis_healthy() -> bool:
    """Active liveness check for the /ready probe."""
    if _redis is None:
        return False
    try:
        return bool(_redis.ping())
    except Exception:
        return False


def backend_name() -> str:
    return "redis" if _redis is not None else "in-memory"
