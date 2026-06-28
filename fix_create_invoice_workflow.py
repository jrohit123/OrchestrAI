"""
Update the create_sales_invoice workflow with proper training phrases and entity schema.
"""
import asyncio
import json
from app.db import init_db, close_db, execute


async def fix_workflow():
    await init_db()
    
    training_phrases = [
        "invoice {customer_name} {amount}",
        "bill {customer_name} {amount}",
        "create invoice for {customer_name} {amount}",
        "raise invoice {customer_name} {amount}",
        "invoice banao {customer_name} {amount}",
        "bill karo {customer_name} ke liye {amount}",
        "invoice {customer_name} {item_name} {qty} units {amount}",
        "{customer_name} ka invoice {amount}",
        "generate invoice {customer_name} {amount}"
    ]
    
    entity_schema = {
        "customer_name": {
            "required": True,
            "table": "customers",
            "column": "name",
            "match": "ILIKE",
            "format": "wildcard"
        },
        "amount": {
            "required": True,
            "type": "float"
        },
        "item_name": {
            "required": False,
            "type": "string"
        },
        "qty": {
            "required": False,
            "type": "integer"
        }
    }
    
    llm_system_prompt = """This workflow creates a sales invoice for a customer.
First find the customer by name using fuzzy matching. Then create the invoice record
with the specified amount. Generate a professional Tax Invoice PDF with GST breakdown
and send it via WhatsApp. For amounts above Rs.50,000, OTP verification is required.
For amounts above Rs.1,00,000, owner approval is required."""
    
    business_glossary = {
        "invoice": "sales invoice",
        "bill": "invoice",
        "banao": "create",
        "karo": "do/create",
        "ka": "for/of"
    }
    
    await execute("""
        UPDATE workflows
        SET training_phrases = $1::jsonb,
            entity_schema = $2::jsonb,
            llm_system_prompt = $3,
            business_glossary = $4::jsonb
        WHERE intent_key = 'create_sales_invoice'
    """, json.dumps(training_phrases), json.dumps(entity_schema), llm_system_prompt, json.dumps(business_glossary))
    
    print("Workflow updated successfully")
    await close_db()


if __name__ == "__main__":
    asyncio.run(fix_workflow())
