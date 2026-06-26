import json
import re
from app.services.otp_service import generate_and_send_otp
from app.services.whatsapp import send_text, send_buttons
from app.redis_client import set_session, clear_all_sessions
from app.db import fetch_one, execute
from app.scheduler.jobs import reschedule_dues_report, stop_dues_report, get_job_schedule


async def _dispatch_dynamic_intent(intent: str, entity: str | None, org_id: str, raw_text: str, adapter_method: str, session_id: str = None, user_id: str = None, phone: str = None, parameters: dict = None, **ignored) -> str:
    """
    Generic dispatcher for DB-registered workflows that have no hardcoded handler.
    Dynamically imports and calls the adapter function specified in the workflow config.
    Handles disambiguation when multiple customer matches are found.
    """
    if adapter_method == "generic":
        return (
            f"⚙️ Workflow *{intent.replace('_', ' ').title()}* was recognised "
            f"but has no adapter method configured. Contact your admin."
        )

    try:
        # Dynamic import: adapter_method format is "module.function" e.g., "crm.get_credit_limit"
        if "." not in adapter_method:
            return f"⚙️ Invalid adapter method format: {adapter_method}. Expected 'module.function'"
        
        module_name, func_name = adapter_method.split(".", 1)
        
        # Import the adapter module dynamically
        module = __import__(f"app.adapters.{module_name}", fromlist=[func_name])
        adapter_func = getattr(module, func_name)
        
        # Build context dict for adapters that need more than org_id + entity
        parameters = parameters or {}
        context = {
            "org_id": org_id,
            "user_id": user_id,
            "phone": phone,
            "raw_text": raw_text,
            "entity_raw": entity,
            **parameters,  # LLM-extracted fields override
        }
        
        # Call the adapter with appropriate arguments
        # Try calling with context dict first (for complex adapters like quotation)
        try:
            result = await adapter_func(**context)
        except TypeError:
            # Fallback to simple (org_id, entity) signature for backward compatibility
            result = await adapter_func(org_id, entity if entity else None)
        
        # Check if multiple matches found (disambiguation needed)
        if result.get("found") and not result.get("single_match", True):
            matches = result.get("matches", [])
            if matches and session_id:
                # Convert UUID to string for JSON serialization
                serializable_matches = [
                    {"id": str(m["id"]), "name": m["name"], "city": m["city"]} 
                    for m in matches
                ]
                # Store matches in session for selection
                await set_session(session_id, {
                    "disambiguation": True,
                    "matches": serializable_matches,
                    "intent": intent,
                    "adapter_method": adapter_method,
                    "entity": entity
                })
                
                # Present numbered options
                options = "\n".join([f"{i+1}. {m['name']} ({m['city']})" for i, m in enumerate(matches)])
                return f"🔍 {result['message']}\n\nReply with number:\n{options}"
        
        return result["message"]
    except ImportError:
        return f"⚙️ Adapter module not found: app.adapters.{module_name}. Contact admin."
    except AttributeError:
        return f"⚙️ Function {func_name} not found in {module_name}. Contact admin."
    except Exception as e:
        return f"⚙️ Error executing {adapter_method}: {str(e)}"


async def _get_invoice_thresholds(org_id: str) -> tuple[float, float]:
    """Fetch OTP and approval thresholds from DB. Returns (otp_threshold, approval_threshold)."""
    row = await fetch_one("""
        SELECT otp_threshold, approval_threshold, otp_required
        FROM workflows
        WHERE org_id = $1 AND intent_key = 'create_invoice'
    """, org_id)

    if not row or not row["otp_required"]:
        return (999999999, 999999999)  # effectively disabled

    otp = float(row["otp_threshold"]) if row["otp_threshold"] else 50000.0
    approval = float(row["approval_threshold"]) if row["approval_threshold"] else 100000.0
    return (otp, approval)


def _parse_schedule(text: str) -> dict:
    """Parse day + time from natural language schedule command."""
    t = text.lower()

    # Stop/cancel
    if any(w in t for w in ["stop", "cancel", "pause", "off"]):
        return {"action": "stop"}

    # Status check
    if any(w in t for w in ["when", "what time", "status", "check"]):
        return {"action": "status"}

    # Parse day
    day_map = {
        "monday": "mon", "tuesday": "tue", "wednesday": "wed",
        "thursday": "thu", "friday": "fri", "saturday": "sat", "sunday": "sun",
        "mon": "mon", "tue": "tue", "wed": "wed", "thu": "thu",
        "fri": "fri", "sat": "sat", "sun": "sun",
        "daily": "*", "everyday": "*", "every day": "*"
    }
    day = "mon"  # default
    for word, code in day_map.items():
        if word in t:
            day = code
            break

    # Parse hour + minute — AM/PM format like "5:15 PM" or "5 PM"
    hour = None
    minute = 0

    m = re.search(r"(\d{1,2}):(\d{2})\s*(am|pm)", t)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2))
        period = m.group(3)
        if period == "pm" and hour != 12:
            hour += 12
        elif period == "am" and hour == 12:
            hour = 0

    # No minutes — just hour + AM/PM like "5 PM"
    if hour is None:
        m = re.search(r"(\d{1,2})\s*(am|pm)", t)
        if m:
            hour = int(m.group(1))
            minute = 0
            period = m.group(2)
            if period == "pm" and hour != 12:
                hour += 12
            elif period == "am" and hour == 12:
                hour = 0

    # 24hr with minutes like "17:10" or "at 14:30"
    if hour is None:
        m = re.search(r"(\d{1,2}):(\d{2})", t)
        if m:
            hour = int(m.group(1))
            minute = int(m.group(2))

    # Plain hour like "at 17"
    if hour is None:
        m = re.search(r"at\s+(\d{1,2})(?:\s|$)", t)
        if m:
            hour = int(m.group(1))
            minute = 0

    if hour is None:
        return {
            "action": "error",
            "message": (
                "🤔 Could not parse time.\n"
                "Try: *schedule dues report every Monday 9 AM*\n"
                "Or: *send report every Tuesday 2 PM*"
            )
        }

    day_labels = {
        "mon": "Monday", "tue": "Tuesday", "wed": "Wednesday",
        "thu": "Thursday", "fri": "Friday", "sat": "Saturday",
        "sun": "Sunday", "*": "day"
    }
    display_hour = hour if hour <= 12 else hour - 12
    display_hour = 12 if display_hour == 0 else display_hour
    period = "AM" if hour < 12 else "PM"
    minute_str = f":{minute:02d}" if minute > 0 else ":00"

    return {
        "action": "set",
        "day": day,
        "hour": hour,
        "minute": minute,
        "label": f"every {day_labels.get(day, day)} at {display_hour}{minute_str} {period} IST"
    }


async def execute_intent(
    intent: str,
    entity_raw: str | None,
    user: dict,
    session_id: str,
    session: dict,
    raw_text: str,
    route_type: str = "workflow",
    parameters: dict = None,
    analyzer_intent: str = "",
    workflow: dict = None,
) -> str:
    """
    Unified executor.
    route_type=workflow with workflow record → read (sql_template) or action (adapter)
    route_type=general_read → query engine unconstrained
    system intents → hardcoded handlers
    """
    org_id  = user["org_id"]
    user_id = user["user_id"]
    phone   = user["phone"]
    params  = parameters or {}

    # ── WORKFLOW ROUTE (matched workflow) ──────────────────────────────────
    if route_type == "workflow" and workflow:
        workflow_type = workflow.get("workflow_type", "action")

        if workflow_type == "read":
            # Execute stored SQL template — zero LLM cost
            from app.services.query_engine import execute_template
            reply = await execute_template(
                org_id        = org_id,
                sql_template  = workflow["sql_template"],
                entities      = params,
                params_order  = workflow.get("sql_params_order", []),
                entity_schema = workflow.get("entity_schema", {}),
                response_format = workflow.get("response_format", "generic"),
            )
            await _log(org_id, user_id, workflow["intent_key"], raw_text, "success")
            return reply

        else:
            # Action workflow: call adapter
            adapter_method = workflow.get("adapter_method", "generic")
            result_msg = await _dispatch_dynamic_intent(
                intent         = workflow["intent_key"],
                entity         = entity_raw,
                org_id         = org_id,
                raw_text       = raw_text,
                adapter_method = adapter_method,
                session_id     = session_id,
                user_id        = user_id,
                phone          = phone,
                parameters     = params,
            )
            await _log(org_id, user_id, workflow["intent_key"], raw_text, "success")
            return result_msg

    # ── UNCONSTRAINED GENERAL READ (fallback — no workflow matched) ────────
    if route_type == "general_read":
        from app.services.query_engine import execute_read
        reply = await execute_read(org_id, analyzer_intent or intent, params)
        await _log(org_id, user_id, "general_read", raw_text, "success")
        return reply

    # ── SYSTEM ADMIN INTENTS (always hardcoded — security critical) ────
    if intent == "manage_schedule":
        if user["role"] != "owner":
            return "❌ Only the Owner can change schedule settings."

        parsed = _parse_schedule(raw_text)

        if parsed["action"] == "error":
            return parsed["message"]

        if parsed["action"] == "status":
            schedule = get_job_schedule()
            return f"📅 Dues report is scheduled for: *{schedule}*"

        if parsed["action"] == "stop":
            stop_dues_report()
            await execute("""
                UPDATE workflows SET is_scheduled = false
                WHERE intent_key = 'weekly_dues_report' AND org_id = $1
            """, org_id)
            return "⏸ Dues report schedule *paused*.\nSend *schedule dues report every Monday 9 AM* to restart."

        if parsed["action"] == "set":
            # Auto-create workflow if it doesn't exist
            existing = await fetch_one(
                "SELECT id FROM workflows WHERE org_id = $1 AND intent_key = 'weekly_dues_report'",
                org_id
            )
            if not existing:
                await execute("""
                    INSERT INTO workflows (
                        org_id, intent_key, name, description, steps,
                        adapter_method, trigger_patterns, is_active, is_scheduled
                    ) VALUES ($1, 'weekly_dues_report', 'Scheduled Dues Report',
                    'System workflow for cron-scheduled overdue summary. Not used for ad-hoc user queries.',
                    ARRAY['["Send aggregated overdue report to scheduled user via WhatsApp"]'::jsonb],
                    'crm.get_all_overdue', '[]'::jsonb, true, false)
                """, org_id)
            
            reschedule_dues_report(parsed["day"], parsed["hour"], parsed.get("minute", 0))
            await execute("""
                UPDATE workflows
                SET is_scheduled = true,
                    schedule_cron = $1,
                    scheduled_by = $2
                WHERE intent_key = 'weekly_dues_report' AND org_id = $3
            """, f"{parsed.get('minute', 0)} {parsed['hour']} * * {parsed['day']}", user_id, org_id)
            return (
                f"✅ *Schedule Updated*\n\n"
                f"Dues report will now be sent *{parsed['label']}*\n"
                f"Next run: {get_job_schedule()}"
            )

    if intent == "clear_sessions":
        if user["role"] != "owner":
            return "❌ Only the Owner can clear all sessions."
        await clear_all_sessions(org_id)
        await _log(org_id, user_id, intent, raw_text, "success")
        return (
            "🔒 *Emergency Lockdown Activated*\n\n"
            "All active sessions have been cleared.\n"
            "Every user will need to re-verify their identity on their next message.\n\n"
            "_Action logged in audit trail._"
        )

    # ── LEGACY: DYNAMIC DB WORKFLOW (fallback for non-intent_matcher routes) ────
    db_workflow = await fetch_one("""
        SELECT name, adapter_method FROM workflows
        WHERE intent_key = $1 AND org_id = $2 AND is_active = true
    """, intent, org_id)

    if db_workflow:
        adapter_method = db_workflow.get("adapter_method", "generic")
        result_msg = await _dispatch_dynamic_intent(
            intent, entity_raw, org_id, raw_text, adapter_method,
            session_id, user_id, phone,
            parameters=parameters,
        )
        await _log(org_id, user_id, intent, raw_text, "success")
        return result_msg

    # Try general_read fallback for unknown intents
    if analyzer_intent:
        from app.services.query_engine import execute_read
        result = await execute_read(org_id, analyzer_intent, params)
        await _log(org_id, user_id, "general_read_fallback", raw_text, "success")
        return result

    return "🤔 Didn't understand that. Type *help* for the menu."


async def resume_after_otp(user: dict, session_id: str, session: dict) -> str:
    """Called after OTP verified — resumes the pending intent."""
    pending = session.get("pending_intent")
    if not pending:
        return "✅ Verified! Please resend your original request."

    # For security OTP (not invoice-specific), re-execute the original intent
    if pending.get("type") == "security_auth":
        # Clear the OTP state
        await set_session(session_id, {"otp_verified": True, "verified_at": "now"})
        return "✅ Identity verified! Session active for 4h. Please resend your request."

    # For invoice OTP (legacy)
    if pending.get("intent") == "create_invoice":
        amount    = pending["amount"]
        org_id    = user["org_id"]
        user_id   = user["user_id"]
        phone     = pending.get("phone", user["phone"])
        customer  = pending["customer_name"]
        item_name = pending.get("item_name")
        qty       = pending.get("qty")

        # Fetch thresholds from DB
        _, approval_threshold = await _get_invoice_thresholds(org_id)

        # Check approval gate after OTP
        if amount >= approval_threshold and user["role"] != "owner":
            sent = await _send_approval_request(
                user=user,
                customer_name=customer,
                amount=amount,
                qty=qty,
                item_name=item_name,
                raw_text=pending.get("raw_text", ""),
                session_id=session_id
            )
            if sent:
                await _log(org_id, user_id, "create_invoice",
                           pending.get("raw_text", ""), "pending_approval", otp_used=True)
                return (
                    f"✅ Identity verified!\n\n"
                    f"Invoice for *{customer}* — Rs.{amount:,.0f} requires MD approval.\n"
                    f"Approval request sent to Owner. You'll be notified once approved."
                )

        result = await accounting.create_invoice(
            org_id=org_id,
            user_id=user_id,
            customer_name=customer,
            amount=amount,
            phone=phone,
            item_name=item_name,
            qty=qty
        )
        await _log(org_id, user_id, "create_invoice",
                   pending.get("raw_text", ""), "success", otp_used=True)
        # Clear otp_verified so next transaction needs fresh OTP
        await set_session(session_id, {})
        return result["message"]

    return "✅ Verified! Please resend your original request."


async def _send_approval_request(
    user, customer_name, amount, qty, item_name, raw_text, session_id
) -> bool:
    """Send WhatsApp approval buttons to Owner."""
    org_id = user["org_id"]

    owner = await fetch_one("""
        SELECT u.phone, u.name FROM users u
        JOIN roles r ON r.id = u.role_id
        WHERE u.org_id = $1 AND r.name = 'owner'
        AND u.is_active = true AND u.phone IS NOT NULL
        LIMIT 1
    """, org_id)

    if not owner:
        return False

    context = {
        "intent": "create_invoice",
        "customer_name": customer_name,
        "amount": amount,
        "qty": qty,
        "item_name": item_name,
        "raw_text": raw_text,
        "requester_id": user["user_id"],
        "requester_phone": user["phone"],
        "requester_name": user["user_name"],
        "session_id": session_id
    }

    await execute("""
        INSERT INTO pending_approvals
        (org_id, requester_id, approver_role, intent_key, context, status)
        VALUES ($1, $2, 'owner', 'create_invoice', $3::jsonb, 'pending')
    """, org_id, user["user_id"], json.dumps(context))

    item_line = f"\nItems: {qty} × {item_name}" if item_name and qty else ""

    await send_buttons(
        to=owner["phone"],
        body=(
            f"📋 *Invoice Approval Request*\n\n"
            f"From: {user['user_name']} ({user['role']})\n"
            f"Customer: {customer_name}\n"
            f"Amount: Rs.{amount:,.0f}"
            f"{item_line}\n\n"
            f"Please approve or reject:"
        ),
        buttons=[
            {"id": "action:approve", "title": "✅ Approve"},
            {"id": "action:reject",  "title": "❌ Reject"}
        ]
    )
    return True


async def handle_approval_response(phone: str, action: str, user: dict):
    """Called when Owner taps Approve/Reject button."""
    org_id = user["org_id"]

    approval = await fetch_one("""
        SELECT id, requester_id, context
        FROM pending_approvals
        WHERE org_id = $1 AND status = 'pending'
        ORDER BY created_at DESC LIMIT 1
    """, org_id)

    if not approval:
        await send_text(phone, "No pending approvals found.")
        return

    ctx = approval["context"]
    if isinstance(ctx, str):
        ctx = json.loads(ctx)

    await execute("""
        UPDATE pending_approvals
        SET status = $1, decided_by = $2, decided_at = NOW()
        WHERE id = $3
    """, "approved" if action == "action:approve" else "rejected",
        user["user_id"], approval["id"])

    if action == "action:reject":
        await send_text(phone, f"❌ Invoice rejected.")
        await send_text(
            ctx["requester_phone"],
            f"❌ Your invoice request for *{ctx['customer_name']}* "
            f"— Rs.{ctx['amount']:,.0f} was *rejected* by {user['user_name']}."
        )
        return

    # Approved — create invoice
    result = await accounting.create_invoice(
        org_id=org_id,
        user_id=ctx["requester_id"],
        customer_name=ctx["customer_name"],
        amount=ctx["amount"],
        phone=ctx["requester_phone"],
        item_name=ctx.get("item_name"),
        qty=ctx.get("qty")
    )

    await send_text(phone, f"✅ Approved.\n\n{result['message']}")
    await send_text(
        ctx["requester_phone"],
        f"✅ Your invoice was *approved* by {user['user_name']}.\n\n{result['message']}"
    )


async def _log(org_id, user_id, intent, text, outcome, otp_used=False):
    await execute("""
        INSERT INTO audit_log
        (org_id, user_id, intent_key, input_text, outcome, otp_used)
        VALUES ($1, $2, $3, $4, $5, $6)
    """, org_id, user_id, intent, text, outcome, otp_used)
