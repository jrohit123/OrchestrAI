from fastapi import FastAPI, Request, HTTPException
from contextlib import asynccontextmanager
from app.db import init_db, close_db, get_pool
from app.redis_client import init_redis, close_redis, get_redis
from app.routers.webhook import router as webhook_router
from app.routers.admin import router as admin_router
from app.routers.telegram_webhook import router as telegram_router
from app.scheduler.jobs import start_scheduler, stop_scheduler
from app.logging_config import setup_logging, bind_context, get_context_logger
from openai import AsyncOpenAI
import httpx

logger = get_context_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    await init_db()
    await init_redis()
    start_scheduler()
    yield
    stop_scheduler()
    await close_db()
    await close_redis()


app = FastAPI(title="OrchestrAI", version="1.0.0", lifespan=lifespan)


@app.middleware("http")
async def add_correlation_id(request: Request, call_next):
    """Add correlation ID to request context for logging."""
    # Try to get correlation ID from header (Meta sends this)
    correlation_id = request.headers.get("X-Request-ID") or ""
    
    # Bind context for this request
    bind_context(correlation_id_val=correlation_id)
    
    response = await call_next(request)
    response.headers["X-Request-ID"] = correlation_id
    return response

app.include_router(webhook_router)
app.include_router(admin_router)
app.include_router(telegram_router)


@app.get("/")
def root():
    logger.info("ROOT HIT - Logs are flowing")
    return {"status": "OrchestrAI running"}


@app.get("/debug/schema/{source_key}")
async def debug_schema(source_key: str):
    """Debug: show what tables are visible for a given source_key."""
    try:
        from app.db import fetch_all
        rows = await fetch_all("""
            SELECT table_name, column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = 'public'
            ORDER BY table_name, ordinal_position
        """, source_key=source_key)
        tables: dict = {}
        for r in rows:
            tables.setdefault(r["table_name"], []).append(r["column_name"])
        return {"source_key": source_key, "tables": tables}
    except Exception as e:
        return {"error": str(e)}


@app.get("/debug/clear-schema-cache")
async def clear_schema_cache():
    """Force-clear the in-memory schema cache so next request re-reads from DB."""
    from app.services.agent import invalidate_schema_cache
    invalidate_schema_cache()
    return {"cleared": True}


@app.get("/health")
async def health():
    """Health check with dependency status."""
    status = {
        "status": "ok",
        "dependencies": {}
    }
    
    # Check database
    try:
        from app.db import get_default_source_key
        source_key = await get_default_source_key()
        pool = get_pool(source_key)
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        status["dependencies"]["database"] = "ok"
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        status["dependencies"]["database"] = f"error: {str(e)}"
        status["status"] = "degraded"
    
    # Check Redis
    try:
        redis = get_redis()
        if redis:
            await redis.ping()
            status["dependencies"]["redis"] = "ok"
        else:
            status["dependencies"]["redis"] = "error: not connected"
            status["status"] = "degraded"
    except Exception as e:
        logger.error(f"Redis health check failed: {e}")
        status["dependencies"]["redis"] = f"error: {str(e)}"
        status["status"] = "degraded"
    
    # Check OpenAI API
    try:
        client = AsyncOpenAI()
        await client.models.list()
        status["dependencies"]["openai"] = "ok"
    except Exception as e:
        logger.error(f"OpenAI health check failed: {e}")
        status["dependencies"]["openai"] = f"error: {str(e)}"
        status["status"] = "degraded"
    
    # Check Cerebras API (if configured)
    try:
        cerebras_key = __import__("os").getenv("CEREBRAS_API_KEY")
        if cerebras_key:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    "https://api.cerebras.ai/v1/models",
                    headers={"Authorization": f"Bearer {cerebras_key}"},
                    timeout=5.0
                )
                if response.status_code == 200:
                    status["dependencies"]["cerebras"] = "ok"
                else:
                    status["dependencies"]["cerebras"] = f"error: status {response.status_code}"
                    status["status"] = "degraded"
        else:
            status["dependencies"]["cerebras"] = "not_configured"
    except Exception as e:
        logger.error(f"Cerebras health check failed: {e}")
        status["dependencies"]["cerebras"] = f"error: {str(e)}"
    
    # Check scheduler
    try:
        from app.scheduler.jobs import scheduler
        if scheduler and scheduler.running:
            status["dependencies"]["scheduler"] = "ok"
        else:
            status["dependencies"]["scheduler"] = "not_running"
            status["status"] = "degraded"
    except Exception as e:
        logger.error(f"Scheduler health check failed: {e}")
        status["dependencies"]["scheduler"] = f"error: {str(e)}"
        status["status"] = "degraded"
    
    return status