-- Migration: Add quotation workflow to workflows table
-- Fixed JSON syntax for steps array and other fields

INSERT INTO workflows (
    org_id, name, intent_key, description,
    workflow_type, training_phrases, entity_schema,
    sql_template, sql_params_order, response_format,
    business_glossary, llm_system_prompt,
    trigger_patterns, adapter_method,
    otp_required, otp_threshold, approval_threshold,
    is_active, steps,
    pdf_config, response_template
)
VALUES (
    '11111111-0000-0000-0000-000000000001',
    'Generate Price Quotation',
    'generate_price_quotation',
    'Generate a professional price quotation PDF for a customer given design code (SKU), weight in grams, and metal type. Looks up design from inventory, fetches live rate from pricing table, calculates making charges + GST, and sends quotation PDF via WhatsApp.',
    'action',
    '["quote {customer_name} {design_code} {weight}g", "quotation {customer_name} SKU {design_code} {weight} gram", "{customer_name} ka quote banao {design_code} {weight}g", "price quote {customer_name} design {design_code} weight {weight}g", "make quotation for {customer_name} {metal_type} {weight}g", "{customer_name} ke liye quote {design_code}", "generate quote {customer_name} {design_code}", "quote karo {customer_name} {metal_type} {weight} gram", "{customer_name} {design_code} quotation bhejo", "send quote {customer_name} SKU {design_code} {weight}g {metal_type}", "price banao {customer_name} {design_code} {weight}g", "estimate {customer_name} {metal_type} {weight}g"]'::jsonb,
    '{"customer_name": {"type": "string", "match": "ILIKE", "table": "customers", "column": "name", "format": "wildcard", "required": true}, "design_code": {"type": "string", "match": "exact", "table": "inventory", "column": "sku", "format": "exact", "required": true}, "weight_grams": {"type": "float", "match": "exact", "table": null, "column": null, "format": "exact", "required": true}, "metal_type": {"type": "string", "match": "exact", "table": "pricing", "column": "metal_type", "format": "exact", "required": true}}'::jsonb,
    null,
    '[]'::jsonb,
    'generic',
    '{"quote": "price quotation", "quotation": "formal price quote document", "SKU": "design code from inventory", "design code": "inventory SKU identifier", "bhav": "rate per gram", "weight": "weight in grams", "making": "making charge percentage", "estimate": "price quotation"}'::jsonb,
    'This workflow generates a Price Quotation PDF for a customer. It requires 4 inputs: customer_name (lookup in customers table), design_code/SKU (lookup in inventory table by sku column), weight_grams (numeric, in grams), and metal_type (22kt / 18kt / 14kt / silver / platinum). If ANY of these 4 inputs is missing, call the clarify tool immediately - never proceed with missing inputs. Steps: (1) Query inventory for design name: SELECT sku, name FROM inventory WHERE org_id=$1 AND sku=$2. (2) Query pricing for metal rate: SELECT rate_per_gram, making_charge_pct FROM pricing WHERE org_id=$1 AND metal_type=$2 AND quotation_number IS NULL. (3) Query orgs for GST rate: SELECT gst_rate FROM orgs WHERE id=$1. (4) Calculate: metal_cost = weight_grams * rate_per_gram, making = metal_cost * making_charge_pct/100, subtotal = metal_cost + making, gst = subtotal * gst_rate/100, total = subtotal + gst. (5) IMMEDIATELY call generate_pdf with doc_type=quotation, rows=[], title="Price Quotation - {customer_name}", subtitle="{metal_type} {weight_grams}g - {design_code}", and extra_context containing all calculated values. Do NOT call confirm_action - generate PDF directly. Do NOT query again - use the values you already calculated. DISAMBIGUATION: if customer_name search returns 2+ matches, call clarify. This workflow is NOT for viewing existing quotations - that is a query.',
    '[]'::jsonb,
    'quotation.create_quotation',
    false, null, null,
    true,
    ARRAY[
        '"Extract customer, design code, weight, metal type from message"'::jsonb,
        '"Look up inventory by SKU for design name"'::jsonb,
        '"Look up pricing table for metal rate and making %"'::jsonb,
        '"Calculate metal cost, making charges, GST, total"'::jsonb,
        '"Confirm action with full breakdown"'::jsonb,
        '"Generate Price Quotation PDF and send via WhatsApp"'::jsonb
    ],
    '{"doc_type": "quotation", "title_template": "Price Quotation - {customer_name}", "aging_analysis": false, "show_key_insights": false, "insight_focus": "Show design details, pricing breakdown, and validity period"}'::jsonb,
    'Price Quotation Generated

Quote #: {{quotation_number}}
Customer: {{customer_name}}
Design: {{design_name}} ({{design_code}})
Metal: {{metal_type}} @ Rs.{{rate_per_gram}}/g
Weight: {{weight_grams}}g

Pricing Breakdown
Metal Cost: Rs.{{metal_cost}}
Making ({{making_charge_pct}}%): Rs.{{making_charges}}
Subtotal: Rs.{{subtotal}}
GST ({{gst_pct}}%): Rs.{{gst_amount}}
TOTAL: Rs.{{total_amount}}

Valid for 3 days. Quotation PDF sent above'
);

