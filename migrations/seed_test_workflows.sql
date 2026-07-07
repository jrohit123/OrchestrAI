-- ============================================================================
-- SEED: two test workflows for org Rajeswari Jewellers
-- (11111111-0000-0000-0000-000000000001)
--   1. check_stock     — read, one entity (item_name, fuzzy ILIKE)
--   2. pending_orders  — read, zero entities
-- Idempotent: safe to run twice. Rollback: rollback_test_workflows.sql
-- ============================================================================

BEGIN;

-- Guard: menu/command columns (no-op if the migration already added them)
ALTER TABLE workflows
  ADD COLUMN IF NOT EXISTS slash_command varchar(32),
  ADD COLUMN IF NOT EXISTS command_description varchar(80),
  ADD COLUMN IF NOT EXISTS menu_section varchar(30) NOT NULL DEFAULT 'other';

-- ─────────────────────────── 1. check_stock ───────────────────────────
INSERT INTO workflows (
    org_id, intent_key, name, description, workflow_type,
    training_phrases, entity_schema, sql_template, sql_params_order,
    response_format, business_glossary, llm_system_prompt,
    otp_required, otp_threshold, approval_threshold,
    steps, calc_rules, is_active,
    slash_command, command_description, menu_section
) VALUES (
    '11111111-0000-0000-0000-000000000001',
    'check_stock',
    'Stock Check',
    'Check current stock of an item by name or SKU.',
    'read',
    '[
      "What is the stock",
      "Stock",
      "How many items do we have",
      "Stock status",
      "Inventory status",
      "Check inventory",
      "Show stock",
      "All stock",
      "Stock check",
      "Kitna stock hai"
    ]'::jsonb,
    '{}'::jsonb,
    'SELECT sku, name, qty, location, reorder_level, unit_price
     FROM inventory
     WHERE org_id = $1
     ORDER BY name
     LIMIT 50',
    '[]'::jsonb,
    'inventory',
    '{
      "stock": "Quantity of an item currently available in inventory",
      "SKU": "Unique stock keeping unit code identifying an item",
      "reorder level": "Minimum quantity below which the item should be restocked",
      "low stock": "Items whose quantity is below their own reorder level"
    }'::jsonb,
    'This workflow lists all current stock from the inventory table. It shows all items with their SKU, quantity, location, and reorder level. Example inputs: "stock", "show inventory", "stock status", "kitna stock hai". Use the intent_key ''check_stock'' to trigger this workflow.',
    false, NULL, NULL,
    '[]'::jsonb, '{}'::jsonb, true,
    'stock', 'Current stock of any item by name or SKU', 'reports'
)
ON CONFLICT (org_id, intent_key) DO UPDATE SET
    is_active = true,
    slash_command = EXCLUDED.slash_command,
    menu_section = EXCLUDED.menu_section,
    command_description = EXCLUDED.command_description;

-- ────────────────────────── 2. pending_orders ─────────────────────────
INSERT INTO workflows (
    org_id, intent_key, name, description, workflow_type,
    training_phrases, entity_schema, sql_template, sql_params_order,
    response_format, business_glossary, llm_system_prompt,
    otp_required, otp_threshold, approval_threshold,
    steps, calc_rules, is_active,
    slash_command, command_description, menu_section
) VALUES (
    '11111111-0000-0000-0000-000000000001',
    'pending_orders',
    'Pending Orders',
    'List all orders that are not yet delivered or cancelled.',
    'read',
    '[
      "Show pending orders",
      "Which orders are pending",
      "Pending orders dikhao",
      "Kitne orders pending hain",
      "What orders are still open",
      "List open orders",
      "Orders not delivered yet",
      "Baaki orders kaunse hain",
      "Show me all pending customer orders",
      "Any orders due for delivery"
    ]'::jsonb,
    '{}'::jsonb,
    'SELECT order_number, customer_name, description, status,
            expected_delivery, estimated_amount, advance_paid
     FROM orders
     WHERE org_id = $1 AND status NOT IN (''delivered'', ''cancelled'')
     ORDER BY expected_delivery ASC NULLS LAST
     LIMIT 30',
    '[]'::jsonb,
    'orders',
    '{
      "pending order": "An order whose status is not delivered and not cancelled",
      "advance": "Amount the customer has already paid against the order",
      "expected delivery": "Date the order is promised to the customer"
    }'::jsonb,
    'This workflow lists pending orders from the orders table — every order whose status is not delivered or cancelled, soonest expected delivery first. It needs no input from the user. Example inputs: "show pending orders", "pending orders dikhao", "which orders are still open". Use the intent_key ''pending_orders'' to trigger this workflow.',
    false, NULL, NULL,
    '[]'::jsonb, '{}'::jsonb, true,
    'orders', 'All orders not yet delivered', 'reports'
)
ON CONFLICT (org_id, intent_key) DO UPDATE SET
    is_active = true,
    slash_command = EXCLUDED.slash_command,
    menu_section = EXCLUDED.menu_section,
    command_description = EXCLUDED.command_description;

-- ──────────────── Grant both workflows to every role in the org ───────────
UPDATE roles SET permissions = permissions || ARRAY['check_stock']
WHERE org_id = '11111111-0000-0000-0000-000000000001'
  AND NOT permissions @> ARRAY['check_stock'];

UPDATE roles SET permissions = permissions || ARRAY['pending_orders']
WHERE org_id = '11111111-0000-0000-0000-000000000001'
  AND NOT permissions @> ARRAY['pending_orders'];

COMMIT;

-- Sanity check:
-- SELECT intent_key, name, slash_command, menu_section FROM workflows
--   WHERE org_id='11111111-0000-0000-0000-000000000001' AND is_active;
-- SELECT name, permissions FROM roles
--   WHERE org_id='11111111-0000-0000-0000-000000000001';
