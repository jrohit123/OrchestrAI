from app.adapters import inventory, crm, accounting
from app.services.otp_service import generate_and_send_otp
from app.redis_client import set_session
from app.db import execute


OTP_THRESHOLD = 50000.0  # invoices above this require OTP


async def execute_intent(
    intent: str,
    entity_raw: str | None,
    user: dict,
    session_id: str,
    session: dict,
    raw_text: str
) -> str:
    """
    Routes classified intent to the correct adapter.
    Returns a formatted string ready to send as WhatsApp message.
    """
    org_id  = user["org_id"]
    user_id = user["user_id"]
    phone   = user["phone"]

    # ── CHECK STOCK ───────────────────────────────────
    if intent == "check_stock":
        if not entity_raw:
            return "🤔 Which product? Try: *stock gold ring* or *stock bangle*"
        result = await inventory.check_stock(org_id, entity_raw)
        await _log(org_id, user_id, intent, raw_text, "success")
        return result["message"]

    # ── CHECK OUTSTANDING ─────────────────────────────
    if intent == "check_outstanding":
        if not entity_raw:
            return "🤔 Which customer? Try: *dues Mehta* or *outstanding Sharma*"
        result = await crm.get_outstanding(org_id, entity_raw)
        await _log(org_id, user_id, intent, raw_text, "success")
        return result["message"]

    # ── WEEKLY DUES REPORT ────────────────────────────
    if intent == "weekly_dues_report":
        result = await crm.get_all_overdue(org_id)
        await _log(org_id, user_id, intent, raw_text, "success")
        return result["message"]

    # ── CREATE INVOICE (with OTP gate) ────────────────
    if intent == "create_invoice":
        amount = accounting.parse_amount_from_text(raw_text)
        customer_name = entity_raw

        if not customer_name:
            return "🤔 Which customer? Try: *invoice Mehta ₹50000*"
        if not amount:
            return "🤔 What amount? Try: *invoice Mehta ₹50000*"

        # OTP gate
        if amount >= OTP_THRESHOLD and not session.get("otp_verified"):
            action_context = {
                "intent": "create_invoice",
                "customer_name": customer_name,
                "amount": amount,
                "raw_text": raw_text,
                "phone": phone,
                "description": f"create an invoice for {customer_name} — ₹{amount:,.0f}"
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
                    f"Invoice for *{customer_name}* — ₹{amount:,.0f} requires approval.\n\n"
                    f"A 4-digit code has been sent to *{user['email']}*.\n"
                    f"Reply with the code to confirm.\n\n"
                    f"_Code expires in 3 minutes. Reply 'retry' to cancel._"
                )
            else:
                return "❌ Could not send verification email. Contact admin."

        # Create invoice
        result = await accounting.create_invoice(
            org_id=org_id,
            user_id=user_id,
            customer_name=customer_name,
            amount=amount,
            phone=phone
        )
        await _log(org_id, user_id, intent, raw_text,
                   "success" if result["success"] else "failed",
                   otp_used=session.get("otp_verified", False))
        return result["message"]

    return "🤔 I didn't understand that. Type *help* for the menu."


async def resume_after_otp(user: dict, session_id: str, session: dict) -> str:
    """Called after OTP verified — resumes pending intent."""
    pending = session.get("pending_intent")
    if not pending:
        return "✅ Verified! Please resend your original request."

    if pending.get("intent") == "create_invoice":
        result = await accounting.create_invoice(
            org_id=user["org_id"],
            user_id=user["user_id"],
            customer_name=pending["customer_name"],
            amount=pending["amount"],
            phone=pending.get("phone", user["phone"])
        )
        await _log(
            user["org_id"], user["user_id"],
            "create_invoice", pending["raw_text"], "success", otp_used=True
        )
        return result["message"]

    return "✅ Verified! Please resend your original request."


async def _log(org_id, user_id, intent, text, outcome, otp_used=False):
    await execute("""
        INSERT INTO audit_log (org_id, user_id, intent_key, input_text, outcome, otp_used)
        VALUES ($1, $2, $3, $4, $5, $6)
    """, org_id, user_id, intent, text, outcome, otp_used)
