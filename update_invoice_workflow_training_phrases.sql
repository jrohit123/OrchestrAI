-- Update create_sales_invoice workflow with expanded Hinglish training phrases
-- Run this in your Railway PostgreSQL console

UPDATE workflows
SET
  training_phrases = '[
    "invoice {customer_name} {amount}",
    "bill {customer_name} {amount}",
    "create invoice {customer_name} Rs.{amount}",
    "{customer_name} ka invoice {amount}",
    "invoice banao {customer_name} {amount}",
    "raise invoice {customer_name} {amount}",
    "generate invoice for {customer_name} amount {amount}",
    "{customer_name} {amount} invoice",
    "make invoice {customer_name} for Rs.{amount}",
    "{customer_name} bill {amount} rupees",
    "new invoice {customer_name} {amount}",
    "{customer_name} {amount} ka bill banao"
  ]'::jsonb,
  llm_system_prompt = 'This workflow CREATES a new sales invoice in the database. Required entities: customer_name (string, customer lookup) and amount (float, invoice total). Optional: item_name (string), quantity (integer). The adapter function is accounting.create_invoice which handles: customer fuzzy lookup, invoice number generation (INV-1100+n), Tax Invoice PDF generation, WhatsApp delivery. OTP required for amounts above Rs.50,000. Owner approval required above Rs.1,00,000. ENTITY EXTRACTION: "Mehta Enterprises 92000 invoice" → customer_name = "Mehta Enterprises" (full name), amount = 92000. "Singh Bullion 150000" → customer_name = "Singh Bullion Mart" (expand to full match). Always confirm_action before proceeding. This is NOT for viewing existing invoices — that is a query_database read.',
  description = 'Create a new sales invoice for a customer, generate Tax Invoice PDF with GST breakdown, send via WhatsApp. OTP required above Rs.50,000. Owner approval required above Rs.1,00,000.'
WHERE org_id = '11111111-0000-0000-0000-000000000001'
  AND intent_key = 'create_sales_invoice';
