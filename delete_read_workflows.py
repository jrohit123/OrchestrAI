"""
Delete read-type workflows from database.
These are now handled by the tool-calling agent.
"""
import asyncio
from app.db import init_db, close_db, execute


async def delete_read_workflows():
    await init_db()
    
    print("Deleting read workflows from database...")
    
    result = await execute(
        "DELETE FROM workflows WHERE workflow_type = 'read'"
    )
    
    print(f"Deleted {result} read workflows")
    
    await close_db()
    print("Done!")


if __name__ == "__main__":
    asyncio.run(delete_read_workflows())
