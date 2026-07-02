"""
qa_verifier.py — Deterministic verification layer (the QA agent).

Not an LLM call. LLMs cannot reliably verify their own arithmetic.
Grounding is calc_engine + entity_schema — both pure data, both domain-agnostic.

Called:
  (a) right before confirm_action is shown to the user
  (b) right before step_interpreter executes

Returns verified fields with computed values overwritten from calc_rules.
The LLM's own arithmetic is discarded and recomputed from the authoritative rules.
"""
import json
from app.services.calc_engine import compute_draft, CalcError
from app.db import fetch_one

# Columns we never pass into calc_rules namespace (security + noise)
_ORG_EXCLUDED_COLS = {"id", "slug", "created_at", "is_active", "plan"}


class VerificationError(Exception):
    def __init__(self, missing_fields=None, invalid_fields=None, message=""):
        self.missing_fields  = missing_fields or []
        self.invalid_fields  = invalid_fields or []
        self.message         = message or "Draft failed verification"
        super().__init__(self.message)


def _parse_jsonb(val, default):
    if isinstance(val, str):
        try:
            return json.loads(val)
        except Exception:
            return default
    return val if val is not None else default


async def _build_context(org_id: str) -> dict:
    """
    Return ALL org-level columns generically — not hardcoded to any business concept.
    Whatever calc_rules reference (gst_rate, commission_pct, exchange_rate…) is
    available here because it's just a column on orgs. The engine never special-cases any.
    """
    org = await fetch_one("SELECT * FROM orgs WHERE id = $1", org_id)
    if not org:
        return {}
    return {
        k: (float(v) if hasattr(v, '__float__') and not isinstance(v, str) else v)
        for k, v in dict(org).items()
        if k not in _ORG_EXCLUDED_COLS and v is not None
    }


def _validate_schema(entity_schema: dict, fields: dict) -> tuple[list, list]:
    """
    Check RAW (non-computed) required fields are present and typed correctly.
    Computed fields are skipped — they'll be filled by calc_engine.
    """
    missing, invalid = [], []

    for name, spec in entity_schema.items():
        # Skip fields the engine will compute — LLM doesn't need to provide them
        if spec.get("computed"):
            continue

        if name == "items" and spec.get("type") == "array":
            items = fields.get("items")
            if spec.get("required") and not items:
                missing.append("items")
                continue
            item_schema = spec.get("item_schema") or {}
            for idx, item in enumerate(items or []):
                for f_name, f_spec in item_schema.items():
                    if f_spec.get("computed"):
                        continue
                    val = item.get(f_name)
                    if f_spec.get("required") and val in (None, "", []):
                        missing.append(f"items[{idx}].{f_name}")
                    elif f_spec.get("type") in ("float", "integer") and val is not None:
                        try:
                            float(val)
                        except (TypeError, ValueError):
                            invalid.append(f"items[{idx}].{f_name}")
            continue

        val = fields.get(name)
        if spec.get("required") and val in (None, "", []):
            missing.append(name)
        elif spec.get("type") in ("float", "integer") and val is not None:
            try:
                float(val)
            except (TypeError, ValueError):
                invalid.append(name)

    return missing, invalid


async def verify_draft(workflow: dict, fields: dict, org_id: str) -> dict:
    """
    Validate and recompute a draft's fields.

    Returns the VERIFIED fields dict — raw inputs unchanged,
    computed fields overwritten from calc_rules (never from the LLM).

    Raises VerificationError if required fields are missing or malformed.
    """
    entity_schema = _parse_jsonb(workflow.get("entity_schema"), {})
    calc_rules    = _parse_jsonb(workflow.get("calc_rules"), {})

    missing, invalid = _validate_schema(entity_schema, fields)
    if missing or invalid:
        raise VerificationError(
            missing_fields=missing,
            invalid_fields=invalid,
            message=f"Missing: {missing}. Invalid: {invalid}."
        )

    if not calc_rules:
        return dict(fields)

    context = await _build_context(org_id)
    try:
        return compute_draft(calc_rules, fields, context)
    except CalcError as e:
        raise VerificationError(message=f"Could not calculate values: {e}")


def diff_for_audit(pre_fields: dict, verified_fields: dict) -> dict:
    """
    Returns a dict of {path: {was, corrected_to}} for every value the QA layer changed.
    Used for audit logging — proves the system caught and silently corrected an LLM mistake.
    """
    changes = {}

    def _walk(pre, post, path=""):
        if isinstance(post, dict):
            for k, v in post.items():
                _walk(
                    (pre or {}).get(k) if isinstance(pre, dict) else None,
                    v,
                    f"{path}.{k}" if path else k
                )
        elif isinstance(post, list):
            pre_list = pre if isinstance(pre, list) else []
            for i, v in enumerate(post):
                _walk(pre_list[i] if i < len(pre_list) else None, v, f"{path}[{i}]")
        else:
            if pre != post:
                changes[path] = {"was": pre, "corrected_to": post}

    _walk(pre_fields, verified_fields)
    return changes
