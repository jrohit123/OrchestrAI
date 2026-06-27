-- Delete all read workflows since they're now handled by the agent (tool-calling)
-- Keep only action workflows like generate_quotation_with_rate
DELETE FROM workflows
WHERE workflow_type = 'read'
  AND org_id = '11111111-0000-0000-0000-000000000001';

-- This removes: get_outstanding, check_stock, dues_report, check_metal_rates,
-- view_orders_by_status, check_low_stock, check_permissions
