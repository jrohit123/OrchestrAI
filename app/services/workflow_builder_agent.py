"""
workflow_builder_agent.py — Conversational agent for building workflows via admin panel chat.

Everything about a workflow — purpose, fields, constraints, who can use it, and its
trigger command — is captured by talking, never through a settings form. Asks one
question at a time, builds a structured draft, compiles it, shows a plain-English
summary, and publishes only after an explicit confirm click (never something the
LLM can trigger on its own — see run_builder_agent's "ready_for_publish" vs
"published" distinction).

Chat history is stored server-side in workflow_drafts.chat_history — never round-tripped
through the browser. A deterministic "draft recap" (build_draft_recap, below) is
returned on every turn so the frontend's live "Draft so far" panel reflects what's
actually saved, not what the LLM claims it saved.
"""
import json
import os
import base64
from app.db import fetch_all, fetch_one, execute
from app.services.workflow_compiler import compile_workflow_spec
from app.services.llm_router import chat_completion as _llm_chat

from app.config import required

_SYSTEM_PROMPT = """You are helping a non-technical business owner describe a business process
so it becomes a working WhatsApp workflow. They think in plain terms — not schemas, not JSON, not code.
Never show them any technical details.

EXTRACTION-FIRST RULE (highest priority):
Before replying, extract EVERYTHING from the user's message: purpose,
workflow type, use cases, fields, rules, thresholds, roles, trigger command —
whatever is present. Save all of it via the right tool call in ONE turn. Then
your reply must:
1. Restate the FULL current state of the draft so far — not just what changed
   this message — in plain terms, so a message read on its own still makes
   sense (the admin may only glance at the latest reply, not scroll back).
2. Ask ONLY about what is genuinely still unknown — never anything
   already stated or already in the draft
Asking about something the user already told you is the worst failure
mode of this system.

PROPOSE, DON'T INTERROGATE:
When a detail is missing but has an obvious sensible default, propose it
and ask for confirmation instead of asking open-ended questions.
"Should low stock use each item's own reorder level? (that's what I'd
suggest)" beats "how should low stock be defined?"

SILENT STATE CHECKS:
Check for existing drafts silently. Mention a draft ONLY if one exists.
Never say "we don't have any drafts/workflows" — the user doesn't care
about your internal lookups.

LANGUAGE MIRRORING:
Reply in the user's language mix. Hinglish in → Hinglish out. Numbers:
understand 50k = 50,000, 2L / 2 lakh = 2,00,000.

READ-WORKFLOW SHORTCUT:
If the workflow is clearly read-only, don't ask about OTP, approval, or
any other constraint — state "no safety checks needed since this only
shows data" in the summary and move on. Only ask about constraints for
action workflows.

Ask ONE question at a time. After each answer, briefly restate what you understood, then ask the next
most useful question. Cover these topics (skip what's already answered or not relevant):

1. What does this do — what will people type or ask to trigger it?
   Does it CREATE/CHANGE something (action) or just SHOW information (read)?
2. What information needs to be collected or looked up?
3. Should anything be CALCULATED automatically? (tax, total, discount)
   Get the business rule in plain terms: "GST is 3% of item value" is enough.
4. Any safety rules — verification code, someone's approval above a certain amount,
   multi-level sign-off, or a rule that only certain roles can even trigger this?
   Constraints are NOT limited to "OTP above X" and "approval above Y" — the admin
   might describe several independent rules, multi-level chains ("branch manager
   first, then owner above 20L"), non-amount conditions ("anything touching the
   lift needs the secretary, regardless of amount"), or role-only gates ("only
   Finance can do this"). Capture EXACTLY what they describe as one or more
   entries in gates[] via set_gates — never force it into just two numbers.
   THE MOMENT the admin gives a number or names an approver, call set_gates with
   the FULL current list of constraints (existing ones + the new/changed one) —
   convert "1 lakh" to 100000, "50k" to 50000, "20L"/"20 lakh" to 2000000 yourself.
   Then confirm back in plain terms: "Got it — OTP above Rs.50,000. Above Rs.5,00,000
   the branch manager approves; above Rs.20,00,000 the owner also approves after
   them." so they can correct you immediately if you misheard.
   A level's role must be a role that exists in this org — if unsure, call
   list_existing_workflows or just ask the admin what roles they have.
   NOTE: Do NOT proactively ask about constraints on a workflow the admin hasn't
   indicated needs any. Only capture them if the admin volunteers them.
5. Does this produce a document? If yes, ask:
   "Do you have a sample PDF you already send? Attach it and I'll match the look."
   If no PDF attached, ask what the document should show.
6. Who should be able to use this — which roles? THE MOMENT the admin names one
   or more roles, call set_roles with the FULL list of roles that should have
   access (existing ones + new). If they say "anyone"/"all staff", still resolve
   that to real role names via list_existing_workflows if you're unsure what
   roles this org has, rather than guessing a name that doesn't exist.
7. Before publishing, ask: "What short command should trigger this? I suggest /stock"
   (derive suggestion from the name; lowercase, no spaces, ≤32 chars). Save via
   update_builder_draft as slash_command. Set menu_section yourself: 'reports' if
   workflow_type is read, 'create' if action. Also write a one-line
   command_description (≤72 chars) for the menu.

IMPORTANT: If a message in the conversation contains "[Admin uploaded a sample PDF" — that means
the PDF has already been analyzed and saved. Do NOT ask the admin to upload again.
When asked about the document format, confirm you'll use the uploaded sample's layout.

Once you have enough information — including who can use it and the trigger command,
both gathered via chat like everything else — call compile_and_summarize.
Show the summary in plain English and ask if it's correct.
If they want changes, call revise_draft, then show the new summary.
Only call mark_ready_for_review after an explicit "yes" on a summary you've already
shown AND roles + slash_command are both set. The admin then sees everything you've
gathered in one place and hits a single Publish button — that's the only thing that
actually writes to the live workflow; you never trigger that yourself.

If the first message is vague ("help me" / "I want a workflow"), call list_existing_workflows
first, mention what already exists including unfinished drafts, and ask what to add or change.

If the admin wants to MODIFY something that already exists, call list_existing_workflows to find
its intent_key if needed, then call load_existing_workflow before asking what to change.
The normal flow (update_builder_draft, set_gates, set_roles, compile_and_summarize) works
identically whether the draft started fresh or was loaded from an existing workflow — when
loaded, restate the FULL current state (including its existing constraints and roles) before
asking what to change, since the admin may not remember everything that's already configured."""

_TOOLS = [
    {"type": "function", "function": {
        "name": "list_existing_workflows",
        "description": "List this org's live workflows, its roles, and any unfinished drafts.",
        "parameters": {"type": "object", "properties": {}}
    }},
    {"type": "function", "function": {
        "name": "update_builder_draft",
        "description": "Save what's been learned so far about the workflow being built.",
        "parameters": {"type": "object", "properties": {
            "purpose":       {"type": "string", "description": "What this workflow does in plain terms"},
            "workflow_type": {"type": "string", "enum": ["action", "read"]},
            "raw_fields":    {"type": "array", "items": {"type": "string"},
                              "description": "Fields to collect, e.g. ['customer name', 'item description', 'GST — auto']"},
            "business_rules": {"type": "string", "description": "Any OTHER rule not covered by set_gates (calculations, formatting, etc.)."},
            "slash_command": {
                "type": "string",
                "description": "Short command to trigger this workflow (e.g., 'stock', 'quote'). Lowercase, no spaces, ≤32 chars. Include the / prefix."
            },
            "command_description": {
                "type": "string",
                "description": "One-line description for the menu (≤72 chars)."
            },
            "menu_section": {
                "type": "string",
                "enum": ["reports", "create", "other"],
                "description": "Menu section: 'reports' for read workflows, 'create' for action workflows."
            },
        }}
    }},
    {"type": "function", "function": {
        "name": "set_gates",
        "description": (
            "Set the COMPLETE list of safety/approval constraints for this workflow, "
            "replacing whatever was there before. Call this every time the admin adds, "
            "changes, or removes a constraint — always pass the full list that should "
            "apply going forward, not just the one that changed. Not limited to two "
            "numbers: a workflow can have zero, one, or several independent constraints "
            "of different kinds (OTP, single- or multi-level approval, role-only gates)."
        ),
        "parameters": {"type": "object", "properties": {
            "gates": {
                "type": "array",
                "description": "Every constraint that should apply. Convert lakh/crore/k to plain numbers.",
                "items": {
                    "type": "object",
                    "properties": {
                        "id":   {"type": "string", "description": "short stable id, e.g. 'otp1', 'appr1', 'appr_lift'"},
                        "type": {"type": "string", "enum": ["otp", "approval_chain", "permission"]},
                        "when": {
                            "type": "object",
                            "description": (
                                "Condition that triggers this gate. Amount-based: "
                                "{\"field\":\"$computed.total_amount\",\"gte\":50000}. "
                                "Non-amount field: {\"field\":\"$fields.category\",\"equals\":\"lift_elevator\"}. "
                                "Omit only for a 'permission' gate that always applies."
                            ),
                        },
                        "levels": {
                            "type": "array",
                            "description": (
                                "Required for type='approval_chain'. Ordered stages — level 1 is always "
                                "required once 'when' matches; level 2+ is only required once the amount "
                                "exceeds the PREVIOUS level's max_amount (i.e. max_amount is the ceiling "
                                "that role can clear alone; null = no ceiling, final level)."
                            ),
                            "items": {
                                "type": "object",
                                "properties": {
                                    "level":      {"type": "integer"},
                                    "role":       {"type": "string", "description": "role name required to approve at this level"},
                                    "max_amount": {"type": ["number", "null"]},
                                }
                            }
                        },
                        "role_any_of": {
                            "type": "array", "items": {"type": "string"},
                            "description": "Required only for type='permission' — the only role(s) allowed to trigger this workflow at all, regardless of amount."
                        }
                    }
                }
            }
        }, "required": ["gates"]}
    }},
    {"type": "function", "function": {
        "name": "set_roles",
        "description": (
            "Set the COMPLETE list of roles allowed to use this workflow, replacing "
            "whatever was set before. Call this the moment the admin says who should "
            "be able to use it — always pass the full list, not just an addition."
        ),
        "parameters": {"type": "object", "properties": {
            "roles": {"type": "array", "items": {"type": "string"},
                      "description": "Role names as they exist in this org, e.g. ['staff', 'branch_manager']"}
        }, "required": ["roles"]}
    }},
    {"type": "function", "function": {
        "name": "analyze_sample_pdf",
        "description": "Analyze an uploaded PDF to extract layout instructions. Call when admin attaches a PDF.",
        "parameters": {"type": "object", "properties": {
            "doc_type_hint": {"type": "string"}
        }}
    }},
    {"type": "function", "function": {
        "name": "compile_and_summarize",
        "description": "Compile everything gathered into a real workflow spec and produce a plain-English summary.",
        "parameters": {"type": "object", "properties": {}}
    }},
    {"type": "function", "function": {
        "name": "revise_draft",
        "description": "Apply a change the admin asked for after seeing a summary, then recompile.",
        "parameters": {"type": "object", "properties": {
            "change_description": {"type": "string", "description": "What to change"}
        }, "required": ["change_description"]}
    }},
    {"type": "function", "function": {
        "name": "mark_ready_for_review",
        "description": (
            "Mark the draft as ready for review. The admin then sees everything gathered "
            "so far (fields, constraints, roles, command) and hits one Publish button — "
            "nothing left to fill in. Call ONLY after admin said yes to a summary AND "
            "roles and slash_command are both set."
        ),
        "parameters": {"type": "object", "properties": {}}
    }},
    {"type": "function", "function": {
        "name": "load_existing_workflow",
        "description": "Load a live workflow into the draft so the admin can change it by talking instead of editing JSON. Use when admin wants to modify something that already exists.",
        "parameters": {"type": "object", "properties": {
            "intent_key": {"type": "string", "description": "The intent_key of the workflow to load"}
        }, "required": ["intent_key"]}
    }},
]


def _parse_jsonb(val, default):
    """asyncpg returns jsonb columns as raw JSON text — see app/db.py, no codec registered."""
    if val is None:
        return default
    if isinstance(val, str):
        try:
            return json.loads(val)
        except (json.JSONDecodeError, TypeError):
            return default
    return val


def _describe_when(when: dict) -> str:
    if not when:
        return ""
    field = when.get("field", "") or ""
    is_amount = "total_amount" in field or "amount" in field
    if "gte" in when:
        return f"amount ≥ ₹{when['gte']:,.0f}" if is_amount else f"{field.split('.')[-1]} ≥ {when['gte']}"
    if "lte" in when:
        return f"amount ≤ ₹{when['lte']:,.0f}" if is_amount else f"{field.split('.')[-1]} ≤ {when['lte']}"
    if "equals" in when:
        return f"{field.split('.')[-1]} = {when['equals']}"
    if "not_equals" in when:
        return f"{field.split('.')[-1]} ≠ {when['not_equals']}"
    return ""


def _describe_gate(g: dict) -> str:
    if not isinstance(g, dict):
        return f"• {g}"
    gtype = g.get("type")
    when = g.get("when") or {}
    if gtype == "otp":
        amt = when.get("gte") if when.get("gte") is not None else when.get("lte")
        return f"\U0001f510 OTP required above ₹{amt:,.0f}" if amt is not None else "\U0001f510 OTP required"
    if gtype == "approval_chain":
        cond = _describe_when(when)
        lines = [f"\U0001f464 Approval — {cond}:" if cond else "\U0001f464 Approval:"]
        for lvl in (g.get("levels") or []):
            ceiling = f", up to ₹{lvl['max_amount']:,.0f}" if lvl.get("max_amount") is not None else " (no ceiling)"
            lines.append(f"   {lvl.get('level', '?')}. {lvl.get('role') or '(role not set)'}{ceiling}")
        return "\n".join(lines)
    if gtype == "permission":
        roles = ", ".join(g.get("role_any_of") or []) or "(no role set)"
        return f"\U0001f512 Only {roles} can use this"
    return f"• {gtype or 'unknown constraint'}"


def build_draft_recap(draft: dict) -> str:
    """
    Deterministic, server-rendered plain-English recap of a draft's CURRENT
    state — the "Draft so far" panel shown live next to the chat. Built from
    the actual draft row, never from what the LLM said in its reply, so it
    can't drift from what's really going to be saved. Same principle as
    workflow_validator.py: the thing the admin is trusted to read has to be
    generated by code, not trusted to an LLM's account of itself.
    """
    lines = []
    title = draft.get("name") or draft.get("purpose") or "(untitled)"
    lines.append(title)
    if draft.get("purpose") and draft.get("name"):
        lines.append(draft["purpose"])
    if draft.get("workflow_type"):
        lines.append(f"Type: {draft['workflow_type']}")

    raw_fields = _parse_jsonb(draft.get("raw_fields"), [])
    if raw_fields:
        lines.append("Fields: " + ", ".join(raw_fields))

    lines.append("")
    gates = _parse_jsonb(draft.get("gates"), [])
    if gates:
        lines.append("Constraints:")
        for g in gates:
            lines.append(_describe_gate(g))
    else:
        lines.append("Constraints: none")

    lines.append("")
    granted_roles = draft.get("granted_roles") or []
    lines.append("Who can use it: " + (", ".join(granted_roles) if granted_roles else "(not set yet)"))
    lines.append("Trigger command: " + (f"/{draft['slash_command']}" if draft.get("slash_command") else "(not set yet)"))

    return "\n".join(lines)


async def _get_or_create_draft(org_id: str, draft_id: str | None, source_key: str) -> dict:
    if draft_id:
        row = await fetch_one(
            "SELECT * FROM workflow_drafts WHERE id = $1 AND org_id = $2",
            draft_id, org_id, source_key=source_key
        )
        if row:
            return dict(row)
    # Create a new draft
    row = await fetch_one(
        "INSERT INTO workflow_drafts (org_id, status) VALUES ($1, 'chatting') RETURNING *",
        org_id, source_key=source_key
    )
    return dict(row)


async def _copy_workflow_into_draft(wf: dict, draft_id: str, granted_roles: list[str], source_key: str) -> None:
    """
    Shared by the load_existing_workflow tool (LLM-triggered, matched by name
    during chat) and start_edit_draft (deterministic, triggered by clicking
    "Edit the logic" on a specific workflow row — no name-matching involved).
    Copies every field of a live `workflows` row into a workflow_drafts row
    so the admin can change it by talking, exactly like building a new one.
    """
    steps           = _parse_jsonb(wf.get("steps"), [])
    gates           = _parse_jsonb(wf.get("gates"), [])
    entity_schema   = _parse_jsonb(wf.get("entity_schema"), {})
    calc_rules      = _parse_jsonb(wf.get("calc_rules"), {})
    sql_params      = _parse_jsonb(wf.get("sql_params_order"), [])
    business_glossary = _parse_jsonb(wf.get("business_glossary"), {})
    pdf_config      = _parse_jsonb(wf.get("pdf_config"), None)
    training_phrases = _parse_jsonb(wf.get("training_phrases"), [])

    await execute("""
        UPDATE workflow_drafts SET
            intent_key=$1, name=$2, description=$3, workflow_type=$4,
            training_phrases=$5::jsonb, entity_schema=$6::jsonb,
            calc_rules=$7::jsonb, steps=$8::jsonb,
            sql_template=$9, sql_params_order=$10::jsonb,
            response_format=$11, business_glossary=$12::jsonb,
            llm_system_prompt=$13, pdf_config=$14::jsonb,
            response_template=$15, otp_required=$16,
            otp_threshold=$17, approval_threshold=$18,
            gates=$19::jsonb, granted_roles=$20,
            slash_command=$21, command_description=$22, menu_section=$23,
            status='chatting', updated_at=now()
        WHERE id=$24
    """,
        wf["intent_key"], wf["name"], wf.get("description"), wf["workflow_type"],
        json.dumps(training_phrases), json.dumps(entity_schema),
        json.dumps(calc_rules), json.dumps(steps),
        wf.get("sql_template"), json.dumps(sql_params),
        wf.get("response_format") or "generic", json.dumps(business_glossary),
        wf.get("llm_system_prompt"),
        json.dumps(pdf_config) if pdf_config else None,
        wf.get("response_template"), wf.get("otp_required", False),
        wf.get("otp_threshold"), wf.get("approval_threshold"),
        json.dumps(gates), granted_roles,
        wf.get("slash_command"), wf.get("command_description"), wf.get("menu_section"),
        draft_id, source_key=source_key
    )


async def start_edit_draft(wf: dict, org_id: str, source_key: str) -> dict:
    """
    Deterministic entry point for the admin panel's "Edit the logic" button —
    creates a fresh draft pre-loaded from a SPECIFIC workflow by id (never
    guessed by an LLM matching a name), and seeds the chat with a greeting so
    the builder opens already primed instead of the admin re-explaining which
    workflow they mean or the LLM misidentifying it.
    """
    row = await fetch_one(
        "INSERT INTO workflow_drafts (org_id, status) VALUES ($1, 'chatting') RETURNING *",
        org_id, source_key=source_key
    )
    draft_id = str(row["id"])

    granted = await fetch_all(
        "SELECT name FROM roles WHERE org_id = $1 AND $2 = ANY(permissions)",
        org_id, wf["intent_key"], source_key=source_key
    )
    granted_roles = [r["name"] for r in granted]

    await _copy_workflow_into_draft(wf, draft_id, granted_roles, source_key)

    greeting = f"Loaded *{wf['name']}* — tell me what you'd like to change."
    await execute(
        "UPDATE workflow_drafts SET chat_history = $1::jsonb WHERE id = $2",
        json.dumps([{"role": "assistant", "content": greeting}]), draft_id, source_key=source_key
    )

    fresh = await fetch_one("SELECT * FROM workflow_drafts WHERE id = $1", draft_id, source_key=source_key)
    return {
        "draft_id":    draft_id,
        "greeting":    greeting,
        "draft_recap": build_draft_recap(dict(fresh)),
    }


async def _execute_tool(
    tool_name: str,
    tool_input: dict,
    draft: dict,
    org_id: str,
    attachment_b64: str | None,
    source_key: str = "platform",
) -> dict:

    if tool_name == "list_existing_workflows":
        live = await fetch_all(
            "SELECT intent_key, name, workflow_type FROM workflows WHERE org_id = $1 ORDER BY name",
            org_id, source_key=source_key
        )
        roles = await fetch_all(
            "SELECT name FROM roles WHERE org_id = $1 ORDER BY name", org_id, source_key=source_key
        )
        drafts = await fetch_all("""
            SELECT id, name, purpose, status, updated_at
            FROM workflow_drafts
            WHERE org_id = $1 AND status = 'chatting' AND id != $2
            ORDER BY updated_at DESC LIMIT 5
        """, org_id, draft["id"], source_key=source_key)
        return {
            "live_workflows":    [dict(r) for r in live],
            "org_roles":         [r["name"] for r in roles],
            "unfinished_drafts": [dict(r) for r in drafts],
        }

    if tool_name == "update_builder_draft":
        updates: dict = {}
        if tool_input.get("purpose"):
            updates["purpose"] = tool_input["purpose"]
        if tool_input.get("workflow_type"):
            updates["workflow_type"] = tool_input["workflow_type"]
        if tool_input.get("business_rules"):
            existing = draft.get("business_rules") or ""
            updates["business_rules"] = (existing + "\n" + tool_input["business_rules"]).strip()
        if tool_input.get("raw_fields"):
            existing_fields = _parse_jsonb(draft.get("raw_fields"), [])
            merged = list({*existing_fields, *tool_input["raw_fields"]})
            updates["raw_fields"] = json.dumps(merged)
        if tool_input.get("slash_command"):
            updates["slash_command"] = tool_input["slash_command"].lstrip("/")
        if tool_input.get("command_description"):
            updates["command_description"] = tool_input["command_description"]
        if tool_input.get("menu_section"):
            updates["menu_section"] = tool_input["menu_section"]

        if updates:
            set_parts = [f"{k} = ${i+2}" for i, k in enumerate(updates)]
            await execute(
                f"UPDATE workflow_drafts SET {', '.join(set_parts)}, updated_at = now() WHERE id = $1",
                draft["id"], *updates.values(), source_key=source_key
            )
            # Refresh local draft dict so subsequent tool calls in same turn see the updates
            for k, v in updates.items():
                draft[k] = v
        return {"saved": list(updates.keys())}

    if tool_name == "set_gates":
        gates = tool_input.get("gates") or []
        # Backfill missing ids so the validator's uniqueness/reference checks
        # never choke on an LLM omission — deterministic, not a guess.
        for i, g in enumerate(gates):
            if isinstance(g, dict) and not g.get("id"):
                g["id"] = f"{g.get('type', 'gate')}{i+1}"
        await execute(
            "UPDATE workflow_drafts SET gates = $1::jsonb, updated_at = now() WHERE id = $2",
            json.dumps(gates), draft["id"], source_key=source_key
        )
        draft["gates"] = gates
        return {"saved_gates": len(gates)}

    if tool_name == "set_roles":
        roles = tool_input.get("roles") or []
        await execute(
            "UPDATE workflow_drafts SET granted_roles = $1, updated_at = now() WHERE id = $2",
            roles, draft["id"], source_key=source_key
        )
        draft["granted_roles"] = roles
        return {"saved_roles": roles}

    if tool_name == "analyze_sample_pdf":
        if not attachment_b64:
            return {"error": "No PDF attached to this message"}
        from app.services.pdf_template_extractor import extract_pdf_template
        pdf_bytes = base64.b64decode(attachment_b64)
        spec = await extract_pdf_template(pdf_bytes, tool_input.get("doc_type_hint", ""))
        await execute(
            "UPDATE workflow_drafts SET pdf_sample_analysis = $1::jsonb, updated_at = now() WHERE id = $2",
            json.dumps(spec), draft["id"], source_key=source_key
        )
        return {
            "doc_type_guess": spec.get("doc_type_guess"),
            "analyzed": True,
            "message": f"Extracted layout from your sample PDF ({spec.get('doc_type_guess', 'document')}). Will use this style."
        }

    if tool_name == "compile_and_summarize":
        fresh = await fetch_one("SELECT * FROM workflow_drafts WHERE id = $1", draft["id"], source_key=source_key)
        try:
            spec = await compile_workflow_spec(dict(fresh), org_id=org_id, source_key=source_key)
        except ValueError as e:
            return {"error": str(e)}

        # Save compiled spec back into the draft
        await execute("""
            UPDATE workflow_drafts SET
                name=$1, intent_key=$2, description=$3,
                workflow_type=$4,
                training_phrases=$5::jsonb, entity_schema=$6::jsonb,
                calc_rules=$7::jsonb, steps=$8::jsonb,
                sql_template=$9, sql_params_order=$10::jsonb, response_format=$11,
                business_glossary=$12::jsonb, llm_system_prompt=$13,
                pdf_config=$14::jsonb, response_template=$15,
                otp_required=$16, otp_threshold=$17, approval_threshold=$18,
                gates=$19::jsonb,
                plain_english_summary=$20,
                slash_command=$21, command_description=$22, menu_section=$23,
                status = 'ready_for_review', updated_at = now()
            WHERE id = $24
        """,
            spec["name"], spec["intent_key"], spec["description"],
            spec.get("workflow_type") or "action",
            json.dumps(spec["training_phrases"]),
            json.dumps(spec["entity_schema"]),
            json.dumps(spec.get("calc_rules", {})),
            json.dumps(spec.get("steps", [])),
            spec.get("sql_template"),
            json.dumps(spec.get("sql_params_order", [])),
            spec.get("response_format") or "generic",
            json.dumps(spec.get("business_glossary", {})),
            spec.get("llm_system_prompt"),
            json.dumps(spec["pdf_config"]) if spec.get("pdf_config") else None,
            spec.get("response_template"),
            bool(spec.get("otp_required", False)),
            spec.get("otp_threshold"),
            spec.get("approval_threshold"),
            json.dumps(spec.get("gates") or draft.get("gates") or []),
            spec["plain_english_summary"],
            draft.get("slash_command"),
            draft.get("command_description"),
            draft.get("menu_section"),
            draft["id"],
            source_key=source_key
        )
        return {
            "summary":              spec["plain_english_summary"],
            "intent_key":           spec["intent_key"],
            "_show_confirm_buttons": True,
            "has_pdf_preview":      bool(spec.get("pdf_config")),
        }

    if tool_name == "revise_draft":
        change = tool_input.get("change_description", "")
        existing_rules = draft.get("business_rules") or ""
        await execute(
            "UPDATE workflow_drafts SET business_rules = $1, status = 'chatting', updated_at = now() WHERE id = $2",
            f"{existing_rules}\nRequested change: {change}".strip(),
            draft["id"], source_key=source_key
        )
        fresh = await fetch_one("SELECT * FROM workflow_drafts WHERE id = $1", draft["id"], source_key=source_key)
        return await _execute_tool("compile_and_summarize", {}, dict(fresh), org_id, attachment_b64, source_key)

    if tool_name == "mark_ready_for_review":
        fresh = await fetch_one("SELECT * FROM workflow_drafts WHERE id = $1", draft["id"], source_key=source_key)
        if not fresh or fresh["status"] not in ("ready_for_review", "chatting"):
            return {"error": "Nothing compiled yet. Please describe the workflow first."}
        if not fresh.get("intent_key"):
            return {"error": "Workflow has no name yet — please compile first."}
        if not fresh.get("granted_roles"):
            return {"error": "No one's been given access yet — ask who should be able to use this before marking it ready."}
        if not fresh.get("slash_command"):
            return {"error": "No trigger command set yet — ask what it should be before marking it ready."}
        await execute(
            "UPDATE workflow_drafts SET status = 'ready_for_review', updated_at = now() WHERE id = $1",
            draft["id"], source_key=source_key
        )
        return {
            "_show_publish_panel": True,
            "draft_id": str(draft["id"]),
            "message": "Everything's gathered — review the recap and hit Publish."
        }

    if tool_name == "load_existing_workflow":
        intent_key = tool_input.get("intent_key", "")
        wf = await fetch_one(
            "SELECT * FROM workflows WHERE org_id = $1 AND intent_key = $2",
            org_id, intent_key, source_key=source_key
        )
        if not wf:
            return {"error": f"No workflow found with key '{intent_key}'. Check the name and try again."}
        wf = dict(wf)

        granted = await fetch_all(
            "SELECT name FROM roles WHERE org_id = $1 AND $2 = ANY(permissions)",
            org_id, intent_key, source_key=source_key
        )
        granted_roles = [r["name"] for r in granted]

        await _copy_workflow_into_draft(wf, draft["id"], granted_roles, source_key)
        draft["granted_roles"] = granted_roles
        draft["gates"] = _parse_jsonb(wf.get("gates"), [])

        return {
            "loaded": True,
            "name": wf["name"],
            "intent_key": intent_key,
            "current_gates": draft["gates"],
            "current_roles": granted_roles,
            "message": f"Loaded '{wf['name']}' — tell me what to change."
        }

    return {"error": f"Unknown tool: {tool_name}"}


async def run_builder_agent(
    message: str,
    org_id: str,
    draft_id: str | None = None,
    attachment_b64: str | None = None,
    pre_extracted_pdf: dict | None = None,
    max_iterations: int = 6,
    source_key: str = "platform",
) -> dict:
    """
    Process one chat turn from the admin.

    Returns:
        {
            "reply":               str,      — message to show the admin
            "draft_id":            str,      — use on next call
            "draft_recap":         str,      — deterministic "Draft so far" text, always present
            "summary_card":        str|None, — plain-English summary if just compiled
            "ready_for_publish":   bool,      — show the confirm-and-publish screen
            "published":           bool,
            "published_intent_key": str|None,
        }
    """
    draft = await _get_or_create_draft(org_id, draft_id, source_key)

    # If a pre-extracted PDF analysis was passed from the browser (extracted before this call),
    # save it to the draft immediately so compile_and_summarize can use it
    if pre_extracted_pdf and isinstance(pre_extracted_pdf, dict):
        await execute(
            "UPDATE workflow_drafts SET pdf_sample_analysis = $1::jsonb, updated_at = now() WHERE id = $2",
            json.dumps(pre_extracted_pdf), draft["id"], source_key=source_key
        )
        draft["pdf_sample_analysis"] = pre_extracted_pdf
        print(f"[BUILDER] Pre-extracted PDF analysis saved to draft {draft['id']}")
        # Inject a system note into chat history so the bot knows the PDF is available
        chat_history = draft.get("chat_history") or []
        if isinstance(chat_history, str):
            chat_history = json.loads(chat_history)
        chat_history.append({
            "role": "user",
            "content": f"[Admin uploaded a sample PDF — it has been analyzed. doc_type: {pre_extracted_pdf.get('doc_type_guess', 'invoice')}. The layout has been extracted and saved. When compiling, use this PDF layout for render_instructions.]"
        })
        await execute(
            "UPDATE workflow_drafts SET chat_history = $1::jsonb, updated_at = now() WHERE id = $2",
            json.dumps(chat_history), draft["id"], source_key=source_key
        )
        draft["chat_history"] = chat_history

    # Load chat history from DB (server-side storage)
    chat_history = draft.get("chat_history") or []
    if isinstance(chat_history, str):
        chat_history = json.loads(chat_history)

    # Append the new user message
    user_content = message
    if attachment_b64:
        user_content += "\n[Admin attached a PDF file with this message.]"
    chat_history.append({"role": "user", "content": user_content})

    # Inject current draft state into context so LLM can avoid re-asking
    draft_context = ""
    if draft.get("purpose"):
        draft_context += f"Purpose: {draft['purpose']}\n"
    if draft.get("workflow_type"):
        draft_context += f"Workflow Type: {draft['workflow_type']}\n"
    raw_fields = _parse_jsonb(draft.get("raw_fields"), [])
    if raw_fields:
        draft_context += f"Fields to collect: {', '.join(raw_fields)}\n"
    draft_gates = _parse_jsonb(draft.get("gates"), [])
    if draft_gates:
        draft_context += f"Constraints so far (gates): {json.dumps(draft_gates)}\n"
    if draft.get("granted_roles"):
        draft_context += f"Roles allowed so far: {', '.join(draft['granted_roles'])}\n"
    if draft.get("business_rules"):
        draft_context += f"Business Rules: {draft['business_rules']}\n"
    if draft.get("slash_command"):
        draft_context += f"Slash Command: /{draft['slash_command']}\n"
    if draft.get("command_description"):
        draft_context += f"Command Description: {draft['command_description']}\n"
    if draft.get("menu_section"):
        draft_context += f"Menu Section: {draft['menu_section']}\n"

    # Build messages for API call
    system_content = _SYSTEM_PROMPT
    if draft_context:
        system_content += f"\n\n=== CURRENT DRAFT STATE ===\n{draft_context}=== END DRAFT STATE ===\n"
    messages = [{"role": "system", "content": system_content}] + chat_history

    summary_card = None
    published = False
    published_intent_key = None
    has_pdf_preview = False
    ready_for_publish = False

    async def _recap() -> str:
        fresh = await fetch_one("SELECT * FROM workflow_drafts WHERE id = $1", draft["id"], source_key=source_key)
        return build_draft_recap(dict(fresh)) if fresh else build_draft_recap(draft)

    for _ in range(max_iterations):
        response = await _llm_chat(
            messages=messages,
            tools=_TOOLS,
            tool_choice="auto",
            max_tokens=8192,
        )
        msg = response.choices[0].message

        if not msg.tool_calls:
            # Final text response
            reply = (msg.content or "").strip()
            chat_history.append({"role": "assistant", "content": reply})
            # Save updated chat history to DB
            await execute(
                "UPDATE workflow_drafts SET chat_history = $1::jsonb, updated_at = now() WHERE id = $2",
                json.dumps(chat_history), draft["id"], source_key=source_key
            )
            return {
                "reply":                reply,
                "draft_id":             str(draft["id"]),
                "draft_recap":          await _recap(),
                "summary_card":         summary_card,
                "has_pdf_preview":      has_pdf_preview,
                "published":            published,
                "published_intent_key": published_intent_key,
                "ready_for_publish":    ready_for_publish,
            }

        # Process tool calls
        messages.append({
            "role":       "assistant",
            "content":    msg.content,
            "tool_calls": msg.tool_calls,
        })

        for tc in msg.tool_calls:
            tool_input = json.loads(tc.function.arguments)
            try:
                result = await _execute_tool(
                    tc.function.name, tool_input, draft, org_id, attachment_b64, source_key
                )
            except Exception as e:
                import logging
                logging.exception("builder tool %s failed", tc.function.name)
                result = f"ERROR: {tc.function.name} failed: {type(e).__name__}: {e}. Tell the user you hit a temporary problem saving that, and that their answer is noted in the conversation."

            if result.get("_show_confirm_buttons"):
                summary_card = result.get("summary")
                has_pdf_preview = result.get("has_pdf_preview", False)

            # mark_ready_for_review is the deterministic signal that the
            # confirm-and-publish screen should open — previously this was
            # only ever visible to the LLM (as a tool result it then
            # paraphrased into chat text), so the frontend had no reliable
            # way to know a draft was ready.
            if tc.function.name == "mark_ready_for_review" and result.get("_show_publish_panel"):
                ready_for_publish = True

            if tc.function.name == "publish_workflow" and result.get("published"):
                published = True
                published_intent_key = result.get("intent_key")

            messages.append({
                "tool_call_id": tc.id,
                "role":         "tool",
                "content":      json.dumps(result),
            })

    # Max iterations hit
    reply = "Let me take that one step at a time — could you tell me a bit more?"
    chat_history.append({"role": "assistant", "content": reply})
    await execute(
        "UPDATE workflow_drafts SET chat_history = $1::jsonb, updated_at = now() WHERE id = $2",
        json.dumps(chat_history), draft["id"], source_key=source_key
    )
    return {
        "reply":                reply,
        "draft_id":             str(draft["id"]),
        "draft_recap":          await _recap(),
        "summary_card":         summary_card,
        "has_pdf_preview":      has_pdf_preview,
        "published":            published,
        "published_intent_key": published_intent_key,
        "ready_for_publish":    ready_for_publish,
    }
