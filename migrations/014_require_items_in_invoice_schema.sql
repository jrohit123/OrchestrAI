-- Migration 014: Require `items` field in create_sales_invoice entity_schema
--
-- Background (Bug 10, Round 2):
-- `items` was never listed in entity_schema, so _validate_draft never checked
-- for it. This meant confirm_action could fire on a draft with no line items,
-- causing generate_pdf to fall back to the synthetic "Jewellery — As Per Order"
-- placeholder even for brand-new invoices where the user described real items.
--
-- This migration:
--   1. Adds items as REQUIRED in create_sales_invoice.
--   2. Removes customer_id as required (it was already set to false in
--      migration 012, but this ensures it stays false even if replayed).
--
-- Safe to run multiple times (jsonb_set is idempotent on the key path).

-- Step 1: Add items as required
UPDATE workflows
SET entity_schema = jsonb_set(
    entity_schema,
    '{items}',
    '{"type": "array", "required": true}'::jsonb,
    true   -- create key if it doesn't exist
)
WHERE intent_key = 'create_sales_invoice'
  AND is_active   = true;

-- Step 2: Ensure customer_id stays NOT required (executor resolves it at runtime)
UPDATE workflows
SET entity_schema = jsonb_set(
    entity_schema,
    '{customer_id, required}',
    'false'::jsonb,
    false
)
WHERE intent_key = 'create_sales_invoice'
  AND is_active   = true
  AND entity_schema ? 'customer_id';
