import asyncpg
import os
from dotenv import load_dotenv

load_dotenv()

_routing_pool = None
_pools: dict[str, "asyncpg.Pool"] = {}   # source_key -> pool, cached


async def init_db():
    """Boot-time: connect ONLY to the routing DB. Everything else resolved lazily."""
    global _routing_pool
    _routing_pool = await asyncpg.create_pool(
        dsn=os.getenv("ROUTING_DATABASE_URL") or os.getenv("BAANGANGA_DATABASE_URL") or os.getenv("DATABASE_URL"),
        min_size=1,
        max_size=5,
        init=_set_timezone,
        statement_cache_size=0
    )
    print("Routing DB connected")
    await get_pool("platform")   # pre-warm the one every request needs


async def _set_timezone(conn):
    await conn.execute("SET timezone = 'Asia/Kolkata'")


async def close_db():
    global _routing_pool, _pools
    for pool in _pools.values():
        await pool.close()
    _pools = {}
    if _routing_pool:
        await _routing_pool.close()


async def get_pool(source_key: str = "platform"):
    """Return a cached pool for this data source, resolving its DSN from the routing DB on first use."""
    if source_key in _pools:
        return _pools[source_key]

    row = await _routing_pool.fetchrow(
        "SELECT database_url FROM data_sources WHERE source_key = $1", source_key
    )
    if not row:
        raise RuntimeError(f"No data_sources row for source_key='{source_key}' in routing DB")

    pool = await asyncpg.create_pool(
        dsn=row["database_url"],
        min_size=2,
        max_size=10,
        init=_set_timezone,
        statement_cache_size=0
    )
    _pools[source_key] = pool
    return pool


async def get_pool_for_org(org_id: str, kind: str = "business"):
    """kind = 'platform' or 'business'."""
    row = await _routing_pool.fetchrow(
        "SELECT platform_source, business_source FROM org_routing WHERE org_id = $1", org_id
    )
    if not row:
        raise RuntimeError(f"No org_routing row for org_id='{org_id}'")
    source_key = row["platform_source"] if kind == "platform" else row["business_source"]
    return await get_pool(source_key)


# ── Existing call sites everywhere else (identity.py, draft_store.py, menu.py,
# agent.py, step_interpreter.py, etc.) keep working completely unchanged —
# they default to "platform", which resolves to Baanganga's Neon DB, same as today.
async def fetch_one(query: str, *args, source_key: str = "platform"):
    pool = await get_pool(source_key)
    async with pool.acquire() as conn:
        return await conn.fetchrow(query, *args)


async def fetch_all(query: str, *args, source_key: str = "platform"):
    pool = await get_pool(source_key)
    async with pool.acquire() as conn:
        return await conn.fetch(query, *args)


async def execute(query: str, *args, source_key: str = "platform"):
    pool = await get_pool(source_key)
    async with pool.acquire() as conn:
        return await conn.execute(query, *args)
