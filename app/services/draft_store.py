from app.db import fetch_one, execute
import json

async def get_active_draft(org_id: str, user_id: str) -> dict | None:
    row = await fetch_one("""
        SELECT * FROM user_drafts
        WHERE org_id=$1 AND user_id=$2
          AND stage NOT IN ('done','cancelled') AND expires_at > now()
    """, org_id, user_id)
    return dict(row) if row else None

async def upsert_draft(org_id, user_id, intent_key, fields: dict,
                       stage="collecting", summary: str | None = None):
    if not isinstance(fields, dict):
        raise TypeError(f"upsert_draft: fields must be a dict, got {type(fields).__name__}")
    await execute("""
        INSERT INTO user_drafts (org_id, user_id, intent_key, fields, stage, conversation_summary)
        VALUES ($1,$2,$3,$4::jsonb,$5,$6)
        ON CONFLICT (org_id, user_id) WHERE stage NOT IN ('done','cancelled')
        DO UPDATE SET fields = user_drafts.fields || EXCLUDED.fields,
                      stage = EXCLUDED.stage,
                      conversation_summary = COALESCE(EXCLUDED.conversation_summary,
                                                      user_drafts.conversation_summary),
                      updated_at = now()
    """, org_id, user_id, intent_key, json.dumps(fields), stage, summary)

async def close_draft(org_id, user_id, final_stage: str):
    await execute("""
        UPDATE user_drafts SET stage=$3, updated_at=now()
        WHERE org_id=$1 AND user_id=$2 AND stage NOT IN ('done','cancelled')
    """, org_id, user_id, final_stage)
