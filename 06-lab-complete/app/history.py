"""
Per-user conversation history.

Stored as a capped, newest-last list per user. Redis-backed (a Redis list)
so history survives instance restarts and is shared across instances; falls
back to in-memory per process when Redis is unavailable.
"""
import json
import time
import logging
import threading
from collections import defaultdict

from app.config import settings
from app.store import get_redis

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_mem: dict[str, list] = defaultdict(list)  # in-memory fallback


def add_turn(user_id: str, question: str, answer: str):
    """Append one Q→A turn, trimming to the configured max."""
    entry = json.dumps({
        "q": question,
        "a": answer,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    })
    cap = settings.max_history_turns
    r = get_redis()
    if r is not None:
        try:
            key = f"history:{user_id}"
            pipe = r.pipeline()
            pipe.rpush(key, entry)
            pipe.ltrim(key, -cap, -1)
            pipe.expire(key, 7 * 24 * 3600)
            pipe.execute()
            return
        except Exception:
            logger.warning('{"event":"history_redis_error","fallback":"in-memory"}')
    with _lock:
        lst = _mem[user_id]
        lst.append(entry)
        del lst[:-cap]


def get_history(user_id: str) -> list[dict]:
    """Return this user's stored turns, oldest first."""
    r = get_redis()
    if r is not None:
        try:
            raw = r.lrange(f"history:{user_id}", 0, -1)
            return [json.loads(x) for x in raw]
        except Exception:
            logger.warning('{"event":"history_redis_error","fallback":"in-memory"}')
    with _lock:
        return [json.loads(x) for x in _mem[user_id]]
