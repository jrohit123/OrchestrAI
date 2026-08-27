"""
action_executor.py — v2. Thin wrapper over step_interpreter.

NO intent_key branching. NO per-workflow Python functions. Ever.
All execution logic lives in workflows.steps[] in the database.
Adding a new workflow requires zero changes to this file.
"""
from app.db import fetch_one
from app.services.step_interpreter import run_workflow_steps
from app.services.draft_store import close_draft


async def execute_pending_action(
    pending_action: dict,
    user: dict,
    phone: str = None,
    otp_verified: bool = False,
    approved: bool = False,
) -> dict:
    """
    Execute a confirmed pending action.

    Returns:
        {
            "success": bool,
            "message": str,
            "pdf_bytes": bytes | None,
            "stage": str | None,         — set on gate halts
            "resume_step": int | None,   — step to resume from after gate
            + any generated doc numbers (invoice_number, quotation_number, etc.)
        }
    """
    intent_key = pending_action.get("intent_key")
    if not intent_key:
        logger.error(f"pending_action has no intent_key: {pending_action!r}")
        return {
            "success": False,
            "message": (
                "I lost track of what we were working on. Please send your "
                "request again — for example *\"assign CS-26-08-17 to Anuja\"*."
            ),
        }

    workflow = await fetch_one(
        "SELECT * FROM workflows WHERE intent_key = $1 AND org_id = $2 AND is_active = true",
        intent_key, user["org_id"], source_key=user["source_key"]
    )

    # D4: Permission check at execution time — any role can run any workflow without this
    perms = set(user.get("permissions") or [])
    if intent_key not in perms:
        logger.warning(
            f"Permission denied: user={user.get('user_id')} "
            f"role={user.get('role')} intent={intent_key}"
        )
        return {
            "success": False,
            "message": (
                "You don't have permission to do that. "
                "Please ask a committee member or admin."
            ),
        }
    if not workflow:
        return {
            "success": False,
            "message": (
                f"❌ Workflow '{intent_key}' not found or inactive.\n"
                f"Ask your admin to configure this workflow in the admin panel."
            )
        }

    result = await run_workflow_steps(
        workflow=dict(workflow),
        fields=pending_action.get("fields", {}),
        user=user,
        phone=phone or user.get("phone", ""),
        resume_step=pending_action.get("resume_step", 0),
        otp_verified=otp_verified,
        approved=approved,
    )

    if result["status"] == "done":
        # Clear the draft after successful execution
        await close_draft(user["org_id"], user.get("user_id") or user.get("id"), "done", source_key=user["source_key"])
        return {
            "success":   True,
            "message":   result["message"],
            "pdf_bytes": result.get("pdf_bytes"),
            # Expose any generated doc numbers at the top level for webhook
            **{k: v for k, v in result.get("generated", {}).items()},
        }

    if result["status"] in ("awaiting_otp", "awaiting_approval"):
        return {
            "success":     False,
            "stage":       result["status"],
            "resume_step": result.get("resume_step", 0),
            "message":     result.get("message", ""),
        }

    if result["status"] == "ambiguous":
        candidates = result.get("candidates", [])
        opts = "\n".join(
            f"{i+1}. {c.get('case_number') or c.get('name') or '?'}"
            + (f" — {c['title']}" if c.get("title") else "")
            for i, c in enumerate(candidates[:5])
        )
        return {
            "success": False,
            "message": f"🤔 I found more than one match:\n{opts}\n\n"
                       f"Which one did you mean? Reply with the full number.",
        }

    # status == "error" - close draft and show friendly message
    await close_draft(user["org_id"], user.get("user_id") or user.get("id"), "cancelled", source_key=user["source_key"])
    return {
        "success": False,
        "message": (
            "❌ I couldn't save that — something went wrong on my end while writing to "
            "the database. Please send your request again as a new message."
        ),
    }
