-- ============================================================================
-- ROLLBACK: Remove test workflows for org Rajeswari Jewellers
-- (11111111-0000-0000-0000-000000000001)
-- Removes workflows and their permissions from roles
-- ============================================================================

BEGIN;

-- Remove permissions from all roles for these workflows
UPDATE roles SET permissions = array_remove(permissions, 'check_stock')
WHERE org_id = '11111111-0000-0000-0000-000000000001';

UPDATE roles SET permissions = array_remove(permissions, 'pending_orders')
WHERE org_id = '11111111-0000-0000-0000-000000000001';

-- Delete the workflows
DELETE FROM workflows
WHERE org_id = '11111111-0000-0000-0000-000000000001'
  AND intent_key IN ('check_stock', 'pending_orders');

COMMIT;

-- Verification query:
-- SELECT intent_key, name FROM workflows
--   WHERE org_id='11111111-0000-0000-0000-000000000001';
-- SELECT name, permissions FROM roles
--   WHERE org_id='11111111-0000-0000-0000-000000000001';
