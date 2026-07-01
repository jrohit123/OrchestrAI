-- Fix 5: Remove customer_id from required fields in entity_schema
-- customer_id is resolved by the executor from customer_name, not provided by LLM
-- SENSITIVE_COLS strips UUIDs from query results, making customer_id impossible to obtain

UPDATE workflows
SET entity_schema = jsonb_set(
    entity_schema,
    '{customer_id,required}',
    'false'
)
WHERE intent_key = 'create_sales_invoice'
  AND org_id = '11111111-0000-0000-0000-000000000001';

UPDATE workflows
SET entity_schema = jsonb_set(
    entity_schema,
    '{customer_id,required}',
    'false'
)
WHERE intent_key = 'generate_price_quotation'
  AND org_id = '11111111-0000-0000-0000-000000000001';
