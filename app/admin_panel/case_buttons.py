"""Case buttons: the panel asks the organisation's own flow to do the work.

For now there is one button, "assign". Which flow it runs is a setting of the organisation
(orgs.settings.case_buttons.assign = the flow's key, for example "case_pass_on", which Godrej calls
"Assign a case"), so this code holds
no rule about what assigning means: what is written on the case, who is told and what follows are
all in that flow, and switching the flow off switches the button off.

The flow runs as the signed-in person's own record in this organisation (found by email), so the
case timeline shows a real name and the flow's messages go out as they do from the chat bot."""

from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.admin_panel.acting import chat_user
from app.admin_panel.common import Ctx, CtxDep, PanelRoute, log_event
from app.db import fetch_one
from app.logging_config import get_context_logger

logger = get_context_logger(__name__)

router = APIRouter(
    prefix="/admin/{org_slug}/api/v2", tags=["admin-panel"], route_class=PanelRoute
)


async def assign_flow(ctx: Ctx) -> dict | None:
    """The case action this organisation chose for "assign", or None when it chose none."""
    key = (ctx.settings.get("case_buttons") or {}).get("assign")
    if not key or not isinstance(key, str):
        return None
    if not (ctx.caps.get("cases") and ctx.caps.get("workflow_kind")):
        return None
    row = await fetch_one(
        "SELECT * FROM workflows WHERE org_id = $1 AND intent_key = $2 "
        "AND kind IN ('workflow', 'case_action')",
        ctx.org_id,
        key,
        source_key=ctx.source_key,
    )
    return dict(row) if row else None


async def assign_state(ctx: Ctx) -> dict | None:
    """What the page needs: None (no assign button here) or the flow's name and whether it is on."""
    flow = await assign_flow(ctx)
    if flow is None:
        return None
    return {"name": flow["name"], "on": bool(flow["is_active"])}


class AssignBody(BaseModel):
    user_id: UUID
    note: str | None = Field(None, max_length=500)


@router.post("/cases/{case_id}/assign")
async def assign_case(case_id: UUID, body: AssignBody, ctx: CtxDep):
    """Give a case to a person by running the organisation's assign flow."""
    ctx.need("cases")
    flow = await assign_flow(ctx)
    if flow is None:
        raise HTTPException(
            status_code=409,
            detail="Assigning from the dashboard is not set up for this organisation.",
        )
    if not flow["is_active"]:
        raise HTTPException(
            status_code=409,
            detail=f"The “{flow['name']}” flow is switched off, so cases cannot be assigned here. "
            "A super admin can switch it on under Flows.",
        )
    case = await fetch_one(
        "SELECT c.id, c.case_number, c.assigned_to_id, au.name AS assignee_name "
        "FROM cases c LEFT JOIN users au ON au.id = c.assigned_to_id "
        "WHERE c.org_id = $1 AND c.id = $2",
        ctx.org_id,
        case_id,
        source_key=ctx.source_key,
    )
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    person = await fetch_one(
        "SELECT id, name, is_active FROM users WHERE org_id = $1 AND id = $2",
        ctx.org_id,
        body.user_id,
        source_key=ctx.source_key,
    )
    if person is None:
        raise HTTPException(status_code=404, detail="That person was not found.")
    if not person["is_active"]:
        raise HTTPException(
            status_code=409,
            detail=f"{person['name']} is switched off, so cannot get a case.",
        )
    if case["assigned_to_id"] == person["id"]:
        raise HTTPException(
            status_code=409,
            detail=f"{case['case_number']} is with {person['name']} already.",
        )
    actor = await chat_user(ctx, email=ctx.account_email, party=False)
    if actor is None:
        raise HTTPException(
            status_code=409,
            detail="To assign cases here, your email must also belong to a person in this "
            "organisation (under People), and that person needs a role. Yours is not there yet.",
        )

    from app.services.step_interpreter import run_workflow_steps

    fields = {"case_number": case["case_number"], "assignee_name": person["name"]}
    if body.note and body.note.strip():
        fields["comment_text"] = body.note.strip()
    try:
        result = await run_workflow_steps(flow, fields, actor, actor["phone"] or "")
    except (
        Exception
    ) as e:  # the engine reports problems in its result; this is the unexpected
        logger.error(f"assign flow crashed: {e!r}")
        raise HTTPException(
            status_code=502,
            detail="It could not be done just now. Nothing was changed.",
        ) from None
    status = result.get("status")
    if status == "ambiguous":
        raise HTTPException(
            status_code=409,
            detail=f"More than one person is called {person['name']}. Ask a super admin to "
            "give them different names.",
        )
    if status != "done":
        raise HTTPException(
            status_code=409,
            detail=result.get("message") or "The flow stopped before it finished.",
        )
    await log_event(
        ctx,
        "cases",
        "assign",
        f"Gave {case['case_number']} to {person['name']}",
        target_type="case",
        target_id=case_id,
        before={"assigned_to": case["assignee_name"]},
        after={"assigned_to": person["name"], "flow": flow["intent_key"]},
    )
    return {
        "ok": True,
        "message": f"{case['case_number']} is now with {person['name']}.",
        "case_id": str(case_id),
        "assigned_to_id": str(person["id"]),
        "assignee_name": person["name"],
    }
