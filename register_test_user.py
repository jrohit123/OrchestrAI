import asyncio
import asyncpg
import os
from dotenv import load_dotenv

load_dotenv()

async def register_test_user():
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        print("ERROR: DATABASE_URL not set in .env")
        return
    
    print("Connecting to database...")
    conn = await asyncpg.connect(dsn)
    
    try:
        # Check if user exists
        user = await conn.fetchrow(
            "SELECT id, org_id FROM users WHERE phone = '+919372860852'"
        )
        
        if user:
            print(f"User already exists: {user['id']}, org_id: {user['org_id']}")
        else:
            # Get the org
            org = await conn.fetchrow(
                "SELECT id FROM orgs WHERE is_active = true LIMIT 1"
            )
            if not org:
                print("ERROR: No active org found")
                return
            
            # Get owner role
            role = await conn.fetchrow(
                "SELECT id FROM roles WHERE org_id = $1 AND name = 'owner'",
                org["id"]
            )
            if not role:
                print("ERROR: No owner role found")
                return
            
            # Create user
            user_id = await conn.fetchval("""
                INSERT INTO users (phone, org_id, role_id, name, is_active)
                VALUES ($1, $2, $3, 'Test User', true)
                RETURNING id
            """, "+919372860852", org["id"], role["id"])
            
            print(f"User registered: {user_id}, org_i d: {org['id']}")
            
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(register_test_user())
