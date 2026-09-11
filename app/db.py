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
#pool


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
    #Hi this is Kartik
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


async def get_pool(source_key: str) -> "asyncpg.Pool":
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


async def get_source_key_for_channel(channel: str) -> str:
    """Resolve which org's source_key owns a given messaging channel
    (e.g. 'telegram', 'whatsapp'), from the routing DB — not a hardcoded
    mapping. Raises if zero or more than one org claims the channel, since
    both are configuration states a caller needs to know about rather than
    silently guessing."""
    rows = await _routing_pool.fetch(
        "SELECT source_key FROM data_sources WHERE messaging_channel = $1", channel
    )
    if not rows:
        raise RuntimeError(f"No data_sources row configured for messaging_channel='{channel}'")
    if len(rows) > 1:
        raise RuntimeError(
            f"Multiple data_sources rows configured for messaging_channel='{channel}': "
            f"{[r['source_key'] for r in rows]} — ambiguous"
        )
    return rows[0]["source_key"]


async def fetch_one(query: str, *args, source_key: str):
    pool = await get_pool(source_key)
    async with pool.acquire() as conn:
        return await conn.fetchrow(query, *args)


async def fetch_all(query: str, *args, source_key: str):
    pool = await get_pool(source_key)
    async with pool.acquire() as conn:
        return await conn.fetch(query, *args)


async def execute(query: str, *args, source_key: str):
    pool = await get_pool(source_key)
    async with pool.acquire() as conn:
        return await conn.execute(query, *args)
