import asyncpg
import os
from dotenv import load_dotenv

load_dotenv()

_pool = None


async def init_db():
    global _pool
    _pool = await asyncpg.create_pool(
        dsn=os.getenv("DATABASE_URL"),
        min_size=2,
        max_size=10,
        init=_set_timezone
    )
    print("DB connected")


async def _set_timezone(conn):
    await conn.execute("SET timezone = 'Asia/Kolkata'")


async def close_db():
    global _pool
    if _pool:
        await _pool.close()


def get_pool():
    return _pool


async def fetch_one(query: str, *args):
    async with _pool.acquire() as conn:
        return await conn.fetchrow(query, *args)


async def fetch_all(query: str, *args):
    async with _pool.acquire() as conn:
        return await conn.fetch(query, *args)


async def execute(query: str, *args):
    async with _pool.acquire() as conn:
        return await conn.execute(query, *args)
