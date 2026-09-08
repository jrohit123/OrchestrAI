"""
json_utils.py — Shared JSON/JSONB parsing helpers.

asyncpg returns jsonb columns as raw JSON text, not a parsed object — there's
no jsonb codec registered in app/db.py — so anything read via fetch_all/
fetch_one needs to be parsed before being iterated, indexed, or handed to a
JSON API response as if it were already a list/dict. This module was
extracted from six near-identical copies of the same function (agent.py,
step_interpreter.py, workflow_builder_agent.py, qa_verifier.py,
vocabulary.py, admin.py) that had drifted slightly from each other — a fix
to one wasn't reaching the other five.
"""
import json


def parse_jsonb(val, default=None):
    """
    Parse a value that may be raw JSON text (from an unconverted jsonb
    column), already-parsed (dict/list), or None.
    """
    if val is None:
        return default
    if isinstance(val, str):
        try:
            return json.loads(val)
        except Exception:
            return default
    return val
