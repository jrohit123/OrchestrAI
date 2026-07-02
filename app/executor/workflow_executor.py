"""
workflow_executor.py — Minimal live functions still used by webhook.py.

resume_after_otp     — called after security OTP verification
handle_approval_response — called when owner taps Approve/Reject button

Everything else that was here has been removed:
  - execute_intent        → replaced by run_agent (agent.py)
  - _get_invoice_thresholds → read from workflows table in step_interpreter
  - _parse_schedule       → replaced by manage_schedule tool in agent.py
  - _send_approval_request → now done inside step_interpreter._op_approval_gate
  - accounting.create_invoice calls → replaced by execute_pending_action
  - _log                  → done in webhook.py directly
"""
import json
from app.db import fetch_one, execute
from app.services.whatsapp import send_text, send_buttons
from app.redis_client import set_session


async def resume_after_otp(user: dict, session_id: str, session: dict) -> str:
    """
    Called after security session OTP is verified.
    The actual pending_action OTP path is handled in webhook.py directly
    via execute_pending_action(otp_verified=True) — this function only
    handles the legacy security_auth OTP path.
    """
    pending = session.get("pending_intent")

    if pending and pending.get("type") == "security_auth":
        await set_session(session_id, {"otp_verified": True})
        return "✅ Identity verified! Session active for 4h. Please resend your request."

    # Fallback for any other legacy pending_intent shapes
    return "✅ Verified! Please resend your original request."


async def handle_approval_response(phone: str, action: str, user: dict):
    """
    Called when an owner taps Approve or Reject on a pending_approvals button.
    Resumes execution via execute_pending_action(approved=True).
    """
    from app.services.action_executor import execute_pending_action

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

    # Mark as decided
    await execute("""
        UPDATE pending_approvals
        SET status = $1, decided_by = $2, decided_at = NOW()
        WHERE id = $3
    """,
        "approved" if action == "action:approve" else "rejected",
        user["user_id"],
        approval["id"]
    )

    requester_phone = ctx.get("requester_phone", "")
    requester_name  = ctx.get("requester_name", "Your colleague")

    if action == "action:reject":
        await send_text(phone, "❌ Action rejected.")
        if requester_phone:
            await send_text(
                requester_phone,
                f"❌ Your request was *rejected* by {user['user_name']}."
            )
        return

    # Approved — resume execution from where it halted
    pending_action = ctx.get("pending_action")
    if not pending_action:
        await send_text(phone, "✅ Approved, but no pending action found to execute.")
        return

    result = await execute_pending_action(
        pending_action=pending_action,
        user={
            "user_id":    ctx.get("requester_id", user["user_id"]),
            "org_id":     org_id,
            "user_name":  requester_name,
            "org_name":   user.get("org_name", ""),
            "email":      ctx.get("requester_email", ""),
            "role":       "owner",
            "role_id":    user.get("role_id", ""),
            "permissions": [],
            "phone":      requester_phone,
            "is_active":  True,
            "org_active": True,
        },
        phone=requester_phone,
        approved=True,
    )

    if result.get("success"):
        await send_text(phone, f"✅ Approved.\n\n{result['message']}")
        if requester_phone:
            await send_text(
                requester_phone,
                f"✅ Your request was *approved* by {user['user_name']}.\n\n{result['message']}"
            )
    else:
        await send_text(phone, f"✅ Approved but execution failed: {result.get('message', '?')}")
