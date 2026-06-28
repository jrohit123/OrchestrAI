import asyncio
import sys
sys.path.insert(0, 'd:\\Orchestrator AI')

from app.db import init_db, execute, close_db

async def delete_existing_data():
    await init_db()
    org_id = '11111111-0000-0000-0000-000000000001'
    
    print("Deleting existing data...")
    
    # Delete invoices
    result = await execute("DELETE FROM invoices WHERE org_id = $1", org_id)
    print(f"Deleted invoices: {result}")
    
    # Delete orders
    result = await execute("DELETE FROM orders WHERE org_id = $1", org_id)
    print(f"Deleted orders: {result}")
    
    # Delete customers
    result = await execute("DELETE FROM customers WHERE org_id = $1", org_id)
    print(f"Deleted customers: {result}")
    
    print("Data deletion complete!")
    await close_db()

if __name__ == "__main__":
    asyncio.run(delete_existing_data())
