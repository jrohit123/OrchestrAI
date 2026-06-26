"""
Dynamic SQL Query Engine — LLM generates SQL directly.
Includes schema in prompt, validates SQL for safety, executes read-only queries.
"""
import os
import re
from openai import AsyncOpenAI
from dotenv import load_dotenv
from app.db import fetch_all

load_dotenv()
_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# DB Schema for LLM context
DB_SCHEMA = """
TABLES:
- customers: id, name, phone, email, gst_number, city, credit_limit, created_at
- invoices: id, invoice_number, customer_id, created_by, items (jsonb), amount, status (draft/pending/paid/overdue), due_date, paid_at, pdf_url, created_at
- inventory: id, sku, name, qty, location, reorder_level, unit_price, updated_at
- metal_rates: id, metal_type, rate_per_gram, making_charge_pct, updated_by, updated_at
- orders: id, order_number, quotation_id, customer_id, customer_name, description, metal_type, weight_estimate, estimated_amount, advance_paid, status (confirmed/production/shipped/delivered/cancelled), expected_delivery, notes, created_by, created_at
- quotations: id, quotation_number, customer_id, customer_name, metal_type, weight_grams, design_code, rate_per_gram, making_charge_pct, making_charges, subtotal, gst_pct, gst_amount, total_amount, status, valid_until, notes, created_by, created_at

RELATIONSHIPS:
- invoices.customer_id → customers.id
- orders.customer_id → customers.id
- quotations.customer_id → customers.id
"""

# Dangerous SQL patterns to block
DANGEROUS_PATTERNS = [
    r'\bDROP\b', r'\bDELETE\b', r'\bTRUNCATE\b', r'\bALTER\b', 
    r'\bCREATE\b', r'\bINSERT\b', r'\bUPDATE\b', r'\bGRANT\b',
    r'\bREVOKE\b', r'\bEXEC\b', r'\bEXECUTE\b', r';\s*--',
    r'\bpg_\w+', r'\binformation_schema\b', r'\bpg_catalog\b'
]


def _validate_sql(sql: str) -> tuple[bool, str]:
    """Validate SQL is safe (read-only, no dangerous operations)."""
    sql_upper = sql.upper()
    
    # Block dangerous patterns
    for pattern in DANGEROUS_PATTERNS:
        if re.search(pattern, sql_upper, re.IGNORECASE):
            return False, f"Blocked dangerous SQL pattern: {pattern}"
    
    # Ensure it's a SELECT query
    if not sql_upper.strip().startswith('SELECT'):
        return False, "Only SELECT queries allowed"
    
    # Block multiple statements
    if ';' in sql.rstrip(';'):
        return False, "Multiple statements not allowed"
    
    return True, "OK"


async def _generate_sql(intent: str, parameters: dict) -> str:
    """LLM generates SQL based on intent and schema."""
    prompt = f"""You are a SQL expert. Generate a PostgreSQL SELECT query for this request.

REQUEST: {intent}
PARAMETERS: {parameters}

DATABASE SCHEMA:
{DB_SCHEMA}

RULES:
- Generate ONLY a SELECT query (no INSERT/UPDATE/DELETE)
- Always include WHERE org_id = $1 (parameterized)
- Use parameterized queries ($1, $2, etc.) - NEVER embed values directly
- For text search use ILIKE with % wildcards
- For numeric comparisons use standard operators
- LIMIT results to 10-50 rows unless specified
- Use proper JOIN syntax for related tables
- Return ONLY the SQL query, no explanation

Example:
INPUT: "show top 3 customers by credit limit"
OUTPUT: SELECT name, city, credit_limit FROM customers WHERE org_id = $1 ORDER BY credit_limit DESC NULLS LAST LIMIT 3

INPUT: "dues for Mehta Jewellers"
OUTPUT: SELECT c.name, i.invoice_number, i.amount, i.status, i.due_date FROM invoices i JOIN customers c ON c.id = i.customer_id WHERE i.org_id = $1 AND c.org_id = $1 AND c.name ILIKE $2 AND i.status IN ('pending', 'overdue') ORDER BY i.due_date ASC

Now generate SQL for:
{intent}
"""

    response = await _client.chat.completions.create(
        model="gpt-4o-mini",
        max_tokens=500,
        temperature=0,
        messages=[{"role": "user", "content": prompt}],
    )
    
    sql = response.choices[0].message.content.strip()
    
    # Clean up markdown if present
    if sql.startswith('```'):
        sql = sql.split('```')[1]
        if sql.startswith('sql'):
            sql = sql[3:]
    sql = sql.strip()
    
    return sql


def _extract_parameters(sql: str, user_params: dict, org_id: str) -> list:
    """Extract and build parameter list for SQL."""
    # Count parameter placeholders
    param_count = sql.count('$')
    params = [org_id]  # $1 is always org_id
    
    # Fill remaining params from user_params
    for i in range(1, param_count):
        param_key = list(user_params.keys())[i-1] if i-1 < len(user_params) else None
        if param_key:
            val = user_params[param_key]
            # Add wildcards for ILIKE
            if 'ILIKE' in sql.upper() and isinstance(val, str):
                if not val.startswith('%'):
                    val = f'%{val}%'
            params.append(val)
        else:
            params.append(None)
    
    return params


def _format_results(rows: list, sql: str) -> str:
    """Format query results for WhatsApp."""
    if not rows:
        return "✅ No results found."
    
    # Try to infer format based on columns
    cols = list(rows[0].keys())
    
    # Simple table format
    header = " | ".join(cols[:4])  # Limit to 4 columns
    lines = [f"📊 *Results*\n\n{header}"]
    
    for r in rows[:10]:  # Limit to 10 rows
        vals = " | ".join(str(r[c])[:20] for c in cols[:4])
        lines.append(vals)
    
    if len(rows) > 10:
        lines.append(f"\n... and {len(rows) - 10} more")
    
    return "\n".join(lines)


async def execute_read(org_id: str, intent: str, parameters: dict) -> str:
    """Execute a general_read request with dynamic SQL generation."""
    try:
        # Generate SQL
        sql = await _generate_sql(intent, parameters)
        
        # Validate SQL
        is_safe, reason = _validate_sql(sql)
        if not is_safe:
            print(f"[QUERY_ENGINE] SQL blocked: {reason}")
            return f"⚠️ Query blocked for security: {reason}"
        
        # Build parameters
        params = _extract_parameters(sql, parameters, org_id)
        
        # Execute
        rows = await fetch_all(sql, *params)
        rows = [dict(r) for r in rows]
        
        # Format results
        return _format_results(rows, sql)
        
    except Exception as e:
        print(f"[QUERY_ENGINE] Error: {e}")
        return f"⚠️ Could not run query: {str(e)}"
