"""
workflow_publisher.py — Promotes a workflow_drafts row to the live workflows table.

Uses ON CONFLICT DO UPDATE so publishing an existing workflow updates it in-place.
The old row is NOT versioned (versions table deferred) — the draft row itself
stays as the history with status='published'.
"""

import json

from app.db import execute, fetch_all, fetch_one
from app.logging_config import get_context_logger
from app.services.json_utils import parse_jsonb as _parse_jsonb

logger = get_context_logger(__name__)


class PublishConflict(Exception):
    """
    Raised when a draft's based_on_version no longer matches the live
    workflow's current version — someone else published a change to this
    same workflow while this draft was being edited. The classic lost-update
    problem: without this check, whichever admin clicks Publish/Save second
    would silently overwrite the first admin's change with no trace. Caught
    in admin.py's publish endpoint and surfaced as a 409, never auto-resolved
    here — see workflow_publisher module docs for why this doesn't attempt
    an automatic merge.
    """

    def __init__(self, intent_key: str, current_version: int, based_on_version: int):
        self.intent_key = intent_key
        self.current_version = current_version
        self.based_on_version = based_on_version
        super().__init__(
            f"'{intent_key}' is now at v{current_version}, but this draft was "
            f"based on v{based_on_version} — someone else published a change "
            f"since this draft was started."
        )


def _j(val, default=None):
    """Safely serialize a value to JSON string for DB binding."""
    if val is None:
        return default
    if isinstance(val, (dict, list)):
        return json.dumps(val)
    return val


def extract_required_permissions(steps: list) -> set:
    """Every permission string a workflow's steps can require via a
    require_permission op — both `any_of` entries and every value in `map`
    — independent of the workflow's own top-level intent_key permission.

    A workflow granting a role access via intent_key alone doesn't mean the
    role can actually get through the workflow: a require_permission step
    partway through (e.g. mapping action="close" -> "close_case") can gate
    on a DIFFERENT, finer-grained permission that nothing else grants. See
    sync_role_grants below — this is what lets it grant the whole set a
    role needs to actually complete the workflow, not just trigger it."""
    perms = set()
    for step in steps or []:
        if isinstance(step, str):
            try:
                step = json.loads(step)
            except Exception as e:
                logger.debug(
                    f"extract_required_permissions: skipping unparseable step: {e}"
                )
                continue
        if not isinstance(step, dict) or step.get("op") != "require_permission":
            continue
        params = step.get("params") or {}
        perms.update(params.get("any_of") or [])
        perms.update((params.get("map") or {}).values())
    return perms


def _referenced_tables(entity_schema: dict) -> set:
    """Every real DB table a workflow's entity_schema fields read from or
    write to — skips computed fields (no table of their own) and json_key/
    custom_fields fields (no 'table', by design — see workflow_compiler.txt).
    Covers item_schema-nested fields too."""
    tables = set()
    for spec in (entity_schema or {}).values():
        if not isinstance(spec, dict):
            continue
        if spec.get("table"):
            tables.add(spec["table"])
        item_schema = (
            (spec.get("item_schema") or {}) if spec.get("type") == "array" else {}
        )
        for ispec in item_schema.values():
            if isinstance(ispec, dict) and ispec.get("table"):
                tables.add(ispec["table"])
    return tables


def _referenced_entity_types(entity_schema: dict) -> set:
    """Every entity_records 'entity_type' a workflow's entity_schema fields
    address (see the generic-entity convention: a field marks itself with
    "entity_type" whether it maps a real entity_records column or nests
    under custom_fields via json_key — unlike the per-table custom_fields
    convention, json_key fields here still carry "entity_type" since it's
    the only thing that says which slice of the one shared table they
    belong to). Covers item_schema-nested fields too."""
    types = set()
    for spec in (entity_schema or {}).values():
        if not isinstance(spec, dict):
            continue
        if spec.get("entity_type"):
            types.add(spec["entity_type"])
        item_schema = (
            (spec.get("item_schema") or {}) if spec.get("type") == "array" else {}
        )
        for ispec in item_schema.values():
            if isinstance(ispec, dict) and ispec.get("entity_type"):
                types.add(ispec["entity_type"])
    return types


async def sync_role_grants(
    intent_key: str,
    org_id: str,
    desired_roles: list[str],
    source_key: str,
    entity_schema: dict | str | None = None,
    steps: list | str | None = None,
) -> None:
    """
    Set a workflow's role access to EXACTLY desired_roles — grants roles that
    should now have it, revokes roles that shouldn't. Unlike the old
    append-only logic (array_append with no removal path), this has to
    actually revoke now: a role gathered via chat one turn can be dropped by
    the admin ("actually only staff, not branch_manager") on a later turn,
    via set_roles replacing the whole list — publishing has to make the live
    grants match that replacement, not just accumulate onto it.

    Also grants readable_tables for every table this workflow's
    entity_schema actually touches, for each role being granted the
    workflow. roles.permissions ("can trigger this workflow") and
    roles.readable_tables ("can this role's queries even see this table")
    are two independent arrays — publishing previously only ever synced the
    first one. Reproduced live: get_meeting_records was correctly granted
    to owner/tenant (they could trigger it), but owner/tenant's
    readable_tables never included meetings/meeting_minutes, so the LLM
    never saw those tables in its schema and every lookup silently failed
    with a sanitized "couldn't find that information" — having the
    workflow permission gave no hint the underlying table access was still
    missing. Only ever adds tables, never removes — a role losing this one
    workflow shouldn't lose table access another granted workflow still
    needs.

    Also grants every fine-grained permission this workflow's steps require
    via require_permission (see extract_required_permissions) — not just
    intent_key. Ticking a role on here means "this role can actually use
    this workflow end to end", not just "can trigger it and then hit a
    permission wall on some internal step". Reproduced live: godrej's
    assign_case workflow gates its "close" action behind a separate
    close_case permission that no role had ever been granted — every role
    including admin could trigger the workflow but none could actually
    close a case, and the failure surfaced to the user as a misleading
    "something went wrong writing to the database" message instead of a
    permission error. Revoking is the mirror case and needs care: a
    sub-permission is only removed from a role if no OTHER active workflow
    that role still has access to also requires it — unticking this
    workflow must not collaterally break a different workflow that happens
    to share the same permission string.
    """
    tables_needed = _referenced_tables(_parse_jsonb(entity_schema, {}) or {})
    entity_types_needed = _referenced_entity_types(_parse_jsonb(entity_schema, {}) or {})
    if entity_types_needed:
        # entity_records is one physical table shared by every generic
        # entity_type — readable_tables alone can't tell them apart (see
        # check_entity_records_access in query_engine.py), so a workflow
        # touching any entity_type always needs the table grant too.
        tables_needed = tables_needed | {"entity_records"}
    own_sub_perms = extract_required_permissions(_parse_jsonb(steps, []) or [])
    required_perms = {intent_key} | own_sub_perms

    all_roles = await fetch_all(
        "SELECT id, name, permissions, readable_tables, readable_entity_types "
        "FROM roles WHERE org_id = $1",
        org_id,
        source_key=source_key,
    )

    # Every OTHER active workflow's (intent_key -> its own required sub-perms),
    # to know what a role must keep even after losing access to THIS one.
    other_workflows = await fetch_all(
        "SELECT intent_key, steps FROM workflows "
        "WHERE org_id = $1 AND is_active = true AND intent_key != $2",
        org_id,
        intent_key,
        source_key=source_key,
    )
    other_required: dict[str, set] = {
        row["intent_key"]: {row["intent_key"]}
        | extract_required_permissions(_parse_jsonb(row["steps"], []) or [])
        for row in other_workflows
    }

    desired = set(desired_roles or [])
    for r in all_roles:
        role_perms = set(r["permissions"] or [])
        wants_it = r["name"] in desired

        # What this role would still need even without THIS workflow: the
        # union of required perms for every other active workflow the role
        # currently has intent_key access to.
        still_needed: set = set()
        for other_intent_key, perms in other_required.items():
            if other_intent_key in role_perms:
                still_needed |= perms

        if wants_it:
            to_add = required_perms - role_perms
            if to_add:
                await execute(
                    "UPDATE roles SET permissions = permissions || $1::text[] WHERE id = $2",
                    list(to_add),
                    r["id"],
                    source_key=source_key,
                )
        else:
            to_remove = (required_perms & role_perms) - still_needed
            for perm in to_remove:
                await execute(
                    "UPDATE roles SET permissions = array_remove(permissions, $1) WHERE id = $2",
                    perm,
                    r["id"],
                    source_key=source_key,
                )

        if wants_it and tables_needed:
            missing = tables_needed - set(r["readable_tables"] or [])
            if missing:
                await execute(
                    "UPDATE roles SET readable_tables = readable_tables || $1::text[] WHERE id = $2",
                    list(missing),
                    r["id"],
                    source_key=source_key,
                )

        if wants_it and entity_types_needed:
            missing_types = entity_types_needed - set(r["readable_entity_types"] or [])
            if missing_types:
                await execute(
                    "UPDATE roles SET readable_entity_types = readable_entity_types || $1::text[] WHERE id = $2",
                    list(missing_types),
                    r["id"],
                    source_key=source_key,
                )


async def set_workflow_active(
    workflow_id: str, new_active: bool, source_key: str
) -> bool:
    """
    Flip a live workflow's is_active and keep role grants in step with it —
    deactivating a workflow through the admin panel used to just flip the
    column, leaving every role that had the workflow's intent_key (and its
    require_permission sub-perms, e.g. assign_case's close_case/add_case_comment)
    still holding those permissions for a workflow nobody could actually
    reach anymore. Same staleness bug sync_role_grants was built to prevent
    at publish time, just reached through a different door.

    Deactivating revokes via sync_role_grants(desired_roles=[]) — identical
    to what delete_workflow already does, minus the delete.

    Reactivating restores whatever roles last had it. granted_roles isn't
    stored on the live workflows row itself (see publish_draft), so the only
    record of "who had it before it was turned off" is this workflow's most
    recent workflow_versions snapshot.
    """
    row = await fetch_one(
        "SELECT org_id, intent_key, steps, entity_schema, is_active "
        "FROM workflows WHERE id = $1",
        workflow_id,
        source_key=source_key,
    )
    if not row:
        raise ValueError("Workflow not found")
    if row["is_active"] == new_active:
        return new_active

    if new_active:
        last = await fetch_one(
            "SELECT granted_roles FROM workflow_versions "
            "WHERE workflow_id = $1 ORDER BY version DESC LIMIT 1",
            workflow_id,
            source_key=source_key,
        )
        desired_roles = (last["granted_roles"] if last else None) or []
    else:
        desired_roles = []

    await sync_role_grants(
        row["intent_key"],
        str(row["org_id"]),
        desired_roles,
        source_key,
        entity_schema=row.get("entity_schema"),
        steps=row.get("steps"),
    )
    await execute(
        "UPDATE workflows SET is_active = $1 WHERE id = $2",
        new_active,
        workflow_id,
        source_key=source_key,
    )
    return new_active


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
            "Cannot publish — config is inconsistent:\n"
            + "\n".join(f"  • {p}" for p in problems)
        )

    # Belt-and-suspenders: compile_workflow_spec already dry-runs the query
    # (see workflow_compiler.dry_run_sql_template) inside its own retry loop,
    # but publish is the actual gate that writes to the live workflows table
    # — checked again here so a draft that reaches this function through any
    # other path (a resumed old draft, a direct edit) can't ship a query
    # that fails against the real schema.
    if draft.get("workflow_type") == "read" and draft.get("sql_template"):
        from app.services.json_utils import parse_jsonb
        from app.services.workflow_compiler import dry_run_sql_template

        sql_params_order = parse_jsonb(draft.get("sql_params_order"), []) or []
        dry_run_error = await dry_run_sql_template(
            draft["sql_template"], sql_params_order, org_id, source_key
        )
        if dry_run_error:
            raise ValueError(f"Cannot publish — {dry_run_error}")

    existing = await fetch_one(
        "SELECT id, version FROM workflows WHERE org_id = $1 AND intent_key = $2",
        org_id,
        draft["intent_key"],
        source_key=source_key,
    )

    # Optimistic concurrency: a draft copied from a live workflow (via
    # "Edit the logic" or resuming one) remembers which version it started
    # from. If the live version has moved on since, publishing here would
    # silently discard whatever the other admin changed — refuse instead,
    # same principle as a compare-and-swap.
    based_on = draft.get("based_on_version")
    if based_on is not None and existing and existing["version"] != based_on:
        raise PublishConflict(
            intent_key=draft["intent_key"],
            current_version=existing["version"],
            based_on_version=based_on,
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
    row = await fetch_one(
        """
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
        _j(draft.get("entity_schema"), "{}"),
        _j(draft.get("calc_rules"), "{}"),
        _j(draft.get("steps"), "[]"),
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
        source_key=source_key,
    )
    workflow_id = row["id"]

    # granted_roles is a text[] column (asyncpg decodes arrays natively,
    # unlike jsonb — no _parse_jsonb needed here).
    granted_roles = draft.get("granted_roles") or []
    await sync_role_grants(
        draft["intent_key"],
        org_id,
        granted_roles,
        source_key,
        entity_schema=draft.get("entity_schema"),
        steps=draft.get("steps"),
    )

    # Snapshot what just went live — the only history this workflow has.
    # Powers the "N changes vs live" diff view and the conflict message
    # above; not surfaced as a browsable history/rollback UI (yet).
    await execute(
        """
        INSERT INTO workflow_versions (
            workflow_id, org_id, version, intent_key, name,
            entity_schema, gates, granted_roles, steps, calc_rules,
            sql_template, slash_command, source_draft_id
        ) VALUES ($1,$2,$3,$4,$5,$6::jsonb,$7::jsonb,$8,$9::jsonb,$10::jsonb,$11,$12,$13)
    """,
        workflow_id,
        org_id,
        new_version,
        draft["intent_key"],
        draft.get("name"),
        _j(draft.get("entity_schema"), "{}"),
        _j(draft.get("gates"), "[]"),
        granted_roles,
        _j(draft.get("steps"), "[]"),
        _j(draft.get("calc_rules"), "{}"),
        draft.get("sql_template"),
        draft.get("slash_command"),
        draft["id"],
        source_key=source_key,
    )

    # Mark draft as published
    await execute(
        "UPDATE workflow_drafts SET status = 'published', published_workflow_id = $2, updated_at = now() WHERE id = $1",
        draft["id"],
        workflow_id,
        source_key=source_key,
    )

    return {
        "published": True,
        "intent_key": draft["intent_key"],
        "workflow_id": str(workflow_id),
        "is_new": existing is None,
        "version": new_version,
    }
