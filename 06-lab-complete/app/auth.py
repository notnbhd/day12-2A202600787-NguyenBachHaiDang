"""API Key authentication."""
import hashlib

from fastapi import HTTPException, Security, Depends
from fastapi.security.api_key import APIKeyHeader

from app.config import settings

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def verify_api_key(api_key: str = Security(api_key_header)) -> str:
    if not api_key or api_key != settings.agent_api_key:
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key. Include header: X-API-Key: <key>",
        )
    return api_key


def user_id_from_key(api_key: str) -> str:
    """Stable, non-reversible user id derived from the API key (never stores the raw key)."""
    return hashlib.sha256(api_key.encode()).hexdigest()[:16]


def current_user(api_key: str = Depends(verify_api_key)) -> str:
    """FastAPI dependency: authenticated user's id."""
    return user_id_from_key(api_key)
