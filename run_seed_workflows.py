import asyncio
import asyncpg
import os
from dotenv import load_dotenv

load_dotenv()

async def run_seed():
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        print("ERROR: DATABASE_URL not set in .env")
        return
    
    print("Connecting to database...")
    conn = await asyncpg.connect(dsn)
    
    try:
        with open("migrations/seed_test_workflows.sql", "r") as f:
            sql = f.read()
        
        print("Running seed data...")
        await conn.execute(sql)
        print("Seed data completed successfully!")
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(run_seed())
