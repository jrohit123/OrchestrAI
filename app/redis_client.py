import redis.asyncio as aioredis
import os
import json
from dotenv import load_dotenv

load_dotenv()

_redis = None


async def init_redis():
    global _redis
    _redis = await aioredis.from_url(
        os.getenv("REDIS_URL"),
        decode_responses=True
    )
    print("Redis connected")


async def close_redis():
    global _redis
    if _redis:
        await _redis.close()


def get_redis():
    return _redis


async def get_session(session_id: str) -> dict:
    data = await _redis.get(f"session:{session_id}")
    return json.loads(data) if data else {}


async def set_session(session_id: str, data: dict, ttl: int = 600):
    await _redis.setex(f"session:{session_id}", ttl, json.dumps(data))


async def delete_session(session_id: str):
    await _redis.delete(f"session:{session_id}")
