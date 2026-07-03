"""
workflow_builder_agent.py — Conversational agent for building workflows via admin panel chat.

Asks one question at a time, builds a structured draft, compiles it, shows a plain-English
summary, and publishes only after explicit confirmation.
Chat history is stored server-side in workflow_drafts.chat_history — never round-tripped
through the browser.
"""
import json
import os
import base64
from openai import AsyncOpenAI
from app.db import fetch_all, fetch_one, execute
from app.services.workflow_compiler import compile_workflow_spec
from app.services.workflow_publisher import publish_draft

_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

_SYSTEM_PROMPT = """You are helping a non-technical business owner describe a business process
so it becomes a working WhatsApp workflow. They think in plain terms — not schemas, not JSON, not code.
Never show them any technical details.

Ask ONE question at a time. After each answer, briefly restate what you understood, then ask the next
most useful question. Cover these topics (skip what's already answered or not relevant):

1. What does this do — what will people type or ask to trigger it?
   Does it CREATE/CHANGE something (action) or just SHOW information (read)?
2. What information needs to be collected or looked up?
3. Should anything be CALCULATED automatically? (tax, total, discount)
   Get the business rule in plain terms: "GST is 3% of item value" is enough.
4. Any safety rules — verification code or someone's approval above a certain amount?
5. Does this produce a document? If yes, ask:
   "Do you have a sample PDF you already send? Attach it and I'll match the look."
   If no PDF attached, ask what the document should show.

Once you have enough information, call compile_and_summarize.
Show the summary in plain English and ask if it's correct.
If they want changes, call revise_draft, then show the new summary.
Only call publish_workflow after an explicit "yes" on a summary you've already shown.

If the first message is vague ("help me" / "I want a workflow"), call list_existing_workflows
first, mention what already exists including unfinished drafts, and ask what to add or change."""

_TOOLS = [
    {"type": "function", "function": {
        "name": "list_existing_workflows",
        "description": "List this org's live workflows and any unfinished drafts.",
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
            "business_rules": {"type": "string", "description": "Safety rules, thresholds, special logic"},
        }}
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
        "name": "publish_workflow",
        "description": "Make the confirmed workflow live. Call ONLY after admin said yes to a summary.",
        "parameters": {"type": "object", "properties": {}}
    }},
]


async def _get_or_create_draft(org_id: str, draft_id: str | None) -> dict:
    if draft_id:
        row = await fetch_one(
            "SELECT * FROM workflow_drafts WHERE id = $1 AND org_id = $2",
            draft_id, org_id
        )
        if row:
            return dict(row)
    # Create a new draft
    row = await fetch_one(
        "INSERT INTO workflow_drafts (org_id, status) VALUES ($1, 'chatting') RETURNING *",
        org_id
    )
    return dict(row)


async def _execute_tool(
    tool_name: str,
    tool_input: dict,
    draft: dict,
    org_id: str,
    attachment_b64: str | None,
) -> dict:

    if tool_name == "list_existing_workflows":
        live = await fetch_all(
            "SELECT intent_key, name, workflow_type FROM workflows WHERE org_id = $1 ORDER BY name",
            org_id
        )
        drafts = await fetch_all("""
            SELECT id, name, purpose, status, updated_at
            FROM workflow_drafts
            WHERE org_id = $1 AND status = 'chatting' AND id != $2
            ORDER BY updated_at DESC LIMIT 5
        """, org_id, draft["id"])
        return {
            "live_workflows":    [dict(r) for r in live],
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
            existing_fields = draft.get("raw_fields") or []
            if isinstance(existing_fields, str):
                existing_fields = json.loads(existing_fields)
            merged = list({*existing_fields, *tool_input["raw_fields"]})
            updates["raw_fields"] = json.dumps(merged)

        if updates:
            set_parts = [f"{k} = ${i+2}" for i, k in enumerate(updates)]
            await execute(
                f"UPDATE workflow_drafts SET {', '.join(set_parts)}, updated_at = now() WHERE id = $1",
                draft["id"], *updates.values()
            )
        return {"saved": list(updates.keys())}

    if tool_name == "analyze_sample_pdf":
        if not attachment_b64:
            return {"error": "No PDF attached to this message"}
        from app.services.pdf_template_extractor import extract_pdf_template
        pdf_bytes = base64.b64decode(attachment_b64)
        spec = await extract_pdf_template(pdf_bytes, tool_input.get("doc_type_hint", ""))
        await execute(
            "UPDATE workflow_drafts SET pdf_sample_analysis = $1::jsonb, updated_at = now() WHERE id = $2",
            json.dumps(spec), draft["id"]
        )
        return {
            "doc_type_guess": spec.get("doc_type_guess"),
            "analyzed": True,
            "message": f"Extracted layout from your sample PDF ({spec.get('doc_type_guess', 'document')}). Will use this style."
        }

    if tool_name == "compile_and_summarize":
        fresh = await fetch_one("SELECT * FROM workflow_drafts WHERE id = $1", draft["id"])
        try:
            spec = await compile_workflow_spec(dict(fresh), org_id=org_id)
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
                plain_english_summary=$19,
                status = 'ready_for_review', updated_at = now()
            WHERE id = $20
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
            spec["plain_english_summary"],
            draft["id"]
        )
        return {
            "summary":              spec["plain_english_summary"],
            "intent_key":           spec["intent_key"],
            "_show_confirm_buttons": True,
        }

    if tool_name == "revise_draft":
        change = tool_input.get("change_description", "")
        existing_rules = draft.get("business_rules") or ""
        await execute(
            "UPDATE workflow_drafts SET business_rules = $1, status = 'chatting', updated_at = now() WHERE id = $2",
            f"{existing_rules}\nRequested change: {change}".strip(),
            draft["id"]
        )
        fresh = await fetch_one("SELECT * FROM workflow_drafts WHERE id = $1", draft["id"])
        return await _execute_tool("compile_and_summarize", {}, dict(fresh), org_id, attachment_b64)

    if tool_name == "publish_workflow":
        fresh = await fetch_one("SELECT * FROM workflow_drafts WHERE id = $1", draft["id"])
        if not fresh or fresh["status"] not in ("ready_for_review", "chatting"):
            return {"error": "Nothing compiled yet. Please describe the workflow first."}
        if not fresh.get("intent_key"):
            return {"error": "Workflow has no name yet — please compile first."}
        try:
            result = await publish_draft(dict(fresh), org_id, "admin")
            return result
        except ValueError as e:
            return {"error": str(e)}

    return {"error": f"Unknown tool: {tool_name}"}


async def run_builder_agent(
    message: str,
    org_id: str,
    draft_id: str | None = None,
    attachment_b64: str | None = None,
    pre_extracted_pdf: dict | None = None,
    max_iterations: int = 6,
) -> dict:
    """
    Process one chat turn from the admin.

    Returns:
        {
            "reply":               str,      — message to show the admin
            "draft_id":            str,      — use on next call
            "summary_card":        str|None, — plain-English summary if compiled
            "published":           bool,
            "published_intent_key": str|None,
        }
    """
    draft = await _get_or_create_draft(org_id, draft_id)

    # If a pre-extracted PDF analysis was passed from the browser (extracted before this call),
    # save it to the draft immediately so compile_and_summarize can use it
    if pre_extracted_pdf and isinstance(pre_extracted_pdf, dict):
        await execute(
            "UPDATE workflow_drafts SET pdf_sample_analysis = $1::jsonb, updated_at = now() WHERE id = $2",
            json.dumps(pre_extracted_pdf), draft["id"]
        )
        draft["pdf_sample_analysis"] = pre_extracted_pdf
        print(f"[BUILDER] Pre-extracted PDF analysis saved to draft {draft['id']}")

    # Load chat history from DB (server-side storage)
    chat_history = draft.get("chat_history") or []
    if isinstance(chat_history, str):
        chat_history = json.loads(chat_history)

    # Append the new user message
    user_content = message
    if attachment_b64:
        user_content += "\n[Admin attached a PDF file with this message.]"
    chat_history.append({"role": "user", "content": user_content})

    # Build messages for API call
    messages = [{"role": "system", "content": _SYSTEM_PROMPT}] + chat_history

    summary_card = None
    published = False
    published_intent_key = None

    for _ in range(max_iterations):
        response = await _client.chat.completions.create(
            model="gpt-4o",
            max_tokens=2048,
            messages=messages,
            tools=_TOOLS,
            tool_choice="auto",
            parallel_tool_calls=False,
        )
        msg = response.choices[0].message

        if not msg.tool_calls:
            # Final text response
            reply = (msg.content or "").strip()
            chat_history.append({"role": "assistant", "content": reply})
            # Save updated chat history to DB
            await execute(
                "UPDATE workflow_drafts SET chat_history = $1::jsonb, updated_at = now() WHERE id = $2",
                json.dumps(chat_history), draft["id"]
            )
            return {
                "reply":                reply,
                "draft_id":             str(draft["id"]),
                "summary_card":         summary_card,
                "published":            published,
                "published_intent_key": published_intent_key,
            }

        # Process tool calls
        messages.append({
            "role":       "assistant",
            "content":    msg.content,
            "tool_calls": msg.tool_calls,
        })

        for tc in msg.tool_calls:
            tool_input = json.loads(tc.function.arguments)
            result = await _execute_tool(
                tc.function.name, tool_input, draft, org_id, attachment_b64
            )

            if result.get("_show_confirm_buttons"):
                summary_card = result.get("summary")

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
        json.dumps(chat_history), draft["id"]
    )
    return {
        "reply":                reply,
        "draft_id":             str(draft["id"]),
        "summary_card":         summary_card,
        "published":            published,
        "published_intent_key": published_intent_key,
    }
