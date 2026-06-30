-- Update generate_price_quotation workflow entity_schema to include items
-- This ensures the LLM knows items are required and their structure

UPDATE workflows
SET entity_schema = jsonb_build_object(
    'customer_name', jsonb_build_object('type', 'string', 'required', true),
    'customer_id', jsonb_build_object('type', 'string', 'required', true),
    'items', jsonb_build_object(
        'type', 'array',
        'required', true,
        'item_schema', jsonb_build_object(
            'description', jsonb_build_object('type', 'string', 'required', true),
            'design_code', jsonb_build_object('type', 'string', 'required', false),
            'design_name', jsonb_build_object('type', 'string', 'required', false),
            'metal_type', jsonb_build_object('type', 'string', 'required', false),
            'weight', jsonb_build_object('type', 'float', 'required', false),
            'qty', jsonb_build_object('type', 'integer', 'required', true),
            'unit_price', jsonb_build_object('type', 'float', 'required', true),
            'making_charges', jsonb_build_object('type', 'float', 'required', false),
            'gst', jsonb_build_object('type', 'float', 'required', true),
            'total', jsonb_build_object('type', 'float', 'required', true)
        )
    )
)
WHERE intent_key = 'generate_price_quotation';
