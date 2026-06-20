from fastapi import FastAPI
from contextlib import asynccontextmanager
from app.db import init_db, close_db
from app.redis_client import init_redis, close_redis
from app.routers.webhook import router as webhook_router
from app.routers.admin import router as admin_router
from app.scheduler.jobs import start_scheduler, stop_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await init_redis()
    start_scheduler()
    yield
    stop_scheduler()
    await close_db()
    await close_redis()


app = FastAPI(title="OrchestrAI", version="1.0.0", lifespan=lifespan)

app.include_router(webhook_router)
app.include_router(admin_router)


@app.get("/")
def root():
    return {"status": "OrchestrAI running"}


@app.get("/health")
def health():
    return {"status": "ok", "scheduler": "running"}
