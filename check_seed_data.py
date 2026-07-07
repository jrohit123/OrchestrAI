import asyncio
import asyncpg
import os
from dotenv import load_dotenv

load_dotenv()

async def check_seed():
    dsn = os.getenv("DATABASE_URL")
    conn = await asyncpg.connect(dsn)
    
    try:
        # Check workflows
        workflows = await conn.fetch("""
            SELECT intent_key, name, slash_command, menu_section, is_active
            FROM workflows
            WHERE org_id = '11111111-0000-0000-0000-000000000001'
        """)
        print("Workflows:")
        for w in workflows:
            print(f"  {w['intent_key']}: slash_command={w['slash_command']}, menu_section={w['menu_section']}, active={w['is_active']}")
        
        # Check user permissions
        user = await conn.fetchrow("""
            SELECT u.id, u.name, u.phone, r.name as role, r.permissions
            FROM users u
            JOIN roles r ON r.id = u.role_id
            WHERE u.phone = '+919372860852'
        """)
        if user:
            print(f"\nUser: {user['name']} ({user['phone']})")
            print(f"Role: {user['role']}")
            print(f"Permissions: {user['permissions']}")
        
    finally:
        await conn.close()

asyncio.run(check_seed())
