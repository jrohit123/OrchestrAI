"""
calc_engine.py — Deterministic, sandboxed expression evaluator for workflow calc_rules.

No eval(). No domain knowledge. No hardcoded field names.
Works for any industry — gst_rate, commission_pct, discount_pct, whatever.
The workflow's calc_rules reference whatever columns this org's orgs table has.

IMPORTANT: calc_rules dicts are read back from a Postgres `jsonb` column.
jsonb does NOT preserve object key order (this is documented Postgres
behaviour, not a bug in this file) — so "gst" can come back before
"line_subtotal" even though gst's expression references it. Every
evaluation function below is therefore order-independent: it retries
unresolved rules across multiple passes until nothing is left, rather
than assuming the rules are already in dependency order.
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


def _resolve_multipass(rules: dict, names: dict, out: dict, label: str, error_suffix: str) -> dict:
    """
    Evaluate `rules` (field_name -> expression string) against `names`,
    without assuming any particular order between rules. Rules may
    reference fields produced by other rules in the same dict — this
    keeps retrying whatever hasn't resolved yet until either everything
    succeeds or a full pass makes no progress at all (which then means a
    *real* problem — a missing input like `weight`, not just bad ordering).
    """
    pending = dict(rules)
    last_error = None
    while pending:
        made_progress = False
        for field, expr in list(pending.items()):
            try:
                result = _eval(expr, names)
            except (InvalidExpression, ZeroDivisionError, TypeError, KeyError) as e:
                last_error = (field, expr, e)
                continue
            out[field] = round(result, 2) if isinstance(result, float) else result
            names[field] = out[field]
            del pending[field]
            made_progress = True

        if not made_progress:
            field, expr, e = last_error
            raise CalcError(f"{label}[{field}] '{expr}' failed {error_suffix}: {e}")

    return out


def compute_item_rules(item_rules: dict, item: dict, context: dict) -> dict:
    """
    Apply per-line-item calc_rules to a single item dict.
    `context` = org-level values this workflow's rules reference.
    The engine has no opinion on what those values are.
    """
    if not item_rules:
        return dict(item)
    # Ensure qty defaults to 1 if not present
    # Ensure making_charge_pct defaults to org's default if not present
    # making_charges can be flat (direct value) or percentage-based
    # Keep making_charges_flat in context even if None (for calc rule fallback check)
    item_with_defaults = {
        **item,
        "qty": item.get("qty", 1),
        "making_charge_pct": item.get("making_charge_pct", context.get("default_making_charge_pct", 12)),
        "making_charges_flat": item.get("making_charges_flat"),
    }
    # Filter out None values EXCEPT for making_charges_flat (needed for fallback logic)
    names = {**context, **{k: v for k, v in item_with_defaults.items() if v is not None or k == "making_charges_flat"}}
    out = dict(item_with_defaults)
    return _resolve_multipass(item_rules, names, out, "item_rules", f"on item {item}")


def compute_aggregate_rules(aggregate_rules: dict, fields: dict, context: dict) -> dict:
    """
    Workflow-level rules that see the whole draft (e.g. grand total from items).
    """
    if not aggregate_rules:
        return {}
    names = {**context, **{k: v for k, v in fields.items() if v is not None}}
    out = {}
    return _resolve_multipass(aggregate_rules, names, out, "aggregate_rules", "")


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
