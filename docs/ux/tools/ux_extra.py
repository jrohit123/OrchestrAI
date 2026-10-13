"""Adds a few awkward made-up records to ux_housing: a very long name, a flow with a very long name, and a 35-step flow."""
import asyncio, json
import asyncpg
async def main():
    c = await asyncpg.connect("postgresql://postgres@127.0.0.1:55432/ux_housing")
    org = await c.fetchval("SELECT id FROM orgs LIMIT 1")
    role = await c.fetchval("SELECT id FROM roles WHERE name='Tenant' AND org_id=$1", org)
    await c.execute("INSERT INTO users (org_id, role_id, name, phone, email, channel) VALUES ($1,$2,$3,NULL,'long.name@example.test','telegram')", org, role, "Venkateswaranathan Subramaniam Ramachandran Iyer-Krishnamurthy of Wing C")
    steps = [{"op": "derive_field", "params": {"field": f"value_{i}", "expr": "$fields.title"}} for i in range(35)]
    await c.execute("""INSERT INTO workflows (org_id, intent_key, name, description, workflow_type, steps, entity_schema, gates, training_phrases, version, is_active, menu_section, kind)
                       VALUES ($1,'long_flow','A flow whose name goes on and on and on so we can see how cards and tables cope with it', 'Thirty-five small steps to see how the editor copes.', 'action', $2::jsonb, '{"title":{"type":"string","label":"Title","required":true}}'::jsonb, '[]'::jsonb, '[]'::jsonb, 1, false, 'other', 'workflow')""", org, json.dumps(steps))
    print("ok")
asyncio.run(main())
