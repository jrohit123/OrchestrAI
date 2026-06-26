"""
DEPRECATED — routing uses message_router.py (LLM + DB workflows).
Kept only so old imports do not break.
"""
from app.services.message_router import invalidate_router_cache


def invalidate_workflow_cache(org_id: str = None):
    invalidate_router_cache(org_id)
