"""
vocabulary.py — Per-org deterministic keyword vocabulary for control-flow
matching (confirm/cancel/self-reference) that must never depend on an LLM.

These are NOT LLM prompt text — they're exact string matches used by
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
        "retry_words": ["retry", "phir se", ...],
        "filler_words": ["please", "thanks", "ji", "save it", ...]
    }}

An org with no vocabulary configured for a given key gets an empty set for
that key — the deterministic shortcut simply never matches for it (no
crash, no guessed English/Hindi words); the message just falls through to
the normal LLM agent turn instead. See migrations/seed_vocabulary.sql for
the one-time data seed that gives existing orgs their current behaviour, and
migrations/core/core-0012_filler_words.sql for the filler words.
"""

import re

from app.db import fetch_one
from app.services.json_utils import parse_jsonb as _parse_jsonb

_VOCAB_KEYS = (
    "confirm_words",
    "cancel_words",
    "cancel_tokens",
    "self_reference_words",
    "retry_words",
    "filler_words",
)

# Punctuation that may sit around a word: "Yes!", "ok.", "(yes)". A slash is NOT in the list, so
# "/cancel" stays one word.
_EDGE = "\"'`\u00b4\u2018\u2019\u201c\u201d.,;:!?\u00a1\u00bf\u2026()[]{}<>*_~|\\-\u2013\u2014"
# Marks that change how an emoji looks but not what it says (skin colour, variation selector, joiner)
_EMOJI_NOISE = re.compile("[\ufe0f\u200d\U0001f3fb-\U0001f3ff]")


def _tokens(text: str) -> tuple[str, ...]:
    """The words of a message, lower case, without the punctuation around them."""
    text = _EMOJI_NOISE.sub("", (text or "").lower())
    return tuple(chunk for chunk in (c.strip(_EDGE) for c in text.split()) if chunk)


def matches_vocab(
    text: str, words: frozenset, fillers: frozenset = frozenset()
) -> bool:
    """
    True when the WHOLE message is made of `words` (a word or a phrase such as "go ahead"), at least
    one of them, with `fillers` (polite words such as "please", "thanks", "ji", "save it") allowed
    around them and punctuation ignored. So "yes", "Yes!", "ok thanks", "yes save it", "haan ji" and
    "yes yes" match, but "yes but make it 5000", "ok no wait", "no problem, go ahead" and
    "yesterday" do not: those say more than yes or no, and go to the agent as a correction.

    Deterministic (no LLM call), and tolerant of the polite words people really type. The lists
    come from the organisation (orgs.settings.vocabulary); there is no default list in the code.
    """
    if not words:
        return False
    tokens = _tokens(text)
    if not tokens:
        return False
    main = {t for t in (_tokens(w) for w in words) if t}
    extra = {t for t in (_tokens(f) for f in fillers) if t} - main
    if not main:
        return False
    # walk the message left to right; a state is (position reached, a word from `words` was used)
    seen = {(0, False)}
    todo = [(0, False)]
    while todo:
        i, used = todo.pop()
        if i == len(tokens):
            if used:
                return True
            continue
        for phrase, is_word in [(p, True) for p in main] + [(p, False) for p in extra]:
            end = i + len(phrase)
            if tokens[i:end] == phrase and (end, used or is_word) not in seen:
                seen.add((end, used or is_word))
                todo.append((end, used or is_word))
    return False


_cache: dict[str, dict] = {}  # org_id -> {key: frozenset}


async def get_vocabulary(org_id: str, source_key: str) -> dict:
    """
    Returns {"confirm_words", "cancel_words", "cancel_tokens",
    "self_reference_words", "retry_words", "filler_words"} -> frozenset, entirely from
    orgs.settings->'vocabulary' for this org. A key with nothing configured
    resolves to an empty frozenset, not a guessed default.

    Cached per org for the process lifetime (same convention as agent.py's
    schema cache) — call invalidate_vocabulary_cache() after changing
    orgs.settings if a running process needs to pick the change up without
    a restart.
    """
    if org_id in _cache:
        return _cache[org_id]

    row = await fetch_one(
        "SELECT settings FROM orgs WHERE id = $1", org_id, source_key=source_key
    )
    org_vocab = (_parse_jsonb(row["settings"], {}) if row else {}).get(
        "vocabulary"
    ) or {}

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
