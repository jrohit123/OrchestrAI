-- Update create_sales_invoice workflow llm_system_prompt to match items-based schema
-- This ensures LLM knows to use items[] array instead of amount field

UPDATE workflows
SET llm_system_prompt = 'This workflow CREATES a new sales invoice.
Required: customer_name (resolve to customer_id), items[] array.
Each item: description, qty, unit_price, gst, total.
Optional top-level amount is derived from sum of item totals.
Multi-turn: use update_draft to accumulate fields across messages.
When complete: confirm_action once. Do not ask for confirmation in plain text.
NEVER invent customer names or item data from examples or schema samples.'
WHERE intent_key = 'create_sales_invoice';
