"""
vocabulary.py — Per-org deterministic keyword vocabulary for control-flow
matching (confirm/cancel/self-reference) that must never depend on an LLM.

These are NOT LLM prompt text — they're exact/token string matches used by
webhook.py's cancel gate and pending-action confirm/cancel checks, and by
step_interpreter's self-assignment shortcut. They have to resolve
deterministically before any LLM call happens, so they can't live in a
prompt file the way instructional text does.

Zero words live in this file. Everything comes from orgs.settings->'vocabulary'
— same JSONB config pattern already used for dashboard_stats and
case_reminders, so this needs no new table and no migration:

    {"vocabulary": {
        "confirm_words": ["yes", "haan", "ok", ...],
        "cancel_words": ["no", "nahi", "cancel", ...],
        "cancel_tokens": ["cancel", "/cancel", "stop", ...],
        "self_reference_words": ["myself", "me", "mujhe", ...],
        "retry_words": ["retry", "phir se", ...]
    }}

An org with no vocabulary configured for a given key gets an empty set for
that key — the deterministic shortcut simply never matches for it (no
crash, no guessed English/Hindi words); the message just falls through to
the normal LLM agent turn instead. See migrations/seed_vocabulary.sql for
the one-time data seed that gives existing orgs their current behaviour.
"""
import re
from app.db import fetch_one
from app.services.json_utils import parse_jsonb as _parse_jsonb

_VOCAB_KEYS = ("confirm_words", "cancel_words", "cancel_tokens", "self_reference_words", "retry_words")


def matches_vocab(text: str, words: frozenset) -> bool:
    """
    True if `text` STARTS WITH one of `words` as a whole token — e.g. "yes"
    matches "yes save it" and "yes, please" but not "yesterday". Deliberately
    NOT plain `text in words` (exact equality): that broke live — a real
    user replying "yes save it" to a pending confirmation didn't exactly
    equal "yes", failed the deterministic shortcut, fell through to the
    general LLM agent turn, and got stuck re-asking the same confirmation
    instead of ever executing. Still fully deterministic (no LLM call) —
    just tolerant of the word not being the ENTIRE message, which is how
    people actually type confirmations/cancellations/retries.
    """
    if not words:
        return False
    text = text.strip().lower()
    pattern = r'^(?:' + '|'.join(re.escape(w) for w in words) + r')\b'
    return bool(re.match(pattern, text))

_cache: dict[str, dict] = {}   # org_id -> {key: frozenset}


async def get_vocabulary(org_id: str, source_key: str) -> dict:
    """
    Returns {"confirm_words", "cancel_words", "cancel_tokens",
    "self_reference_words"} -> frozenset, entirely from
    orgs.settings->'vocabulary' for this org. A key with nothing configured
    resolves to an empty frozenset, not a guessed default.

    Cached per org for the process lifetime (same convention as agent.py's
    schema cache) — call invalidate_vocabulary_cache() after changing
    orgs.settings if a running process needs to pick the change up without
    a restart.
    """
    if org_id in _cache:
        return _cache[org_id]

    row = await fetch_one("SELECT settings FROM orgs WHERE id = $1", org_id, source_key=source_key)
    org_vocab = (_parse_jsonb(row["settings"], {}) if row else {}).get("vocabulary") or {}

    resolved = {
        key: frozenset(w.lower() for w in (org_vocab.get(key) or []))
        for key in _VOCAB_KEYS
    }

    _cache[org_id] = resolved
    return resolved


def invalidate_vocabulary_cache(org_id: str | None = None):
    if org_id:
        _cache.pop(org_id, None)
    else:
        _cache.clear()
