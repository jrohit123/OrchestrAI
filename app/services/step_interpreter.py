"""
step_interpreter.py — Generic executor for workflows.steps[].

Adding workflow #41 never requires touching this file.
All execution logic lives in the workflow record in the DB.

Available step ops:
  resolve_entity   — look up a named entity from any table (supports expose param)
  compute          — run qa_verifier to validate + recompute via calc_rules
  otp_gate         — halt for OTP verification if amount >= threshold
  approval_gate    — halt for approval if amount >= threshold and user is not owner
  db.insert_row    — insert a row into any table with field mapping + sequence generation
  db.update_row    — update an existing row in any table
  db.upsert_row    — insert or update (ON CONFLICT) in any table
  pdf.generate     — generate PDF using workflow's pdf_config
  notify.whatsapp  — send PDF and/or text message to the user
"""
import json
from app.db import fetch_one, fetch_all, execute
from app.services.qa_verifier import verify_draft, VerificationError
from app.services.otp_service import generate_and_send_otp


class StepError(Exception):
    pass


def _parse_jsonb(val, default=None):
    if isinstance(val, str):
        try:
            return json.loads(val)
        except Exception:
            return default
    return val if val is not None else default


def _resolve_path(ctx: dict, path):
    """
    Resolve a $path reference into a value from ctx.
    '$fields.customer_name' → ctx['fields']['customer_name']
    '$computed.total'       → ctx['computed']['total']
    '$customer.id'          → ctx['customer']['id']
    '$org_id'               → ctx['org_id']
    '$user.user_id'         → ctx['user']['user_id']
    Non-$ values are returned as-is (literal).
    """
    if not isinstance(path, str) or not path.startswith("$"):
        return path
    parts = path[1:].split(".")
    val = ctx
    for p in parts:
        if isinstance(val, dict):
            val = val.get(p)
        else:
            return None
    return val


def _resolve_values(values: dict, ctx: dict) -> dict:
    return {
        k: _resolve_path(ctx, v) if isinstance(v, str) else v
        for k, v in values.items()
    }


# ── Step primitives ───────────────────────────────────────────────────────────

async def _op_resolve_entity(params: dict, ctx: dict) -> dict:
    """
    Look up a named entity from any table by a fuzzy name match.
    Stores the full resolved row in ctx[into] for downstream steps.
    Optional expose: {"alias": "column"} copies columns into ctx["fields"]
    so calc_rules can reference them.
    """
    table      = params["table"]
    match_col  = params.get("match_column", "name")
    into       = params.get("into", table.rstrip("s"))
    name_path  = params["name_from"]
    name_val   = _resolve_path(ctx, name_path)

    if not name_val:
        raise StepError(f"resolve_entity: no value at '{name_path}'")

    # NEW: table="sheet:TabName" routes to Google Sheets instead of Postgres
    if table.startswith("sheet:"):
        from app.services.sheets_client import sheet_fetch_filtered
        tab = table.split(":", 1)[1]
        rows = await sheet_fetch_filtered(tab, {match_col: name_val})
    else:
        raw_rows = await fetch_all(
            f"SELECT * FROM {table} WHERE org_id = $1 AND {match_col} ILIKE $2 LIMIT 5",
            ctx["org_id"], f"%{name_val}%"
        )
        rows = [dict(r) for r in raw_rows]

    if len(rows) == 0:
        raise StepError(f"No {table} record found matching '{name_val}'")
    if len(rows) > 1:
        raise StepError(f"AMBIGUOUS:{table}:{json.dumps(rows, default=str)}")

    resolved = dict(rows[0])
    ctx[into] = resolved

    # expose: copy named columns from resolved row into ctx["fields"]
    # so calc_rules can reference them as if they were user-provided inputs
    for alias, column in (params.get("expose") or {}).items():
        ctx["fields"][alias] = resolved.get(column)

    return ctx


async def _op_compute(params: dict, ctx: dict) -> dict:
    """
    Run qa_verifier: validate required fields + recompute all calc_rules.
    Overwrites ctx['fields'] with verified values.
    Computed values also stored in ctx['computed'] for downstream $computed.x references.
    """
    verified = await verify_draft(ctx["workflow"], ctx["fields"], ctx["org_id"])
    ctx["fields"]   = verified
    ctx["computed"] = verified
    return ctx


async def _op_otp_gate(params: dict, ctx: dict) -> dict:
    """
    Halt for OTP if total amount >= workflow's otp_threshold.
    Skipped if already verified.
    """
    if ctx.get("otp_verified"):
        return ctx

    amount_path   = params.get("amount_field", "$computed.total_amount")
    amount        = float(_resolve_path(ctx, amount_path) or 0)
    otp_threshold = float(_parse_jsonb(ctx["workflow"].get("otp_threshold"), 0) or 0)

    if otp_threshold <= 0 or amount < otp_threshold:
        return ctx

    user = ctx["user"]
    sent = await generate_and_send_otp(
        user_id=user["user_id"],
        user_email=user["email"],
        user_name=user["user_name"],
        org_name=user["org_name"],
        org_id=user["org_id"],
        action_context={"type": "action_otp", "intent_key": ctx["workflow"]["intent_key"]}
    )
    if not sent:
        raise StepError("Could not send OTP email")

    ctx["_halt"] = "awaiting_otp"
    return ctx


async def _op_approval_gate(params: dict, ctx: dict) -> dict:
    """
    Halt for approval if total amount >= workflow's approval_threshold
    and the user is not the owner role.
    Sends approval buttons to the org owner and creates a pending_approvals record.
    Skipped if already approved.
    """
    if ctx.get("approved"):
        return ctx

    amount_path        = params.get("amount_field", "$computed.total_amount")
    amount             = float(_resolve_path(ctx, amount_path) or 0)
    approval_threshold = float(_parse_jsonb(ctx["workflow"].get("approval_threshold"), 0) or 0)
    owner_role_id      = "22220000-0000-0000-0000-000000000001"

    if approval_threshold <= 0 or amount < approval_threshold:
        return ctx
    if ctx["user"].get("role_id") == owner_role_id:
        return ctx

    # Find the org owner to send approval request to
    org_id = ctx["org_id"]
    user   = ctx["user"]
    owner  = await fetch_one("""
        SELECT u.phone, u.name, u.id FROM users u
        JOIN roles r ON r.id = u.role_id
        WHERE u.org_id = $1 AND r.id = $2
          AND u.is_active = true AND u.phone IS NOT NULL
        LIMIT 1
    """, org_id, owner_role_id)

    if owner:
        from app.services.whatsapp import send_buttons as _send_buttons
        # Store pending_action in approval context so it can be resumed
        approval_context = {
            "pending_action":    {**ctx["workflow"], "fields": ctx["fields"],
                                  "intent_key": ctx["workflow"]["intent_key"],
                                  "resume_step": 0},
            "requester_id":      user["user_id"],
            "requester_phone":   ctx.get("phone", ""),
            "requester_name":    user.get("user_name", ""),
            "requester_email":   user.get("email", ""),
        }
        await execute("""
            INSERT INTO pending_approvals
            (org_id, requester_id, approver_role, intent_key, context, status)
            VALUES ($1, $2, 'owner', $3, $4::jsonb, 'pending')
        """, org_id, user["user_id"],
            ctx["workflow"]["intent_key"], json.dumps(approval_context))

        await _send_buttons(
            to=owner["phone"],
            body=(
                f"📋 *Approval Request*\n\n"
                f"From: {user.get('user_name', 'Staff')} ({user.get('role', '')})\n"
                f"Action: {ctx['workflow'].get('name', ctx['workflow']['intent_key'])}\n"
                f"Amount: Rs.{amount:,.0f}\n\n"
                f"Please approve or reject:"
            ),
            buttons=[
                {"id": "action:approve", "title": "✅ Approve"},
                {"id": "action:reject",  "title": "❌ Reject"}
            ]
        )

    ctx["_halt"] = "awaiting_approval"
    return ctx


async def _op_insert_row(params: dict, ctx: dict) -> dict:
    """
    Insert one row into any table.
    values: dict of {column: $path_or_literal}
    sequence: {field, prefix, start} — generates a document number (INV-101, QUO-1001, etc.)
    """
    table  = params["table"]
    values = _resolve_values(params.get("values", {}), ctx)

    # Resolve special date literals
    import datetime as _dt
    for k, v in list(values.items()):
        if v == "TODAY+30":
            values[k] = (_dt.date.today() + _dt.timedelta(days=30)).isoformat()
        elif v == "TODAY+7":
            values[k] = (_dt.date.today() + _dt.timedelta(days=7)).isoformat()
        elif v == "TODAY":
            values[k] = _dt.date.today().isoformat()
        elif v == "NOW()":
            values[k] = _dt.datetime.now(_dt.timezone.utc)

    # NEW: sheet-backed insert
    if table.startswith("sheet:"):
        from app.services.sheets_client import sheet_insert_row, sheet_count_rows
        tab = table.split(":", 1)[1]

        if "sequence" in params:
            seq = params["sequence"]
            count = await sheet_count_rows(tab)
            doc_number = seq["prefix"] + str(seq.get("start", 1000) + count)
            values[seq["field"]] = doc_number
            ctx.setdefault("generated", {})[seq["field"]] = doc_number

        # Serialize lists/dicts same as Postgres path, for consistency
        for k, v in list(values.items()):
            if isinstance(v, (list, dict)):
                values[k] = json.dumps(v)

        await sheet_insert_row(tab, values)
        ctx.setdefault("inserted", {})[tab] = values
        return ctx

    # ── existing Postgres path (unchanged below this line) ──
    if "sequence" in params:
        seq = params["sequence"]
        max_row = await fetch_one(
            f"""SELECT MAX(NULLIF(regexp_replace({seq['field']}, '\\D', '', 'g'), '')::int) AS max_num
                FROM {table} WHERE org_id = $1 AND {seq['field']} LIKE $2""",
            ctx["org_id"], f"{seq['prefix']}%"
        )
        next_num = max(int(max_row["max_num"] or 0) + 1, seq.get("start", 100))
        doc_number = seq["prefix"] + str(next_num)
        values[seq["field"]] = doc_number
        ctx.setdefault("generated", {})[seq["field"]] = doc_number

    cols        = list(values.keys())
    sql_values  = [json.dumps(v) if isinstance(v, (list, dict)) else v for v in values.values()]
    placeholders = ", ".join(f"${i+1}" for i in range(len(cols)))
    sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders}) RETURNING *"

    row = await fetch_one(sql, *sql_values)
    ctx.setdefault("inserted", {})[table] = dict(row)
    return ctx


async def _op_generate_pdf(params: dict, ctx: dict) -> dict:
    """
    Generate PDF using the workflow's pdf_config.
    pdf_config.render_instructions drives the layout — no hardcoded doc_type branches.
    """
    from app.services.pdf_engine import generate_pdf
    from app.services.pdf_preprocessor import preprocess_rows

    workflow   = ctx["workflow"]
    pdf_config = _parse_jsonb(workflow.get("pdf_config"), {}) or {}

    # Build the row data — prefer inserted DB row, fall back to fields
    inserted  = list(ctx.get("inserted", {}).values())
    row_data  = {**(inserted[0] if inserted else {}), **ctx["fields"], **ctx.get("computed", {})}

    # Merge resolved entities (e.g. customer) into extra_context so PDF can show
    # customer name, city, GSTIN etc. without needing a separate DB query
    for entity_key in ("customer", "order", "vendor"):
        if ctx.get(entity_key):
            entity = ctx[entity_key]
            # Prefix with entity key to avoid collisions e.g. customer_name, customer_city
            for col, val in entity.items():
                if col not in ("id", "org_id") and val is not None:
                    row_data.setdefault(f"customer_{col}" if entity_key == "customer" else col, val)

    rows, analysis = preprocess_rows([row_data], pdf_config.get("doc_type", "report"))

    # Build title from template
    all_ctx   = {**ctx["fields"], **ctx.get("computed", {}), **ctx.get("generated", {})}
    title_tmpl = pdf_config.get("title_template", workflow.get("name", "Document"))
    try:
        title = title_tmpl.format(**all_ctx)
    except (KeyError, IndexError):
        title = title_tmpl

    subtitle_tmpl = pdf_config.get("subtitle_template", "")
    try:
        subtitle = subtitle_tmpl.format(**all_ctx) if subtitle_tmpl else params.get("subtitle", "")
    except (KeyError, IndexError):
        subtitle = subtitle_tmpl

    # Merge everything into extra_context for PDF engine
    extra = {
        **ctx["fields"],
        **ctx.get("computed", {}),
        **ctx.get("generated", {}),
        **analysis,
    }

    pdf_bytes = await generate_pdf(
        rows=rows,
        title=title,
        org_name=ctx["user"]["org_name"],
        subtitle=subtitle,
        doc_type=pdf_config.get("doc_type", "report"),
        extra_context=extra,
        pdf_config=pdf_config,
    )
    ctx["pdf_bytes"] = pdf_bytes
    return ctx


async def _op_update_row(params: dict, ctx: dict) -> dict:
    """
    Generic parameterized UPDATE.
    params: {table, set: {col: $path_or_literal}, where: {col: $path_or_literal}}
    Use "NOW()" as a literal string to set timestamp columns to current time.
    """
    import datetime as _dt
    table       = params["table"]
    set_vals    = _resolve_values(params.get("set", {}), ctx)
    where_vals  = _resolve_values(params.get("where", {}), ctx)

    def _resolve_now(v):
        return _dt.datetime.now(_dt.timezone.utc) if v == "NOW()" else v

    set_vals   = {k: _resolve_now(v) for k, v in set_vals.items()}
    where_vals = {k: _resolve_now(v) for k, v in where_vals.items()}

    # NEW: sheet-backed update
    if table.startswith("sheet:"):
        from app.services.sheets_client import sheet_update_row
        tab = table.split(":", 1)[1]
        updated = await sheet_update_row(tab, where_vals, set_vals)
        if not updated:
            raise StepError(f"db.update_row: no matching row in sheet '{tab}'")
        ctx.setdefault("updated", {})[tab] = updated
        return ctx

    # ── existing Postgres path (unchanged below this line) ──
    set_cols   = list(set_vals.keys())
    where_cols = list(where_vals.keys())

    set_clause   = ", ".join(f"{c} = ${i+1}" for i, c in enumerate(set_cols))
    where_clause = " AND ".join(
        f"{c} = ${i+1+len(set_cols)}" for i, c in enumerate(where_cols)
    )
    sql_values = (
        [json.dumps(v) if isinstance(v, (list, dict)) else v for v in set_vals.values()]
        + list(where_vals.values())
    )
    sql = f"UPDATE {table} SET {set_clause} WHERE {where_clause} RETURNING *"

    row = await fetch_one(sql, *sql_values)
    if not row:
        raise StepError(f"db.update_row: no matching row in {table}")
    ctx.setdefault("updated", {})[table] = dict(row)
    return ctx


async def _op_delete_row(params: dict, ctx: dict) -> dict:
    """
    Delete one row matching `where`. Supports table="sheet:TabName" and
    plain Postgres tables. NEW primitive — not in the original set.
    """
    table      = params["table"]
    where_vals = _resolve_values(params.get("where", {}), ctx)

    if table.startswith("sheet:"):
        from app.services.sheets_client import sheet_delete_row
        tab = table.split(":", 1)[1]
        ok = await sheet_delete_row(tab, where_vals)
        if not ok:
            raise StepError(f"db.delete_row: no matching row in sheet '{tab}'")
        ctx.setdefault("deleted", {})[tab] = where_vals
        return ctx

    where_cols   = list(where_vals.keys())
    where_clause = " AND ".join(f"{c} = ${i+1}" for i, c in enumerate(where_cols))
    sql = f"DELETE FROM {table} WHERE {where_clause} RETURNING *"
    row = await fetch_one(sql, *where_vals.values())
    if not row:
        raise StepError(f"db.delete_row: no matching row in {table}")
    ctx.setdefault("deleted", {})[table] = dict(row)
    return ctx


async def _op_ai_price_interpret(params: dict, ctx: dict) -> dict:
    """
    Dual-LLM (Gemini + OpenAI) price interpretation for items carrying a raw
    `rate_text` instead of an already-resolved `unit_price`. Runs BEFORE
    `compute` — once unit_price is settled here, calc_engine (never an LLM)
    does all the arithmetic downstream. See llm_qa_reviewer.py.
    """
    from app.services.llm_qa_reviewer import dual_verify_price

    items = ctx["fields"].get("items", [])
    resolved_items = []
    for item in items:
        if item.get("unit_price") is not None or not item.get("rate_text"):
            resolved_items.append(item)
            continue

        result = await dual_verify_price(
            rate_text=item["rate_text"],
            weight=float(item.get("weight") or 1),
            qty=float(item.get("qty") or 1),
        )
        if not result["agreed"]:
            raise StepError(f"PRICE_AMBIGUOUS:{result['message']}")

        item = {**item, "unit_price": result["unit_price"]}
        item.pop("rate_text", None)
        resolved_items.append(item)

    ctx["fields"]["items"] = resolved_items
    return ctx


async def _op_upsert_row(params: dict, ctx: dict) -> dict:
    """
    Generic INSERT ... ON CONFLICT DO UPDATE.
    params: {table, values: {col: $path_or_literal}, conflict_columns: [col1, col2]}
    """
    import datetime as _dt
    table          = params["table"]
    conflict_cols  = params.get("conflict_columns", [])
    raw_values     = _resolve_values(params.get("values", {}), ctx)

    def _resolve_now(v):
        if v == "NOW()":
            return _dt.datetime.now(_dt.timezone.utc)
        return v

    values = {k: _resolve_now(v) for k, v in raw_values.items()}

    cols         = list(values.keys())
    placeholders = ", ".join(f"${i+1}" for i in range(len(cols)))
    update_clause = ", ".join(
        f"{c} = EXCLUDED.{c}" for c in cols if c not in conflict_cols
    )
    sql_values = [
        json.dumps(v) if isinstance(v, (list, dict)) else v for v in values.values()
    ]
    sql = (
        f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT ({', '.join(conflict_cols)}) DO UPDATE SET {update_clause} "
        f"RETURNING *"
    )

    row = await fetch_one(sql, *sql_values)
    ctx.setdefault("upserted", {})[table] = dict(row) if row else {}
    return ctx


async def _op_notify_whatsapp(params: dict, ctx: dict) -> dict:
    """
    Send PDF document and/or text message to the user's WhatsApp.
    """
    from app.services.whatsapp import send_document, send_text

    phone = ctx.get("phone") or ctx["user"].get("phone")
    if not phone:
        return ctx

    if params.get("attach_pdf") and ctx.get("pdf_bytes"):
        generated = ctx.get("generated", {})
        doc_id    = next(iter(generated.values()), "document") if generated else "document"
        await send_document(
            to=phone,
            pdf_bytes=ctx["pdf_bytes"],
            filename=f"{doc_id}.pdf",
            caption=f"📄 {doc_id}"
        )

    if ctx.get("_final_message"):
        await send_text(phone, ctx["_final_message"])

    return ctx


# ── Op registry — adding a new op never requires changing action_executor.py ─

PRIMITIVES = {
    "resolve_entity":     _op_resolve_entity,
    "ai_price_interpret": _op_ai_price_interpret,
    "compute":            _op_compute,
    "otp_gate":           _op_otp_gate,
    "approval_gate":      _op_approval_gate,
    "db.insert_row":      _op_insert_row,
    "db.update_row":      _op_update_row,
    "db.upsert_row":      _op_upsert_row,
    "db.delete_row":      _op_delete_row,    # NEW
    "sheets.insert_row":  _op_insert_row,    # NEW — alias, dispatches on "sheet:" prefix
    "sheets.update_row":  _op_update_row,    # NEW — alias
    "sheets.delete_row":  _op_delete_row,    # NEW — alias
    "pdf.generate":       _op_generate_pdf,
    "notify.whatsapp":    _op_notify_whatsapp,
}


# ── Main runner ───────────────────────────────────────────────────────────────

async def run_workflow_steps(
    workflow: dict,
    fields: dict,
    user: dict,
    phone: str,
    resume_step: int = 0,
    otp_verified: bool = False,
    approved: bool = False,
) -> dict:
    """
    Execute a workflow's steps[] sequentially from resume_step.
    Returns a result dict with status: done | awaiting_otp | awaiting_approval | error | ambiguous.
    """
    ctx = {
        "fields":       dict(fields),
        "computed":     {},
        "generated":    {},
        "inserted":     {},
        "user":         user,
        "org_id":       user["org_id"],
        "phone":        phone,
        "workflow":     workflow,
        "otp_verified": otp_verified,
        "approved":     approved,
    }

    steps = _parse_jsonb(workflow.get("steps"), []) or []

    try:
        for i in range(resume_step, len(steps)):
            step = steps[i]
            if isinstance(step, str):
                step = json.loads(step)

            op_name = step.get("op")
            op_fn   = PRIMITIVES.get(op_name)
            if not op_fn:
                raise StepError(f"Unknown step op: '{op_name}'")

            print(f"[STEP_INTERP] Step {i+1}/{len(steps)}: {op_name}")
            ctx = await op_fn(step.get("params", {}), ctx)

            if ctx.get("_halt"):
                return {
                    "status":      ctx["_halt"],
                    "resume_step": i + 1,
                    "message":     _gate_message(ctx["_halt"], user),
                }

    except VerificationError as e:
        return {
            "status":         "error",
            "missing_fields": e.missing_fields,
            "invalid_fields": e.invalid_fields,
            "message":        e.message,
        }

    except StepError as e:
        msg = str(e)
        if msg.startswith("AMBIGUOUS:"):
            _, table, candidates_json = msg.split(":", 2)
            return {
                "status":     "ambiguous",
                "table":      table,
                "candidates": json.loads(candidates_json),
            }
        if msg.startswith("PRICE_AMBIGUOUS:"):
            _, message = msg.split(":", 1)
            return {"status": "error", "message": message}
        return {"status": "error", "message": msg}

    # Build final success message from workflow's response_template
    template  = workflow.get("response_template")
    all_vals  = {**ctx["fields"], **ctx.get("computed", {}), **ctx.get("generated", {})}
    if template:
        try:
            message = template.format(**all_vals)
        except (KeyError, IndexError):
            message = f"✅ {workflow.get('name', 'Action')} completed successfully."
    else:
        doc_number = next(iter(ctx.get("generated", {}).values()), None)
        if doc_number:
            message = f"✅ {workflow.get('name', 'Document')} *{doc_number}* created successfully."
        else:
            message = f"✅ {workflow.get('name', 'Action')} completed successfully."

    ctx["_final_message"] = message

    # Send WhatsApp notification if notify.whatsapp wasn't in steps
    # (safety net — step_interpreter already called it if it was in steps)
    if ctx.get("pdf_bytes") and "notify.whatsapp" not in [
        s.get("op") if isinstance(s, dict) else json.loads(s).get("op")
        for s in steps
    ]:
        await _op_notify_whatsapp({}, ctx)

    return {
        "status":    "done",
        "message":   message,
        "pdf_bytes": ctx.get("pdf_bytes"),
        "generated": ctx.get("generated", {}),
        "inserted":  ctx.get("inserted", {}),
    }


def _gate_message(stage: str, user: dict) -> str:
    if stage == "awaiting_otp":
        return (
            f"🔐 *Security Verification Required*\n\n"
            f"A 4-digit code has been sent to *{user.get('email', 'your email')}*\n"
            f"Reply with the code to continue.\n\n"
            f"⏱ Code expires in 3 minutes."
        )
    return (
        "This action requires MD approval.\n"
        "Approval request sent. You'll be notified once approved."
    )
