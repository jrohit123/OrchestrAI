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

EXTRACTION-FIRST RULE (highest priority):
Before replying, extract EVERYTHING from the user's message: purpose,
workflow type, use cases, fields, rules, thresholds — whatever is present.
Save all of it via update_builder_draft in ONE call. Then your reply must:
1. Briefly play back what you understood (so they can correct you)
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
If the workflow is clearly read-only, don't ask about OTP or approval
thresholds — state "no OTP/approval needed since this only shows data"
in the summary and move on. Only ask about safety gates for action
workflows.

Ask ONE question at a time. After each answer, briefly restate what you understood, then ask the next
most useful question. Cover these topics (skip what's already answered or not relevant):

1. What does this do — what will people type or ask to trigger it?
   Does it CREATE/CHANGE something (action) or just SHOW information (read)?
2. What information needs to be collected or looked up?
3. Should anything be CALCULATED automatically? (tax, total, discount)
   Get the business rule in plain terms: "GST is 3% of item value" is enough.
4. Any safety rules — verification code or someone's approval above a certain amount?
   THE MOMENT the admin gives a number, call update_builder_draft with otp_threshold
   and/or approval_threshold set to that exact number — convert "1 lakh" to 100000,
   "50k" to 50000 yourself. Then confirm back: "Got it — OTP above Rs.50,000,
   approval above Rs.1,00,000." so they can correct you immediately if you misheard.
   NOTE: Do NOT proactively ask about OTP/approval thresholds. Only save them if the admin
   volunteers them. These will be set in the publish panel.
5. Does this produce a document? If yes, ask:
   "Do you have a sample PDF you already send? Attach it and I'll match the look."
   If no PDF attached, ask what the document should show.
6. Before publishing, ask: "What short command should trigger this? I suggest /stock"
   (derive suggestion from the name; lowercase, no spaces, ≤32 chars). Save via
   update_builder_draft as slash_command. Set menu_section yourself: 'reports' if
   workflow_type is read, 'create' if action. Also write a one-line
   command_description (≤72 chars) for the menu.
NOTE: Do NOT ask about which roles should use this workflow. Roles are assigned in the publish panel.

IMPORTANT: If a message in the conversation contains "[Admin uploaded a sample PDF" — that means
the PDF has already been analyzed and saved. Do NOT ask the admin to upload again.
When asked about the document format, confirm you'll use the uploaded sample's layout.

Once you have enough information, call compile_and_summarize.
Show the summary in plain English and ask if it's correct.
If they want changes, call revise_draft, then show the new summary.
Only call mark_ready_for_review after an explicit "yes" on a summary you've already shown.
The publish panel will then handle roles, OTP/approval thresholds, and the final slash command.

If the first message is vague ("help me" / "I want a workflow"), call list_existing_workflows
first, mention what already exists including unfinished drafts, and ask what to add or change.

If the admin wants to MODIFY something that already exists, call list_existing_workflows to find
its intent_key if needed, then call load_existing_workflow before asking what to change.
The normal flow (update_builder_draft, compile_and_summarize, publish_workflow) works identically
whether the draft started fresh or was loaded from an existing workflow."""

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
            "otp_threshold": {
                "type": "number",
                "description": "Amount above which OTP verification is required. Set THE MOMENT admin gives a number. Convert 'lakh'=100000, 'k'=1000. Omit if not mentioned."
            },
            "approval_threshold": {
                "type": "number",
                "description": "Amount above which owner approval is required. Convert 'lakh'=100000, '1 crore'=10000000. Omit if not mentioned."
            },
            "business_rules": {"type": "string", "description": "Any OTHER rule not covered by the two threshold fields above."},
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
        "description": "Mark the draft as ready for review. The admin will then use the publish panel to set roles, OTP/approval thresholds, and slash command. Call ONLY after admin said yes to a summary.",
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
        if tool_input.get("otp_threshold") is not None:
            updates["otp_threshold"] = float(tool_input["otp_threshold"])
            updates["otp_required"]  = True
        if tool_input.get("approval_threshold") is not None:
            updates["approval_threshold"] = float(tool_input["approval_threshold"])
        if tool_input.get("business_rules"):
            existing = draft.get("business_rules") or ""
            updates["business_rules"] = (existing + "\n" + tool_input["business_rules"]).strip()
        if tool_input.get("raw_fields"):
            existing_fields = draft.get("raw_fields") or []
            if isinstance(existing_fields, str):
                existing_fields = json.loads(existing_fields)
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
                draft["id"], *updates.values()
            )
            # Refresh local draft dict so subsequent tool calls in same turn see the updates
            for k, v in updates.items():
                draft[k] = v
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
                slash_command=$20, command_description=$21, menu_section=$22,
                status = 'ready_for_review', updated_at = now()
            WHERE id = $23
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
            draft.get("slash_command"),
            draft.get("command_description"),
            draft.get("menu_section"),
            draft["id"]
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
            draft["id"]
        )
        fresh = await fetch_one("SELECT * FROM workflow_drafts WHERE id = $1", draft["id"])
        return await _execute_tool("compile_and_summarize", {}, dict(fresh), org_id, attachment_b64)

    if tool_name == "mark_ready_for_review":
        fresh = await fetch_one("SELECT * FROM workflow_drafts WHERE id = $1", draft["id"])
        if not fresh or fresh["status"] not in ("ready_for_review", "chatting"):
            return {"error": "Nothing compiled yet. Please describe the workflow first."}
        if not fresh.get("intent_key"):
            return {"error": "Workflow has no name yet — please compile first."}
        await execute(
            "UPDATE workflow_drafts SET status = 'ready_for_review', updated_at = now() WHERE id = $1",
            draft["id"]
        )
        return {
            "_show_publish_panel": True,
            "draft_id": str(draft["id"]),
            "message": "Draft is ready — review the settings panel and hit Publish."
        }

    if tool_name == "load_existing_workflow":
        intent_key = tool_input.get("intent_key", "")
        wf = await fetch_one(
            "SELECT * FROM workflows WHERE org_id = $1 AND intent_key = $2",
            org_id, intent_key
        )
        if not wf:
            return {"error": f"No workflow found with key '{intent_key}'. Check the name and try again."}
        wf = dict(wf)
        steps = wf.get("steps")
        if isinstance(steps, str):
            try:
                steps = json.loads(steps)
            except Exception:
                steps = []
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
                slash_command=$19, command_description=$20, menu_section=$21,
                status='chatting', updated_at=now()
            WHERE id=$22
        """,
            wf["intent_key"], wf["name"], wf.get("description"), wf["workflow_type"],
            json.dumps(wf.get("training_phrases") or []),
            json.dumps(wf.get("entity_schema") or {}),
            json.dumps(wf.get("calc_rules") or {}),
            json.dumps(steps or []),
            wf.get("sql_template"),
            json.dumps(wf.get("sql_params_order") or []),
            wf.get("response_format") or "generic",
            json.dumps(wf.get("business_glossary") or {}),
            wf.get("llm_system_prompt"),
            json.dumps(wf.get("pdf_config")) if wf.get("pdf_config") else None,
            wf.get("response_template"),
            wf.get("otp_required", False),
            wf.get("otp_threshold"),
            wf.get("approval_threshold"),
            wf.get("slash_command"),
            wf.get("command_description"),
            wf.get("menu_section"),
            draft["id"]
        )
        return {
            "loaded": True,
            "name": wf["name"],
            "intent_key": intent_key,
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
            json.dumps(chat_history), draft["id"]
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
    if draft.get("raw_fields"):
        raw_fields = draft.get("raw_fields")
        if isinstance(raw_fields, str):
            try:
                raw_fields = json.loads(raw_fields)
            except:
                raw_fields = []
        draft_context += f"Fields to collect: {', '.join(raw_fields) if raw_fields else 'none'}\n"
    if draft.get("otp_threshold"):
        draft_context += f"OTP Threshold: {draft['otp_threshold']}\n"
    if draft.get("approval_threshold"):
        draft_context += f"Approval Threshold: {draft['approval_threshold']}\n"
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
                "has_pdf_preview":      has_pdf_preview,
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
            try:
                result = await _execute_tool(
                    tc.function.name, tool_input, draft, org_id, attachment_b64
                )
            except Exception as e:
                import logging
                logging.exception("builder tool %s failed", tc.function.name)
                result = f"ERROR: {tc.function.name} failed: {type(e).__name__}: {e}. Tell the user you hit a temporary problem saving that, and that their answer is noted in the conversation."

            if result.get("_show_confirm_buttons"):
                summary_card = result.get("summary")
                has_pdf_preview = result.get("has_pdf_preview", False)

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
        "has_pdf_preview":      has_pdf_preview,
        "published":            published,
        "published_intent_key": published_intent_key,
    }
