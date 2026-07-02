"""
calc_engine.py — Deterministic, sandboxed expression evaluator for workflow calc_rules.

No eval(). No domain knowledge. No hardcoded field names.
Works for any industry — gst_rate, commission_pct, discount_pct, whatever.
The workflow's calc_rules reference whatever columns this org's orgs table has.
"""
from simpleeval import EvalWithCompoundTypes, InvalidExpression

_ALLOWED_FUNCTIONS = {
    "round":       round,
    "abs":         abs,
    "min":         min,
    "max":         max,
    "sum_field":   lambda items, field: sum(float(i.get(field) or 0) for i in (items or [])),
    "count_field": lambda items: len(items or []),
}


class CalcError(Exception):
    pass


def _eval(expr: str, names: dict):
    """Evaluate an expression safely."""
    ev = EvalWithCompoundTypes(names=names, functions=_ALLOWED_FUNCTIONS)
    return ev.eval(expr)


def compute_item_rules(item_rules: dict, item: dict, context: dict) -> dict:
    """
    Apply per-line-item calc_rules to a single item dict.
    `context` = org-level values this workflow's rules reference.
    The engine has no opinion on what those values are.
    """
    if not item_rules:
        return dict(item)
    names = {**context, **{k: v for k, v in item.items() if v is not None}}
    out = dict(item)
    for field, expr in item_rules.items():
        try:
            result = _eval(expr, names)
            out[field] = round(result, 2) if isinstance(result, float) else result
            names[field] = out[field]
        except (InvalidExpression, ZeroDivisionError, TypeError, KeyError) as e:
            raise CalcError(f"item_rules[{field}] '{expr}' failed on item {item}: {e}")
    return out


def compute_aggregate_rules(aggregate_rules: dict, fields: dict, context: dict) -> dict:
    """
    Workflow-level rules that see the whole draft (e.g. grand total from items).
    """
    if not aggregate_rules:
        return {}
    names = {**context, **{k: v for k, v in fields.items() if v is not None}}
    out = {}
    for field, expr in aggregate_rules.items():
        try:
            result = _eval(expr, names)
            out[field] = round(result, 2) if isinstance(result, float) else result
            names[field] = out[field]
        except (InvalidExpression, ZeroDivisionError, TypeError, KeyError) as e:
            raise CalcError(f"aggregate_rules[{field}] '{expr}' failed: {e}")
    return out


def compute_draft(calc_rules: dict, fields: dict, context: dict) -> dict:
    """
    Full pass: recompute item fields, then aggregate fields.
    Never mutates input dicts. Returns a new fields dict with computed values filled in.
    """
    if not calc_rules:
        return dict(fields)

    item_rules      = calc_rules.get("item_rules") or {}
    aggregate_rules = calc_rules.get("aggregate_rules") or {}

    new_fields = dict(fields)

    if item_rules and isinstance(fields.get("items"), list):
        new_fields["items"] = [
            compute_item_rules(item_rules, item, context)
            for item in fields["items"]
        ]

    if aggregate_rules:
        new_fields.update(compute_aggregate_rules(aggregate_rules, new_fields, context))

    return new_fields
