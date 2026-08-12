import os
import asyncpg
import traceback
from app.config import required
from app.logging_config import get_context_logger
from dotenv import load_dotenv

load_dotenv()

logger = get_context_logger(__name__)

_routing_pool = None
_pools: dict[str, "asyncpg.Pool"] = {}   # source_key -> pool, cached


async def init_db():
    """Boot-time: connect ONLY to the routing DB. Everything else resolved lazily."""
    global _routing_pool
    _routing_pool = await asyncpg.create_pool(
        dsn=required("ROUTING_DATABASE_URL"),
        min_size=1,
        max_size=5,
        init=_set_timezone,
        statement_cache_size=0
    )
    logger.info("Routing DB connected")
    # Pre-warm all known data sources
    rows = await _routing_pool.fetch("SELECT source_key FROM data_sources")
    for row in rows:
        try:
            await get_pool(row["source_key"])
        except Exception as e:
            logger.warning(f"Could not pre-warm '{row['source_key']}': {e}")


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


async def get_all_source_keys() -> list[str]:
    rows = await _routing_pool.fetch("SELECT source_key FROM data_sources")
    return [r["source_key"] for r in rows]


async def get_default_source_key() -> str:
    """For single-tenant callers (e.g. the admin panel) that don't know
    their source_key. Returns the first configured data source."""
    keys = await get_all_source_keys()
    if not keys:
        raise RuntimeError("No data_sources rows found in routing DB")
    return keys[0]


# ── Existing call sites everywhere else (identity.py, draft_store.py, menu.py,
# agent.py, step_interpreter.py, etc.) keep working completely unchanged —
# they default to "platform", which resolves to Baanganga's Neon DB, same as today.
async def fetch_one(query: str, *args, source_key: str):
    # AP-07: Warn when source_key is not explicitly passed (defaults to 'platform')
    if source_key == "platform":
        caller = traceback.extract_stack()[-2]
        logger.warning(f"fetch_one using default source_key='platform' at {caller.filename}:{caller.lineno}")
    pool = await get_pool(source_key)
    async with pool.acquire() as conn:
        return await conn.fetchrow(query, *args)


async def fetch_all(query: str, *args, source_key: str):
    # AP-07: Warn when source_key is not explicitly passed (defaults to 'platform')
    if source_key == "platform":
        caller = traceback.extract_stack()[-2]
        logger.warning(f"fetch_all using default source_key='platform' at {caller.filename}:{caller.lineno}")
    pool = await get_pool(source_key)
    async with pool.acquire() as conn:
        return await conn.fetch(query, *args)


async def execute(query: str, *args, source_key: str):
    # AP-07: Warn when source_key is not explicitly passed (defaults to 'platform')
    if source_key == "platform":
        caller = traceback.extract_stack()[-2]
        logger.warning(f"execute using default source_key='platform' at {caller.filename}:{caller.lineno}")
    pool = await get_pool(source_key)
    async with pool.acquire() as conn:
        return await conn.execute(query, *args)
