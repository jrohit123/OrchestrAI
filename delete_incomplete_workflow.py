"""
Delete the incomplete create_sales_invoice workflow.
"""
import asyncio
from app.db import init_db, close_db, execute


async def delete_workflow():
    await init_db()
    
    result = await execute("DELETE FROM workflows WHERE intent_key = 'create_sales_invoice'")
    print(f"Deleted {result} workflow(s)")
    
    await close_db()
    print("Done.")


if __name__ == "__main__":
    asyncio.run(delete_workflow())
