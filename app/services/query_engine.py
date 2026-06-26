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

# Cached schema (loaded dynamically from DB)
DB_SCHEMA = None
VALID_COLUMNS = None


async def _load_schema_from_db():
    """Fetch schema dynamically from PostgreSQL information_schema."""
    global DB_SCHEMA, VALID_COLUMNS
    
    # Fetch columns
    columns = await fetch_all("""
        SELECT table_name, column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = 'public'
        ORDER BY table_name, ordinal_position
    """)
    
    # Fetch foreign key relationships
    fks = await fetch_all("""
        SELECT
            tc.table_name,
            kcu.column_name,
            ccu.table_name AS foreign_table_name,
            ccu.column_name AS foreign_column_name
        FROM information_schema.table_constraints AS tc
        JOIN information_schema.key_column_usage AS kcu
            ON tc.constraint_name = kcu.constraint_name
        JOIN information_schema.constraint_column_usage AS ccu
            ON ccu.constraint_name = tc.constraint_name
        WHERE tc.constraint_type = 'FOREIGN KEY'
    """)
    
    # Build VALID_COLUMNS dict
    VALID_COLUMNS = {}
    table_columns = {}
    
    for col in columns:
        table = col['table_name']
        column = col['column_name']
        data_type = col['data_type']
        
        if table not in VALID_COLUMNS:
            VALID_COLUMNS[table] = set()
            table_columns[table] = []
        
        VALID_COLUMNS[table].add(column)
        table_columns[table].append(f"{column} ({data_type})")
    
    # Build DB_SCHEMA string
    tables_section = "TABLES:\n"
    for table, cols in sorted(table_columns.items()):
        cols_str = ", ".join(cols)
        tables_section += f"- {table}: {cols_str}\n"
    
    # Build relationships section
    relationships_section = "RELATIONSHIPS:\n"
    for fk in fks:
        relationships_section += f"- {fk['table_name']}.{fk['column_name']} → {fk['foreign_table_name']}.{fk['foreign_column_name']}\n"
    
    # Add special note for inventory (no customer relationship)
    if 'inventory' in VALID_COLUMNS:
        relationships_section += "- inventory has NO customer relationship (it's independent stock data)\n"
    
    DB_SCHEMA = tables_section + "\n" + relationships_section
    
    print(f"[QUERY_ENGINE] Schema loaded: {len(VALID_COLUMNS)} tables")
    return DB_SCHEMA

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


def _validate_schema(sql: str) -> tuple[bool, str]:
    """Validate SQL uses only valid table/column combinations."""
    # Ensure schema is loaded
    if VALID_COLUMNS is None:
        return True, "OK"  # Skip validation if schema not loaded yet
    
    # Extract table.column patterns
    # Match patterns like table.column or table.column AS alias
    pattern = r'\b(\w+)\.(\w+)\b'
    matches = re.findall(pattern, sql, re.IGNORECASE)
    
    for table, column in matches:
        table_lower = table.lower()
        column_lower = column.lower()
        
        # Skip if table not in our schema (might be a subquery alias)
        if table_lower not in VALID_COLUMNS:
            continue
            
        # Check if column exists in table
        if column_lower not in VALID_COLUMNS[table_lower]:
            return False, f"Invalid column '{column}' in table '{table}'"
    
    return True, "OK"


async def _ensure_schema_loaded():
    """Ensure schema is loaded from DB (lazy load on first use)."""
    global DB_SCHEMA, VALID_COLUMNS
    if DB_SCHEMA is None or VALID_COLUMNS is None:
        await _load_schema_from_db()


async def _generate_sql(intent: str, parameters: dict) -> dict:
    """LLM generates SQL based on intent and schema. Returns SQL and extracted parameters."""
    # Ensure schema is loaded
    await _ensure_schema_loaded()
    
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
- Return ONLY JSON with "sql" and "params" keys, no explanation

Example:
INPUT: "show top 3 customers by credit limit"
OUTPUT: {{"sql": "SELECT name, city, credit_limit FROM customers WHERE org_id = $1 ORDER BY credit_limit DESC NULLS LAST LIMIT 3", "params": {{"limit": 3}}}}

INPUT: "dues for Mehta Jewellers"
OUTPUT: {{"sql": "SELECT c.name, i.invoice_number, i.amount, i.status, i.due_date FROM invoices i JOIN customers c ON c.id = i.customer_id WHERE i.org_id = $1 AND c.org_id = $1 AND c.name ILIKE $2 AND i.status IN ('pending', 'overdue') ORDER BY i.due_date ASC", "params": {{"customer_name": "Mehta"}}}}

Now generate SQL for:
{intent}
"""

    response = await _client.chat.completions.create(
        model="gpt-4o-mini",
        max_tokens=500,
        temperature=0,
        messages=[{"role": "user", "content": prompt}],
    )
    
    content = response.choices[0].message.content.strip()
    
    # Clean up markdown if present
    if content.startswith('```'):
        content = content.split('```')[1]
        if content.startswith('sql'):
            content = content[3:]
    content = content.strip()
    
    # Parse JSON
    import json
    result = json.loads(content)
    
    return result


def _extract_parameters(sql: str, llm_params: dict, org_id: str) -> list:
    """Build parameter list from LLM-extracted params, matching SQL placeholder count."""
    # Count actual parameter placeholders in SQL
    import re
    placeholders = re.findall(r'\$(\d+)', sql)
    max_placeholder = max([int(p) for p in placeholders]) if placeholders else 0
    
    params = [org_id]  # $1 is always org_id
    
    # Build params from LLM output, but only up to the number of placeholders
    param_values = []
    for key, value in llm_params.items():
        if key == 'limit':
            param_values.append(int(value))
        elif key in ['customer_name', 'product_name', 'invoice_number']:
            # Add wildcards for ILIKE
            if isinstance(value, str) and not value.startswith('%'):
                value = f'%{value}%'
            param_values.append(value)
        else:
            param_values.append(value)
    
    # Only append as many params as there are placeholders (minus 1 for org_id)
    for i in range(min(len(param_values), max_placeholder - 1)):
        params.append(param_values[i])
    
    return params


def _format_results(rows: list, sql: str) -> str:
    """Format query results for WhatsApp."""
    if not rows:
        return "✅ No results found."
    
    # Filter out sensitive columns
    sensitive_columns = {'id', 'org_id', 'user_id', 'role_id', 'customer_id', 'invoice_id', 
                         'quotation_id', 'order_id', 'created_by', 'updated_by', 'scheduled_by',
                         'decided_by', 'requester_id', 'approver_role', 'workflow_id'}
    
    # Also filter UUID-like values
    def is_uuid_like(val):
        if not isinstance(val, str):
            return False
        # Check if it looks like a UUID (contains hyphens and is long)
        if '-' in val and len(val) > 20:
            return True
        return False
    
    # Filter columns and values
    filtered_rows = []
    for r in rows:
        filtered = {}
        for col, val in r.items():
            if col.lower() in sensitive_columns:
                continue
            if is_uuid_like(val):
                continue
            filtered[col] = val
        filtered_rows.append(filtered)
    
    if not filtered_rows or not filtered_rows[0]:
        return "✅ No displayable results."
    
    # Try to infer format based on columns
    cols = list(filtered_rows[0].keys())
    
    # Smart formatting based on column names
    lines = []
    
    # Special formatting for roles/permissions
    if 'name' in cols and 'permissions' in cols:
        lines.append("👥 *Roles & Permissions*")
        for r in filtered_rows:
            role = r.get('name', 'Unknown')
            perms = r.get('permissions', [])
            if isinstance(perms, list):
                perms_str = ', '.join(perms[:5])  # Limit to 5 permissions
                if len(perms) > 5:
                    perms_str += f" +{len(perms)-5} more"
            else:
                perms_str = str(perms)[:50]
            lines.append(f"\n• *{role}*: {perms_str}")
        return "\n".join(lines)
    
    # Special formatting for customers
    if 'name' in cols and 'city' in cols:
        lines.append("👤 *Customers*")
        for r in filtered_rows[:10]:
            name = r.get('name', 'N/A')
            city = r.get('city', 'N/A')
            credit = r.get('credit_limit', '')
            if credit:
                lines.append(f"• {name} ({city}) — ₹{credit:,.0f}")
            else:
                lines.append(f"• {name} ({city})")
        if len(filtered_rows) > 10:
            lines.append(f"\n... and {len(filtered_rows) - 10} more")
        return "\n".join(lines)
    
    # Special formatting for inventory
    if 'name' in cols and 'qty' in cols:
        lines.append("📦 *Inventory*")
        for r in filtered_rows[:10]:
            name = r.get('name', 'N/A')
            qty = r.get('qty', 0)
            location = r.get('location', 'N/A')
            lines.append(f"• {name}: {qty} pcs ({location})")
        if len(filtered_rows) > 10:
            lines.append(f"\n... and {len(filtered_rows) - 10} more")
        return "\n".join(lines)
    
    # Default table format (limited columns)
    display_cols = cols[:4]  # Limit to 4 columns
    header = " | ".join(display_cols)
    lines = [f"📊 *Results*\n\n{header}"]
    
    for r in filtered_rows[:10]:
        vals = " | ".join(str(r.get(c, ''))[:20] for c in display_cols)
        lines.append(vals)
    
    if len(filtered_rows) > 10:
        lines.append(f"\n... and {len(filtered_rows) - 10} more")
    
    return "\n".join(lines)


async def execute_read(org_id: str, intent: str, parameters: dict) -> str:
    """Execute a general_read request with dynamic SQL generation."""
    try:
        # Generate SQL (LLM returns both SQL and params)
        result = await _generate_sql(intent, parameters)
        sql = result["sql"]
        llm_params = result.get("params", {})
        
        # Validate SQL safety
        is_safe, reason = _validate_sql(sql)
        if not is_safe:
            print(f"[QUERY_ENGINE] SQL blocked: {reason}")
            return "🤔 I couldn't understand that query. Please try rephrasing it."
        
        # Validate schema (columns exist in tables)
        is_valid, schema_reason = _validate_schema(sql)
        if not is_valid:
            print(f"[QUERY_ENGINE] Schema validation failed: {schema_reason}")
            return "🤔 I couldn't understand that query. Please try rephrasing it in a different way."
        
        # Build parameters from LLM-extracted values
        params = _extract_parameters(sql, llm_params, org_id)
        
        # Execute
        rows = await fetch_all(sql, *params)
        rows = [dict(r) for r in rows]
        
        # Format results
        return _format_results(rows, sql)
        
    except Exception as e:
        print(f"[QUERY_ENGINE] Error: {e}")
        return "🤔 Something went wrong. Please try rephrasing your query."
