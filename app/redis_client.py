import json

import redis.asyncio as aioredis
from dotenv import load_dotenv

from app.config import required
from app.logging_config import get_context_logger

load_dotenv()

logger = get_context_logger(__name__)

_redis = None


async def init_redis():
    global _redis
    # A connection that silently dies (the host's proxy drops idle ones) must never make a call wait for ever:
    # every message and every scheduled job uses Redis, so one stuck call froze the whole chat bot (2026-10-15).
    _redis = await aioredis.from_url(
        required("REDIS_URL"),
        decode_responses=True,
        socket_timeout=5,
        socket_connect_timeout=5,
        socket_keepalive=True,
        health_check_interval=20,
        retry_on_timeout=True,
    )
    logger.info("Redis connected")


async def close_redis():
    global _redis
    if _redis:
        await _redis.aclose()
        _redis = None


def get_redis():
    return _redis


async def get_session(session_id: str) -> dict:
    data = await _redis.get(f"session:{session_id}")
    return json.loads(data) if data else {}


async def set_session(session_id: str, data: dict, ttl: int = 600):
    await _redis.setex(f"session:{session_id}", ttl, json.dumps(data, default=str))


async def delete_session(session_id: str):
    await _redis.delete(f"session:{session_id}")


# ── AUTH TOKEN (session TTL security) ─────────────────
async def set_auth_token(org_id: str, phone: str, ttl_minutes: int = 480):
    """Mark user as authenticated for X minutes."""
    key = f"auth:{org_id}:{phone}"
    await _redis.setex(key, ttl_minutes * 60, "1")


async def check_auth_token(org_id: str, phone: str) -> bool:
    """Returns True if user is still within auth window."""
    key = f"auth:{org_id}:{phone}"
    val = await _redis.get(key)
    return val is not None


async def clear_all_sessions(org_id: str):
    """Emergency lockdown — delete all auth + session keys for org."""
    patterns = [f"auth:{org_id}:*", f"session:{org_id}:*"]
    for pattern in patterns:
        keys = await _redis.keys(pattern)
        if keys:
            await _redis.delete(*keys)
    logger.warning(f"All sessions cleared for org {org_id}")
