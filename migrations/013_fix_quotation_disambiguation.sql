-- Fix B9: Add full-name disambiguation override to quotation workflow
-- Prevents clarify from firing when user provides exact full customer name match

UPDATE workflows
SET llm_system_prompt = 
    llm_system_prompt || 
    E'\n\nIMPORTANT: If the full customer_name provided by the user ILIKE-matches exactly one row in the customers table, proceed with that customer. Do NOT call clarify for disambiguation when there is an exact full-name match. Only clarify when customer_name search returns 2+ matches and the user did not provide a specific full name.'
WHERE intent_key = 'generate_price_quotation'
  AND org_id = '11111111-0000-0000-0000-000000000001';
