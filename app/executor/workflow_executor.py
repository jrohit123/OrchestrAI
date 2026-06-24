import json
import re
from app.adapters import inventory, crm, accounting
from app.services.otp_service import generate_and_send_otp
from app.services.whatsapp import send_text, send_buttons
from app.redis_client import set_session, clear_all_sessions
from app.db import fetch_one, execute
from app.scheduler.jobs import reschedule_dues_report, stop_dues_report, get_job_schedule


async def _dispatch_dynamic_intent(intent: str, entity: str | None, org_id: str, raw_text: str, adapter_method: str) -> str:
    """
    Generic dispatcher for DB-registered workflows that have no hardcoded handler.
    Dynamically calls the adapter method specified in the workflow config.
    """
    if not entity and adapter_method not in ["get_all_overdue"]:
        return "🤔 Which customer or product? Please specify."

    # Map adapter methods to actual adapter functions
    adapter_map = {
        "get_credit_limit": crm.get_credit_limit,
        "get_outstanding": crm.get_outstanding,
        "check_stock": inventory.check_stock,
        "get_all_overdue": crm.get_all_overdue,
    }

    if adapter_method == "generic":
        return (
            f"⚙️ Workflow *{intent.replace('_', ' ').title()}* was recognised "
            f"but has no adapter method configured. Contact your admin."
        )

    if adapter_method not in adapter_map:
        return f"⚙️ Unknown adapter method: {adapter_method}. Contact admin."

    try:
        adapter_func = adapter_map[adapter_method]
        
        # Call the adapter with appropriate arguments
        if adapter_method == "get_all_overdue":
            result = await adapter_func(org_id)
        else:
            result = await adapter_func(org_id, entity)
        
        return result["message"]
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
    raw_text: str
) -> str:
    org_id  = user["org_id"]
    user_id = user["user_id"]
    phone   = user["phone"]

    # ── CHECK STOCK ───────────────────────────────────
    if intent == "check_stock":
        if not entity_raw:
            return "🤔 Which product? Try: *stock gold ring*"
        result = await inventory.check_stock(org_id, entity_raw)
        await _log(org_id, user_id, intent, raw_text, "success")
        return result["message"]

    # ── CHECK OUTSTANDING ─────────────────────────────
    if intent == "check_outstanding":
        if not entity_raw:
            return "🤔 Which customer? Try: *dues Mehta*"
        result = await crm.get_outstanding(org_id, entity_raw)
        await _log(org_id, user_id, intent, raw_text, "success")
        return result["message"]

    # ── WEEKLY DUES REPORT ────────────────────────────
    if intent == "weekly_dues_report":
        limit = None
        lm = re.search(r"top\s+(\d+)", raw_text.lower())
        if lm:
            limit = int(lm.group(1))
        result_data = await crm.get_all_overdue(org_id, limit=limit)
        await _log(org_id, user_id, intent, raw_text, "success")
        return result_data["message"]

    # ── MANAGE SCHEDULE ───────────────────────────────
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

    # ── CLEAR ALL SESSIONS ────────────────────────────────
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

    # ── CREATE INVOICE ────────────────────────────────
    if intent == "create_invoice":
        details = accounting.parse_invoice_details(raw_text)

        customer_name = details.get("customer") or entity_raw
        amount        = details.get("amount")
        qty           = details.get("qty")
        item_name     = details.get("item")

        if not customer_name:
            return "🤔 Which customer? Try: *invoice Mehta 120000*"
        if not amount:
            return "🤔 What amount? Try: *invoice Mehta 120000*\nWith items: *invoice Mehta 15 gold rings 120000*"

        # Stock check if item specified
        if item_name and qty:
            stock = await inventory.check_stock_availability(org_id, item_name, qty)
            if not stock["available"]:
                return stock["message"]

        # Fetch thresholds from DB
        otp_threshold, approval_threshold = await _get_invoice_thresholds(org_id)

        # OTP gate
        if amount >= otp_threshold and not session.get("otp_verified"):
            action_context = {
                "intent": "create_invoice",
                "customer_name": customer_name,
                "amount": amount,
                "qty": qty,
                "item_name": item_name,
                "raw_text": raw_text,
                "phone": phone,
                "description": f"create invoice for {customer_name} — Rs.{amount:,.0f}"
                + (f" ({qty} × {item_name})" if item_name and qty else "")
            }
            sent = await generate_and_send_otp(
                user_id=user_id,
                user_email=user["email"],
                user_name=user["user_name"],
                org_name=user["org_name"],
                action_context=action_context
            )
            if sent:
                await set_session(session_id, {
                    **session,
                    "state": "awaiting_otp",
                    "pending_intent": action_context
                })
                return (
                    f"🔐 *Verification Required*\n\n"
                    f"Invoice for *{customer_name}* — Rs.{amount:,.0f}"
                    + (f"\n{qty} × {item_name}" if item_name and qty else "")
                    + f"\n\nA 4-digit code was sent to *{user['email']}*.\n"
                    f"Reply with the code to confirm.\n\n"
                    f"_Expires in 3 minutes. Reply 'retry' to cancel._"
                )
            else:
                return "❌ Could not send verification email. Contact admin."

        # Approval gate (after OTP or for below-threshold)
        if amount >= approval_threshold and user["role"] != "owner":
            sent = await _send_approval_request(
                user=user,
                customer_name=customer_name,
                amount=amount,
                qty=qty,
                item_name=item_name,
                raw_text=raw_text,
                session_id=session_id
            )
            if sent:
                await _log(org_id, user_id, intent, raw_text, "pending_approval",
                           otp_used=session.get("otp_verified", False))
                return (
                    f"✅ Identity verified!\n\n"
                    f"Invoice for *{customer_name}* — Rs.{amount:,.0f} requires MD approval.\n"
                    f"Approval request sent. You'll be notified once approved."
                )
            else:
                return "❌ Could not find owner to send approval. Contact admin."

        # Create invoice directly
        result = await accounting.create_invoice(
            org_id=org_id,
            user_id=user_id,
            customer_name=customer_name,
            amount=amount,
            phone=phone,
            item_name=item_name,
            qty=qty
        )
        await _log(org_id, user_id, intent, raw_text,
                   "success" if result["success"] else "failed",
                   otp_used=session.get("otp_verified", False))
        # Clear otp_verified so next transaction needs fresh OTP
        await set_session(session_id, {})
        return result["message"]

    # ── DYNAMIC DB WORKFLOW ───────────────────────────
    # For any DB-registered intent with no hardcoded handler above
    db_workflow = await fetch_one("""
        SELECT name, adapter_method FROM workflows
        WHERE intent_key = $1 AND org_id = $2 AND is_active = true
    """, intent, org_id)

    if db_workflow:
        adapter_method = db_workflow.get("adapter_method", "generic")
        result_msg = await _dispatch_dynamic_intent(intent, entity_raw, org_id, raw_text, adapter_method)
        await _log(org_id, user_id, intent, raw_text, "success")
        return result_msg

    return "🤔 Didn't understand that. Type *help* for the menu."


async def resume_after_otp(user: dict, session_id: str, session: dict) -> str:
    """Called after OTP verified — resumes the pending intent."""
    pending = session.get("pending_intent")
    if not pending:
        return "✅ Verified! Please resend your original request."

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
