import asyncio
from app.db import init_db, execute, get_default_source_key

async def run_migration():
    # Initialize DB connection first
    await init_db()
    source_key = await get_default_source_key()
    with open('migrations/005_draft_corruption_fix.sql', encoding='utf-8') as f:
        sql = f.read()
    result = await execute(sql, source_key=source_key)
    print(f"Migration 005 completed: {result}")

if __name__ == "__main__":
    asyncio.run(run_migration())