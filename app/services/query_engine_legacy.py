"""Legacy SQL template execution for action workflow reads still in DB."""
from app.db import fetch_all
from app.services.sql_runner import validate_sql, clean_rows
from app.services.read_agent import run_read_agent


def _build_template_params(org_id, entities, params_order, entity_schema, user_id=None):
    session_context = entity_schema.get("session_context", False)
    params = [user_id if session_context and user_id else org_id]
    for field in params_order:
        val = entities.get(field)
        if val is None:
            schema = entity_schema.get(field, {})
            val = schema.get("default")
            if val is None:
                val = 20 if schema.get("type") == "integer" else ""
        params.append(val)
    return params


async def execute_template(
    org_id, sql_template, entities, params_order,
    entity_schema, response_format="generic", user_id=None,
):
    ok, reason = validate_sql(sql_template)
    if not ok:
        return f"🤔 Query configuration error. ({reason})"
    try:
        params = _build_template_params(org_id, entities, params_order, entity_schema, user_id)
        rows = [dict(r) for r in await fetch_all(sql_template, *params)]
        cleaned = clean_rows(rows)
        if not cleaned:
            return "✅ No results found."
        user = {"org_id": org_id, "role": "owner", "user_name": "", "org_name": "", "permissions": []}
        return await run_read_agent(
            user,
            f"Format this query result for WhatsApp:\n{sql_template}",
            extra_context=f"DATA:\n{cleaned}",
        )
    except Exception as e:
        print(f"[QUERY_ENGINE] Template error: {e}")
        return "🤔 Something went wrong running that query."
