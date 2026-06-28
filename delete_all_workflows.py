"""
Delete all workflows from the database.
This is a one-time cleanup before creating the new 5 workflows.
"""
import asyncio
from app.db import init_db, close_db, execute


async def delete_all_workflows():
    await init_db()
    
    print("Deleting all workflows from database...")
    
    result = await execute("DELETE FROM workflows")
    print(f"Deleted {result} workflows")
    
    await close_db()
    print("Done.")


if __name__ == "__main__":
    asyncio.run(delete_all_workflows())
