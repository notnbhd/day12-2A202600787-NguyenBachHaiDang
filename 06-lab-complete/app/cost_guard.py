"""
Per-user monthly cost guard.

Tracks each user's spend for the current calendar month and refuses new work
(HTTP 402) once they cross MONTHLY_BUDGET_USD. Redis-backed so the budget is
shared across instances; in-memory fallback per process otherwise.
"""
import time
import logging
import threading
from collections import defaultdict

from fastapi import HTTPException

from app.config import settings
from app.store import get_redis

logger = logging.getLogger(__name__)

# Mock token pricing (gpt-4o-mini-ish): USD per 1K tokens
PRICE_INPUT_PER_1K = 0.00015
PRICE_OUTPUT_PER_1K = 0.0006

_lock = threading.Lock()
_spend: dict[str, float] = defaultdict(float)  # in-memory fallback: "{user}:{month}" -> usd


def estimate_cost(input_tokens: int, output_tokens: int) -> float:
    return (input_tokens / 1000) * PRICE_INPUT_PER_1K + (output_tokens / 1000) * PRICE_OUTPUT_PER_1K


def _month() -> str:
    return time.strftime("%Y-%m")


def get_user_cost(user_id: str) -> float:
    """Current month's accumulated spend for a user."""
    r = get_redis()
    if r is not None:
        try:
            val = r.get(f"budget:{user_id}:{_month()}")
            return float(val) if val else 0.0
        except Exception:
            logger.warning('{"event":"costguard_redis_error","fallback":"in-memory"}')
    with _lock:
        return _spend[f"{user_id}:{_month()}"]


def check_budget(user_id: str, estimated: float = 0.0):
    """Raise 402 if this user's month-to-date spend (plus `estimated`) exceeds budget."""
    if get_user_cost(user_id) + estimated > settings.monthly_budget_usd:
        raise HTTPException(
            status_code=402,
            detail=f"Monthly budget exhausted: ${settings.monthly_budget_usd:.2f}/user. Resets next month.",
        )


def record_cost(user_id: str, cost: float):
    """Add `cost` to the user's month-to-date spend."""
    r = get_redis()
    if r is not None:
        try:
            key = f"budget:{user_id}:{_month()}"
            pipe = r.pipeline()
            pipe.incrbyfloat(key, cost)
            pipe.expire(key, 32 * 24 * 3600)  # auto-clear after the month rolls over
            pipe.execute()
            return
        except Exception:
            logger.warning('{"event":"costguard_redis_error","fallback":"in-memory"}')
    with _lock:
        _spend[f"{user_id}:{_month()}"] += cost
