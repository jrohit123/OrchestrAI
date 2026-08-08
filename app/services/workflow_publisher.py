"""
workflow_publisher.py — Promotes a workflow_drafts row to the live workflows table.

Uses ON CONFLICT DO UPDATE so publishing an existing workflow updates it in-place.
The old row is NOT versioned (versions table deferred) — the draft row itself
stays as the history with status='published'.
"""
import json
from app.db import fetch_one, execute


def _j(val, default=None):
    """Safely serialize a value to JSON string for DB binding."""
    if val is None:
        return default
    if isinstance(val, (dict, list)):
        return json.dumps(val)
    return val


async def publish_draft(draft: dict, org_id: str, published_by_user_id: str) -> dict:
    """
    Publish a workflow_drafts row to the live workflows table.
    Returns {"published": True, "intent_key": ..., "is_new": bool}
    Raises ValueError if the draft is not ready_for_review.
    """
    if draft.get("status") not in ("ready_for_review", "chatting"):
        raise ValueError(
            f"Draft status is '{draft.get('status')}' — must be ready_for_review to publish."
        )
    if not draft.get("intent_key"):
        raise ValueError("Draft has no intent_key — cannot publish.")

    # Validate consistency before writing to live table
    from app.services.workflow_validator import validate_workflow_config
    problems = validate_workflow_config(draft)
    if problems:
        raise ValueError(
            "Cannot publish — config is inconsistent:\n" +
            "\n".join(f"  • {p}" for p in problems)
        )

    existing = await fetch_one(
        "SELECT id, version FROM workflows WHERE org_id = $1 AND intent_key = $2",
        org_id, draft["intent_key"]
    )
    new_version = (existing["version"] + 1) if existing else 1

    await execute("""
        INSERT INTO workflows (
            org_id, name, intent_key, description, workflow_type,
            training_phrases, entity_schema, calc_rules, steps,
            sql_template, sql_params_order, response_format,
            business_glossary, llm_system_prompt, pdf_config,
            response_template, otp_required, otp_threshold, approval_threshold,
            adapter_method, version, is_active,
            trigger_patterns, slash_command, command_description, menu_section
        ) VALUES (
            $1,$2,$3,$4,$5,
            $6::jsonb,$7::jsonb,$8::jsonb,$9::jsonb,
            $10,$11::jsonb,$12,
            $13::jsonb,$14,$15::jsonb,
            $16,$17,$18,$19,
            'generic',$20,true,
            '[]'::jsonb,$21,$22,$23
        )
        ON CONFLICT (org_id, intent_key) DO UPDATE SET
            name                = EXCLUDED.name,
            description         = EXCLUDED.description,
            workflow_type       = EXCLUDED.workflow_type,
            training_phrases    = EXCLUDED.training_phrases,
            entity_schema       = EXCLUDED.entity_schema,
            calc_rules          = EXCLUDED.calc_rules,
            steps               = EXCLUDED.steps,
            sql_template        = EXCLUDED.sql_template,
            sql_params_order    = EXCLUDED.sql_params_order,
            response_format     = EXCLUDED.response_format,
            business_glossary   = EXCLUDED.business_glossary,
            llm_system_prompt   = EXCLUDED.llm_system_prompt,
            pdf_config          = EXCLUDED.pdf_config,
            response_template   = EXCLUDED.response_template,
            otp_required        = EXCLUDED.otp_required,
            otp_threshold       = EXCLUDED.otp_threshold,
            approval_threshold  = EXCLUDED.approval_threshold,
            version             = EXCLUDED.version,
            is_active           = true,
            slash_command       = EXCLUDED.slash_command,
            command_description = EXCLUDED.command_description,
            menu_section        = EXCLUDED.menu_section
    """,
        org_id,
        draft.get("name") or draft.get("intent_key"),
        draft["intent_key"],
        draft.get("description", ""),
        draft.get("workflow_type") or "action",
        _j(draft.get("training_phrases"), "[]"),
        _j(draft.get("entity_schema"),    "{}"),
        _j(draft.get("calc_rules"),       "{}"),
        _j(draft.get("steps"),            "[]"),
        draft.get("sql_template"),
        _j(draft.get("sql_params_order"), "[]"),
        draft.get("response_format") or "generic",
        _j(draft.get("business_glossary"), "{}"),
        draft.get("llm_system_prompt"),
        _j(draft.get("pdf_config")),
        draft.get("response_template"),
        bool(draft.get("otp_required", False)),
        draft.get("otp_threshold"),
        draft.get("approval_threshold"),
        new_version,
        draft.get("slash_command"),
        draft.get("command_description"),
        draft.get("menu_section") or "other",
    )

    # Grant permissions to specified roles (from draft.granted_roles)
    granted_roles = draft.get("granted_roles")
    if granted_roles:
        if isinstance(granted_roles, str):
            try:
                granted_roles = json.loads(granted_roles)
            except (json.JSONDecodeError, TypeError):
                granted_roles = []
        if granted_roles:
            await execute("""
                UPDATE roles SET permissions = array_append(permissions, $1)
                WHERE org_id = $2 AND name = ANY($3)
                  AND NOT permissions @> ARRAY[$1]
            """, draft["intent_key"], org_id, granted_roles)
    else:
        # Fallback: grant to owner role (minimum — admin can add more later)
        await execute("""
            UPDATE roles
            SET permissions = array_append(permissions, $1)
            WHERE org_id = $2 AND name = 'owner'
              AND NOT $1 = ANY(permissions)
        """, draft["intent_key"], org_id)

    # Mark draft as published
    await execute(
        "UPDATE workflow_drafts SET status = 'published', updated_at = now() WHERE id = $1",
        draft["id"]
    )

    return {
        "published": True,
        "intent_key": draft["intent_key"],
        "is_new": existing is None,
        "version": new_version,
    }
