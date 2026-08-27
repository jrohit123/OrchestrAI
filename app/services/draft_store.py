from app.db import fetch_one, execute
import json

async def get_active_draft(org_id: str, user_id: str, source_key: str) -> dict | None:
    row = await fetch_one("""
        SELECT * FROM user_drafts
        WHERE org_id=$1 AND user_id=$2
          AND stage NOT IN ('done','cancelled') AND expires_at > now()
    """, org_id, user_id, source_key=source_key)
    return dict(row) if row else None

async def upsert_draft(org_id, user_id, intent_key, fields: dict,
                       stage="collecting", summary: str | None = None, source_key: str = None,
                       reset_fields: bool = False):
    """
    reset_fields=True  → replace fields wholesale (use when switching intent)
    reset_fields=False → merge into existing fields (normal slot filling)
    """
    if not source_key:
        raise ValueError("upsert_draft: source_key is required")
    if not isinstance(fields, dict):
        raise TypeError(f"upsert_draft: fields must be a dict, got {type(fields).__name__}")
    await execute("""
        INSERT INTO user_drafts (org_id, user_id, intent_key, fields, stage,
                                 conversation_summary, expires_at)
        VALUES ($1,$2,$3,$4::jsonb,$5,$6, now() + interval '24 hours')
        ON CONFLICT (org_id, user_id) WHERE stage NOT IN ('done','cancelled')
        DO UPDATE SET
            -- D1: intent_key MUST follow the workflow the user is now running.
            intent_key = EXCLUDED.intent_key,
            -- D1: switching intent must not inherit the old workflow's fields.
            fields = CASE
                       WHEN user_drafts.intent_key IS DISTINCT FROM EXCLUDED.intent_key
                            OR $8::boolean
                       THEN EXCLUDED.fields
                       ELSE user_drafts.fields || EXCLUDED.fields
                     END,
            stage = EXCLUDED.stage,
            conversation_summary = COALESCE(EXCLUDED.conversation_summary,
                                            user_drafts.conversation_summary),
            updated_at = now(),
            -- D2: an actively-used draft must not silently expire.
            expires_at = now() + interval '24 hours'
    """, org_id, user_id, intent_key, json.dumps(fields), stage, summary,
         source_key, reset_fields, source_key=source_key)

async def close_draft(org_id, user_id, final_stage: str, source_key: str):
    await execute("""
        UPDATE user_drafts SET stage=$3, updated_at=now(), expires_at=now()
        WHERE org_id=$1 AND user_id=$2 AND stage NOT IN ('done','cancelled')
    """, org_id, user_id, final_stage, source_key=source_key)
