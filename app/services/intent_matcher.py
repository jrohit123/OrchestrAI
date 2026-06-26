"""
Intent Matcher — workflow-based routing engine.
Replaces per-query LLM intent classification for matched workflows.
Zero LLM cost when keyword match is high-confidence.
"""
import re
import json
from typing import Optional
from openai import AsyncOpenAI
from app.db import fetch_all
import os

_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ── In-memory workflow cache ────────────────────────────────────────────────
# Reloaded when workflows are created/updated. Not persistent across restarts.
_workflow_cache: dict[str, list[dict]] = {}   # org_id → workflow list


async def _load_workflows(org_id: str) -> list[dict]:
    """Load all active workflows for org. Cached per org."""
    if org_id in _workflow_cache:
        return _workflow_cache[org_id]

    rows = await fetch_all("""
        SELECT intent_key, name, workflow_type,
               training_phrases, entity_schema, sql_template,
               sql_params_order, response_format, business_glossary,
               llm_system_prompt, adapter_method, steps,
               otp_required, otp_threshold, approval_threshold, description
        FROM workflows
        WHERE org_id = $1 AND is_active = true
          AND intent_key != 'weekly_dues_report'
        ORDER BY name
    """, org_id)

    workflows = []
    for r in rows:
        w = dict(r)
        # Parse jsonb fields
        for field in ("training_phrases", "entity_schema", "sql_params_order",
                      "business_glossary"):
            if isinstance(w.get(field), str):
                try:
                    w[field] = json.loads(w[field])
                except Exception:
                    w[field] = [] if field in ("training_phrases", "sql_params_order") else {}
        workflows.append(w)

    _workflow_cache[org_id] = workflows
    return workflows


def invalidate_workflow_cache(org_id: str):
    """Call after any workflow create/update/delete."""
    _workflow_cache.pop(org_id, None)


def _normalize(text: str, glossary: dict) -> str:
    """Apply glossary substitutions and lowercase."""
    t = text.lower().strip()
    for term, replacement in (glossary or {}).items():
        t = t.replace(term.lower(), replacement.lower())
    return t


def _extract_keywords(phrase: str) -> set[str]:
    """Strip slot tokens and return meaningful words from a training phrase."""
    # Remove {slot_name} tokens
    cleaned = re.sub(r'\{[^}]+\}', '', phrase)
    # Tokenize and filter short/common words
    stopwords = {'ka', 'ki', 'ke', 'hai', 'kya', 'me', 'ko', 'se', 'is', 'the',
                 'a', 'an', 'for', 'of', 'in', 'to', 'how', 'much', 'many'}
    words = {w for w in re.findall(r'\w+', cleaned.lower()) if len(w) > 2 and w not in stopwords}
    return words


def _score_workflow(message_tokens: set[str], workflow: dict) -> float:
    """Score how well a message matches a workflow's training phrases."""
    best_score = 0.0
    phrases = workflow.get("training_phrases") or []

    for phrase in phrases:
        phrase_keywords = _extract_keywords(phrase)
        if not phrase_keywords:
            continue
        # Jaccard-like: intersection / phrase size
        overlap = len(message_tokens & phrase_keywords)
        score = overlap / len(phrase_keywords)
        best_score = max(best_score, score)

    return best_score


def _extract_entities(message: str, entity_schema: dict, glossary: dict, workflow: dict) -> dict:
    """
    Extract entity values from message using workflow's entity_schema.
    This is a best-effort extraction — the LLM fallback handles complex cases.
    """
    normalized = _normalize(message, glossary)
    entities = {}

    for field, spec in (entity_schema or {}).items():
        match_type = spec.get("match", "ILIKE")
        entity_type = spec.get("type", "string")

        if entity_type == "integer":
            m = re.search(r'\b(\d+)\b', normalized)
            if m:
                entities[field] = int(m.group(1))
            elif spec.get("default") is not None:
                entities[field] = spec["default"]

        elif entity_type == "float":
            m = re.search(r'\b(\d+(?:\.\d+)?)\b', normalized)
            if m:
                entities[field] = float(m.group(1))

        elif field == "status":
            # Status extraction: look for known status words
            known_statuses = {
                "ready": "ready", "delivered": "delivered",
                "production": "in_production", "in_production": "in_production",
                "quality": "quality_check", "confirmed": "confirmed",
                "pending": "pending", "overdue": "overdue", "paid": "paid"
            }
            for word, status in known_statuses.items():
                if word in normalized:
                    entities[field] = status
                    break

        elif field == "metal_type":
            for metal in ["22kt", "18kt", "24kt", "silver", "platinum", "gold"]:
                if metal in normalized:
                    entities[field] = metal
                    break

        else:
            # Generic text entity — extract proper nouns from original message
            words = re.findall(r'[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*', message)
            if words:
                # Take longest match as most likely to be a proper noun
                entities[field] = max(words, key=len)
            else:
                # Try common proper-noun patterns in lowercased Hinglish context
                # Remove known trigger words and take remainder
                trigger_words = _extract_keywords(
                    " ".join(workflow.get("training_phrases", []))
                ) if isinstance(workflow, dict) else set()
                remainder_words = [
                    w for w in message.split()
                    if w.lower() not in trigger_words and len(w) > 2
                ]
                if remainder_words:
                    entities[field] = " ".join(remainder_words[:3])

    # Apply wildcard formatting for ILIKE fields
    for field, spec in (entity_schema or {}).items():
        if field in entities and spec.get("format") == "wildcard":
            val = str(entities[field])
            if not val.startswith("%"):
                entities[field] = f"%{val}%"

    return entities


async def _llm_tiebreaker(
    message: str,
    candidates: list[dict],
    org_name: str,
    user_role: str
) -> Optional[dict]:
    """
    When keyword matching is ambiguous, use LLM to pick the correct workflow.
    Uses each candidate workflow's own llm_system_prompt.
    Much cheaper than full intent analysis — only comparing N workflows.
    """
    candidate_list = "\n".join(
        f"{i+1}. [{w['intent_key']}] {w['name']}: {w.get('description','')}"
        for i, w in enumerate(candidates)
    )

    prompt = f"""User sent this message to a WhatsApp ERP bot for {org_name}:
"{message}"

User role: {user_role}

Choose the SINGLE best matching workflow from these options:
{candidate_list}

Return ONLY JSON: {{"intent_key": "chosen_intent_key", "confidence": 0.0}}
If none fit well, return {{"intent_key": null, "confidence": 0.0}}"""

    resp = await _client.chat.completions.create(
        model="gpt-4o-mini",
        max_tokens=100,
        temperature=0,
        messages=[{"role": "user", "content": prompt}]
    )
    raw = resp.choices[0].message.content.strip()
    try:
        result = json.loads(raw)
        chosen_key = result.get("intent_key")
        if chosen_key:
            for w in candidates:
                if w["intent_key"] == chosen_key:
                    return w
    except Exception:
        pass
    return None


async def match_intent(
    message: str,
    org_id: str,
    org_name: str,
    user_role: str
) -> dict:
    """
    Main entry point. Matches message to a workflow or returns no_match.

    Returns:
      {
        "matched": True/False,
        "workflow": <workflow dict> or None,
        "entities": <extracted entities dict>,
        "confidence": float,
        "method": "keyword" | "llm_tiebreaker" | "no_match"
      }
    """
    workflows = await _load_workflows(org_id)
    if not workflows:
        return {"matched": False, "workflow": None, "entities": {}, "confidence": 0.0, "method": "no_match"}

    # Tokenize message
    msg_tokens = set(re.findall(r'\w+', message.lower())) - \
                 {'ka', 'ki', 'ke', 'hai', 'the', 'a', 'an', 'is', 'for', 'of', 'in'}

    # Score all workflows
    scored = [(w, _score_workflow(msg_tokens, w)) for w in workflows]
    scored.sort(key=lambda x: x[1], reverse=True)

    top_workflow, top_score = scored[0] if scored else (None, 0.0)

    # High confidence: route directly
    HIGH_CONFIDENCE = 0.6
    AMBIGUOUS_ZONE  = 0.3

    if top_score >= HIGH_CONFIDENCE:
        entities = _extract_entities(message, top_workflow.get("entity_schema", {}),
                                     top_workflow.get("business_glossary", {}),
                                     top_workflow)
        return {
            "matched":    True,
            "workflow":   top_workflow,
            "entities":   entities,
            "confidence": top_score,
            "method":     "keyword"
        }

    # Ambiguous: gather candidates and use LLM tiebreaker
    if top_score >= AMBIGUOUS_ZONE:
        candidates = [w for w, s in scored if s >= AMBIGUOUS_ZONE][:4]
        chosen = await _llm_tiebreaker(message, candidates, org_name, user_role)
        if chosen:
            entities = _extract_entities(message, chosen.get("entity_schema", {}),
                                         chosen.get("business_glossary", {}),
                                         chosen)
            return {
                "matched":    True,
                "workflow":   chosen,
                "entities":   entities,
                "confidence": top_score,
                "method":     "llm_tiebreaker"
            }

    # No match — caller falls back to unconstrained general_read
    return {"matched": False, "workflow": None, "entities": {}, "confidence": top_score, "method": "no_match"}
