-- Example workflows for Baanganga Gold And Diamond
-- These demonstrate the new workflow intelligence system

-- Workflow 1: Check Outstanding Dues (Read)
INSERT INTO workflows (
    org_id, name, intent_key, description,
    workflow_type, training_phrases, entity_schema,
    sql_template, sql_params_order, response_format,
    business_glossary, llm_system_prompt,
    trigger_patterns, adapter_method,
    otp_required, otp_threshold, approval_threshold,
    is_active, steps
) VALUES (
    '11111111-0000-0000-0000-000000000001',
    'Check Outstanding Dues',
    'get_outstanding',
    'Check total outstanding dues for a specific customer from unpaid and overdue invoices.',
    'read',
    '["{customer_name} ka kitna baaki hai", "{customer_name} ka outstanding", "dues {customer_name}", "{customer_name} outstanding", "{customer_name} ka udhaar", "{customer_name} ke pending invoices", "balance {customer_name}", "{customer_name} owes how much", "{customer_name} ka payment", "kitna baaki {customer_name}", "how much does {customer_name} owe", "{customer_name} dues check"]'::jsonb,
    '{"customer_name": {"table": "customers", "column": "name", "match": "ILIKE", "required": true, "format": "wildcard"}}'::jsonb,
    'SELECT c.name, c.city, COALESCE(SUM(i.amount), 0) AS total_outstanding, COUNT(i.id) AS invoice_count, MIN(i.due_date) AS oldest_due_date FROM customers c LEFT JOIN invoices i ON i.customer_id = c.id AND i.org_id = $1 AND i.status IN (''pending'', ''overdue'') WHERE c.org_id = $1 AND c.name ILIKE $2 GROUP BY c.id, c.name, c.city',
    '["customer_name"]'::jsonb,
    'outstanding_summary',
    '{"baaki": "outstanding", "udhaar": "outstanding", "pending": "pending invoices", "overdue": "overdue invoices"}'::jsonb,
    'This workflow checks outstanding dues for a specific customer. Joins customers with invoices to sum pending/overdue amounts. Glossary: baaki=outstanding, udhaar=outstanding. Examples: "Mehta ka kitna baaki hai" → customer_name=Mehta, "dues Kapoor" → customer_name=Kapoor, "balance Sharma" → customer_name=Sharma. NOT for aggregate reports across all customers.',
    '[]'::jsonb,
    NULL,
    false,
    NULL,
    NULL,
    true,
    ARRAY[]::jsonb[]
) ON CONFLICT (org_id, intent_key) DO NOTHING;

-- Workflow 2: Check Stock (Read)
INSERT INTO workflows (
    org_id, name, intent_key, description,
    workflow_type, training_phrases, entity_schema,
    sql_template, sql_params_order, response_format,
    business_glossary, llm_system_prompt,
    trigger_patterns, adapter_method,
    otp_required, otp_threshold, approval_threshold,
    is_active, steps
) VALUES (
    '11111111-0000-0000-0000-000000000001',
    'Check Product Stock',
    'check_stock',
    'Check current stock quantity and location for a specific product.',
    'read',
    '["stock {product_name}", "{product_name} ka stock", "{product_name} available hai", "how many {product_name}", "inventory {product_name}", "{product_name} kitna hai", "{product_name} maal", "{product_name} stock check", "do we have {product_name}", "{product_name} available", "check {product_name} stock", "{product_name} kitne hain"]'::jsonb,
    '{"product_name": {"table": "inventory", "column": "name", "match": "ILIKE", "required": true, "format": "wildcard"}}'::jsonb,
    'SELECT name, qty, location, reorder_level, unit_price, CASE WHEN qty <= reorder_level THEN ''LOW'' ELSE ''OK'' END AS stock_status FROM inventory WHERE org_id = $1 AND name ILIKE $2',
    '["product_name"]'::jsonb,
    'inventory',
    '{"maal": "stock", "available": "in stock", "kitna": "how many"}'::jsonb,
    'This workflow checks stock for a specific product. Queries inventory table by name. Glossary: maal=stock, available=in stock. Examples: "stock gold ring" → product_name=gold ring, "bangle kitna hai" → product_name=bangle, "mangalsutra available" → product_name=mangalsutra. NOT for aggregate low-stock reports.',
    '[]'::jsonb,
    NULL,
    false,
    NULL,
    NULL,
    true,
    ARRAY[]::jsonb[]
) ON CONFLICT (org_id, intent_key) DO NOTHING;

-- Workflow 3: Dues Report - Aggregate (Read)
INSERT INTO workflows (
    org_id, name, intent_key, description,
    workflow_type, training_phrases, entity_schema,
    sql_template, sql_params_order, response_format,
    business_glossary, llm_system_prompt,
    trigger_patterns, adapter_method,
    otp_required, otp_threshold, approval_threshold,
    is_active, steps
) VALUES (
    '11111111-0000-0000-0000-000000000001',
    'Dues Report',
    'dues_report',
    'Aggregate outstanding dues report across all customers, ranked by amount.',
    'read',
    '["dues report", "outstanding report", "top {limit} dues", "top {limit} customers by dues", "overdue customers list", "baaki report", "sabse zyada baaki wale", "customer-wise dues", "all outstanding customers", "who owes the most", "dues summary", "udhaar report"]'::jsonb,
    '{"limit": {"required": false, "type": "integer", "default": 20}}'::jsonb,
    'SELECT c.name, c.city, SUM(i.amount) AS total_outstanding, COUNT(i.id) AS invoice_count, MIN(i.due_date) AS oldest_due_date FROM invoices i JOIN customers c ON c.id = i.customer_id WHERE i.org_id = $1 AND i.status IN (''pending'', ''overdue'') GROUP BY c.id, c.name, c.city ORDER BY total_outstanding DESC LIMIT $2',
    '["limit"]'::jsonb,
    'outstanding_summary',
    '{"baaki report": "dues report", "udhaar": "outstanding"}'::jsonb,
    'This workflow generates aggregate dues report across all customers. Joins invoices with customers, groups by customer, sums outstanding amounts, orders by highest amount. Glossary: baaki report=dues report, udhaar=outstanding. Examples: "dues report" → limit=20, "top 3 dues" → limit=3, "sabse zyada baaki wale" → limit=10. NOT for single-customer queries.',
    '[]'::jsonb,
    NULL,
    false,
    NULL,
    NULL,
    true,
    ARRAY[]::jsonb[]
) ON CONFLICT (org_id, intent_key) DO NOTHING;

-- Workflow 4: Metal Rates Lookup (Read)
INSERT INTO workflows (
    org_id, name, intent_key, description,
    workflow_type, training_phrases, entity_schema,
    sql_template, sql_params_order, response_format,
    business_glossary, llm_system_prompt,
    trigger_patterns, adapter_method,
    otp_required, otp_threshold, approval_threshold,
    is_active, steps
) VALUES (
    '11111111-0000-0000-0000-000000000001',
    'Metal Rates',
    'check_metal_rates',
    'Check current metal rates per gram and making charges.',
    'read',
    '["metal rates", "gold rate", "silver rate", "aaj ka bhav", "current gold rate", "today''s rate", "{metal_type} rate kya hai", "{metal_type} bhav", "making charge kya hai", "rate list", "sone ka bhav", "current metal prices"]'::jsonb,
    '{"metal_type": {"table": "metal_rates", "column": "metal_type", "match": "ILIKE", "required": false, "format": "wildcard", "values": ["22kt", "18kt", "24kt", "silver", "platinum", "gold"]}}'::jsonb,
    'SELECT metal_type, rate_per_gram, making_charge_pct, updated_at FROM metal_rates WHERE org_id = $1 ORDER BY metal_type',
    '[]'::jsonb,
    'metal_rates',
    '{"bhav": "rate", "sone ka bhav": "gold rate", "aaj ka": "current"}'::jsonb,
    'This workflow checks current metal rates. Queries metal_rates table, shows rate per gram and making charge. Glossary: bhav=rate, sone ka bhav=gold rate. Examples: "gold rate" → show all rates, "22kt rate kya hai" → filter by 22kt, "aaj ka bhav" → show all rates. No entity filtering in SQL - returns all rates.',
    '[]'::jsonb,
    NULL,
    false,
    NULL,
    NULL,
    true,
    ARRAY[]::jsonb[]
) ON CONFLICT (org_id, intent_key) DO NOTHING;

-- Workflow 5: Orders by Status (Read)
INSERT INTO workflows (
    org_id, name, intent_key, description,
    workflow_type, training_phrases, entity_schema,
    sql_template, sql_params_order, response_format,
    business_glossary, llm_system_prompt,
    trigger_patterns, adapter_method,
    otp_required, otp_threshold, approval_threshold,
    is_active, steps
) VALUES (
    '11111111-0000-0000-0000-000000000001',
    'Order Status View',
    'view_orders_by_status',
    'View orders filtered by production status.',
    'read',
    '["ready orders", "orders in production", "production mein kya hai", "kya ready hai", "{status} orders", "show {status} orders", "orders ready hai", "kaam ready hai", "delivered orders", "confirmed orders", "active orders", "pending orders"]'::jsonb,
    '{"status": {"required": false, "match": "exact", "default": "in_production", "values": {"ready": "ready", "delivered": "delivered", "production": "in_production", "in_production": "in_production", "quality": "quality_check", "confirmed": "confirmed", "pending": "pending", "overdue": "overdue", "paid": "paid"}}}'::jsonb,
    'SELECT order_number, customer_name, description, metal_type, status, expected_delivery FROM orders WHERE org_id = $1 AND status = $2 ORDER BY created_at DESC LIMIT 20',
    '["status"]'::jsonb,
    'orders',
    '{"production mein": "in_production", "ready hai": "ready", "kaam": "order", "deliver hoga": "delivered"}'::jsonb,
    'This workflow views orders by status. Queries orders table filtered by status. Glossary: production mein=in_production, ready hai=ready, kaam=order. Examples: "ready orders" → status=ready, "production mein kya hai" → status=in_production, "delivered orders" → status=delivered. Default shows in_production orders.',
    '[]'::jsonb,
    NULL,
    false,
    NULL,
    NULL,
    true,
    ARRAY[]::jsonb[]
) ON CONFLICT (org_id, intent_key) DO NOTHING;

-- Workflow 6: Low Stock Alert (Read)
INSERT INTO workflows (
    org_id, name, intent_key, description,
    workflow_type, training_phrases, entity_schema,
    sql_template, sql_params_order, response_format,
    business_glossary, llm_system_prompt,
    trigger_patterns, adapter_method,
    otp_required, otp_threshold, approval_threshold,
    is_active, steps
) VALUES (
    '11111111-0000-0000-0000-000000000001',
    'Low Stock Alert',
    'check_low_stock',
    'List all inventory items where quantity is at or below reorder level.',
    'read',
    '["low stock", "stock kam hai", "reorder waale items", "below reorder level", "stock alert", "kya khatam ho raha hai", "low inventory", "reorder karna hai kya", "stock warning", "kaun sa maal khatam ho raha"]'::jsonb,
    '{}'::jsonb,
    'SELECT name, qty, reorder_level, location, (reorder_level - qty) AS units_to_reorder FROM inventory WHERE org_id = $1 AND qty <= reorder_level ORDER BY (reorder_level - qty) DESC',
    '[]'::jsonb,
    'inventory',
    '{"khatam": "out of stock", "reorder": "below minimum level"}'::jsonb,
    'This workflow shows low stock items. Queries inventory where qty <= reorder_level, ordered by urgency. Glossary: khatam=out of stock, reorder=below minimum level. Examples: "low stock" → show all low stock, "stock kam hai" → show all low stock, "reorder karna hai kya" → show items needing reorder. No entity parameters needed.',
    '[]'::jsonb,
    NULL,
    false,
    NULL,
    NULL,
    true,
    ARRAY[]::jsonb[]
) ON CONFLICT (org_id, intent_key) DO NOTHING;

-- Grant permissions to owner role for all new workflows
UPDATE roles
SET permissions = array_cat(permissions, ARRAY['get_outstanding', 'check_stock', 'dues_report', 'check_metal_rates', 'view_orders_by_status', 'check_low_stock', 'check_permissions', 'generate_quotation_with_rate'])
WHERE name = 'owner' AND org_id = '11111111-0000-0000-0000-000000000001';

-- Workflow 7: Check Permissions (Read - uses session context)
INSERT INTO workflows (
    org_id, name, intent_key, description,
    workflow_type, training_phrases, entity_schema,
    sql_template, sql_params_order, response_format,
    business_glossary, llm_system_prompt,
    trigger_patterns, adapter_method,
    otp_required, otp_threshold, approval_threshold,
    is_active, steps
) VALUES (
    '11111111-0000-0000-0000-000000000001',
    'Check Permissions',
    'check_permissions',
    'View the current user''s role and permissions.',
    'read',
    '["what permissions do i have", "my permissions", "show my permissions", "what can i do", "my role permissions", "what are my rights", "permissions check", "access rights"]'::jsonb,
    '{"session_context": true}'::jsonb,
    'SELECT r.name AS role, r.permissions FROM users u JOIN roles r ON u.role_id = r.id WHERE u.id = $1',
    '[]'::jsonb,
    'roles',
    '{"rights": "permissions", "access": "permissions"}'::jsonb,
    'This workflow checks the current user''s role and permissions. Uses session context (user_id) not message-extracted parameters. Glossary: rights=permissions, access=permissions. Examples: "what permissions do i have", "my permissions", "show my permissions". No entity parameters needed - uses current user from session.',
    '[]'::jsonb,
    NULL,
    false,
    NULL,
    NULL,
    true,
    ARRAY[]::jsonb[]
) ON CONFLICT (org_id, intent_key) DO NOTHING;

-- Workflow 8: Generate Quotation with Rate Update (Action)
INSERT INTO workflows (
    org_id, name, intent_key, description,
    workflow_type, training_phrases, entity_schema,
    sql_template, sql_params_order, response_format,
    business_glossary, llm_system_prompt,
    trigger_patterns, adapter_method,
    otp_required, otp_threshold, approval_threshold,
    is_active, steps
) VALUES (
    '11111111-0000-0000-0000-000000000001',
    'Generate Quotation with Rate Update',
    'generate_quotation_with_rate',
    'Update metal rate and generate quotation PDF in one step.',
    'action',
    '["quote for {metal_type} {weight}g {rate} per g making charges {making}%", "{metal_type} {weight}g {rate} per g making {making}%", "generate quotation {metal_type} {weight}g rate {rate} making {making}%", "price quotation {metal_type} {weight} grams {rate} per gram making {making} percent", "quotation {metal_type} {weight}g at {rate}/g making {making}%"]'::jsonb,
    '{"metal_type": {"required": true, "type": "string"}, "weight": {"required": true, "type": "float"}, "rate_per_gram": {"required": true, "type": "float"}, "making_charge_pct": {"required": true, "type": "float"}}'::jsonb,
    NULL,
    '[]'::jsonb,
    'quotation',
    '{"per g": "per gram", "/g": "per gram"}'::jsonb,
    'This workflow updates metal_rates table with new rate and making charge, then generates a quotation PDF. Input format: "22kt gold ring, 15g, 6000 per g, making charges 15%". Extracts metal_type, weight, rate_per_gram, making_charge_pct. Updates metal_rates table, calculates quotation, generates PDF. Glossary: per g=per gram. Examples: "22kt gold ring 15g 6000 per g making charges 15%", "18kt 10g 5000 per g making 12%". All 4 parameters required.',
    '[]'::jsonb,
    'quotation.generate_quotation_with_rate_update',
    false,
    NULL,
    NULL,
    true,
    ARRAY[]::jsonb[]
) ON CONFLICT (org_id, intent_key) DO NOTHING;
