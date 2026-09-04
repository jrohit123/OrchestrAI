"""
workflow_publisher.py — Promotes a workflow_drafts row to the live workflows table.

Uses ON CONFLICT DO UPDATE so publishing an existing workflow updates it in-place.
The old row is NOT versioned (versions table deferred) — the draft row itself
stays as the history with status='published'.
"""
import json
from app.db import fetch_one, fetch_all, execute


def _j(val, default=None):
    """Safely serialize a value to JSON string for DB binding."""
    if val is None:
        return default
    if isinstance(val, (dict, list)):
        return json.dumps(val)
    return val


async def sync_role_grants(intent_key: str, org_id: str, desired_roles: list[str], source_key: str) -> None:
    """
    Set a workflow's role access to EXACTLY desired_roles — grants roles that
    should now have it, revokes roles that shouldn't. Unlike the old
    append-only logic (array_append with no removal path), this has to
    actually revoke now: a role gathered via chat one turn can be dropped by
    the admin ("actually only staff, not branch_manager") on a later turn,
    via set_roles replacing the whole list — publishing has to make the live
    grants match that replacement, not just accumulate onto it.
    """
    all_roles = await fetch_all(
        "SELECT id, name, permissions FROM roles WHERE org_id = $1", org_id, source_key=source_key
    )
    desired = set(desired_roles or [])
    for r in all_roles:
        has_it = intent_key in (r["permissions"] or [])
        wants_it = r["name"] in desired
        if wants_it and not has_it:
            await execute(
                "UPDATE roles SET permissions = array_append(permissions, $1) "
                "WHERE id = $2 AND NOT $1 = ANY(permissions)",
                intent_key, r["id"], source_key=source_key
            )
        elif has_it and not wants_it:
            await execute(
                "UPDATE roles SET permissions = array_remove(permissions, $1) WHERE id = $2",
                intent_key, r["id"], source_key=source_key
            )


async def publish_draft(draft: dict, org_id: str, source_key: str = "platform") -> dict:
    """
    Publish a workflow_drafts row to the live workflows table.
    Returns {"published": True, "intent_key": ..., "is_new": bool}
    Raises ValueError if the draft is not ready_for_review, or if config is
    inconsistent (see workflow_validator.validate_workflow_config).
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
        org_id, draft["intent_key"], source_key=source_key
    )
    new_version = (existing["version"] + 1) if existing else 1

    # NOTE: adapter_method / trigger_patterns are NOT real columns on
    # workflows in either org's database — checked both orgs' actual
    # CREATE TABLE definitions. They were carried forward from older legacy
    # code that referenced them, but this INSERT had literally never been
    # executed before this session (publish_draft was dead code), so the
    # mismatch was never caught until it ran for the first time live:
    # UndefinedColumnError: column "adapter_method" of relation "workflows"
    # does not exist. Do not add them back without adding the columns first.
    row = await fetch_one("""
        INSERT INTO workflows (
            org_id, name, intent_key, description, workflow_type,
            training_phrases, entity_schema, calc_rules, steps,
            sql_template, sql_params_order, response_format,
            business_glossary, llm_system_prompt, pdf_config,
            response_template, otp_required, otp_threshold, approval_threshold,
            gates,
            version, is_active,
            slash_command, command_description, menu_section
        ) VALUES (
            $1,$2,$3,$4,$5,
            $6::jsonb,$7::jsonb,$8::jsonb,$9::jsonb,
            $10,$11::jsonb,$12,
            $13::jsonb,$14,$15::jsonb,
            $16,$17,$18,$19,
            $20::jsonb,
            $21,true,
            $22,$23,$24
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
            gates               = EXCLUDED.gates,
            version             = EXCLUDED.version,
            is_active           = true,
            slash_command       = EXCLUDED.slash_command,
            command_description = EXCLUDED.command_description,
            menu_section        = EXCLUDED.menu_section
        RETURNING id
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
        _j(draft.get("gates"), "[]"),
        new_version,
        draft.get("slash_command"),
        draft.get("command_description"),
        draft.get("menu_section") or "other",
        source_key=source_key
    )
    workflow_id = row["id"]

    # granted_roles is a text[] column (asyncpg decodes arrays natively,
    # unlike jsonb — no _parse_jsonb needed here).
    granted_roles = draft.get("granted_roles") or []
    await sync_role_grants(draft["intent_key"], org_id, granted_roles, source_key)

    # Mark draft as published
    await execute(
        "UPDATE workflow_drafts SET status = 'published', published_workflow_id = $2, updated_at = now() WHERE id = $1",
        draft["id"], workflow_id, source_key=source_key
    )

    return {
        "published": True,
        "intent_key": draft["intent_key"],
        "workflow_id": str(workflow_id),
        "is_new": existing is None,
        "version": new_version,
    }
