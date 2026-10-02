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

MONEY HANDLING: All monetary values use Decimal for precision.
Binary float rounding produces paisa drift that will not reconcile.
"""

import datetime as _dt
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal

# Register Decimal with simpleeval
from simpleeval import DEFAULT_FUNCTIONS, EvalWithCompoundTypes, InvalidExpression

DEFAULT_FUNCTIONS["Decimal"] = Decimal


def _due_from_tat(value, unit, start=None):
    # whole numbers reach formulas as Decimal (see _normalize_numbers) and
    # timedelta refuses Decimal, so hand it a float. `start` counts the time from
    # then (for example when the case was raised) instead of from now.
    span = unit if unit in ("minutes", "hours") else "days"
    base = (
        start if isinstance(start, _dt.datetime) else _dt.datetime.now(_dt.timezone.utc)
    )
    return base + _dt.timedelta(**{span: float(value)})


_ALLOWED_FUNCTIONS = {
    "round": lambda x, d=2: round(x, d),
    "abs": abs,
    "min": min,
    "max": max,
    "sum_field": lambda items, field: sum(
        Decimal(i.get(field) or 0) for i in (items or [])
    ),
    "count_field": lambda items: len(items or []),
    "Decimal": Decimal,
    "due_from_tat": _due_from_tat,
}


class CalcError(Exception):
    pass


def _normalize_numbers(d: dict) -> defaultdict:
    """
    Coerce every plain int/float leaf to Decimal before evaluation, and make
    the result a defaultdict(None) — a calc_rules expression referencing an
    optional field the current item/draft simply doesn't have (e.g. a
    fallback ternary like `x if x is not None else y` on a field this
    workflow's entity_schema marks optional) should see None, not blow up
    with NameNotDefined. simpleeval looks names up via __getitem__, so a
    defaultdict is all it takes — no per-field allowlist of "which names
    are allowed to be missing".

    Decimal coercion itself: inputs arrive as a mix of types by nature, not
    by mistake — asyncpg decodes a Postgres `numeric` column (e.g.
    orgs.default_making_charge_pct) as Decimal natively, while a value the
    user typed in chat and the LLM parsed into a field is a plain float.
    simpleeval's arithmetic operators refuse to mix Decimal with float
    ("unsupported operand type(s) for *: 'decimal.Decimal' and 'float'") —
    reproduced live: an item specifying its own making_charge_pct (float)
    against a line_subtotal already turned Decimal by an earlier pass here.
    Normalizing once, upfront, means every expression sees one consistent
    numeric type instead of only working by accident when both operands
    already match.
    """
    out = defaultdict(lambda: None)
    for k, v in d.items():
        if isinstance(v, bool):
            out[k] = v
        elif isinstance(v, (int, float)):
            out[k] = Decimal(str(v))
        else:
            out[k] = v
    return out


def _eval(expr: str, names: dict):
    """Evaluate an expression safely."""
    ev = EvalWithCompoundTypes(names=names, functions=_ALLOWED_FUNCTIONS)
    return ev.eval(expr)


def _resolve_multipass(
    rules: dict, names: dict, out: dict, label: str, error_suffix: str
) -> dict:
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
            # Convert to Decimal if it's a number, use ROUND_HALF_UP for Indian tax practice
            if isinstance(result, float):
                result = Decimal(str(result))
            if isinstance(result, Decimal):
                result = result.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            out[field] = result
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

    Every item field is passed through as-is, None included — a rule that
    needs a fallback (e.g. "this item's own rate, else the org's default")
    expresses that itself as a ternary expression referencing both names,
    same as any other calc_rules logic. The engine doesn't special-case
    any field name to make that possible; `x if x is not None else y` is
    plain simpleeval syntax, not a language extension. A field genuinely
    missing everywhere it could come from surfaces as a normal CalcError
    from _resolve_multipass below (a TypeError/KeyError evaluating the
    expression) — not a bespoke pre-check for one workflow's fields.
    """
    if not item_rules:
        return dict(item)
    item_with_defaults = {**item, "qty": item.get("qty", 1)}
    names = _normalize_numbers({**context, **item_with_defaults})
    out = dict(item_with_defaults)
    return _resolve_multipass(item_rules, names, out, "item_rules", f"on item {item}")


def compute_aggregate_rules(aggregate_rules: dict, fields: dict, context: dict) -> dict:
    """
    Workflow-level rules that see the whole draft (e.g. grand total from items).
    """
    if not aggregate_rules:
        return {}
    names = _normalize_numbers(
        {**context, **{k: v for k, v in fields.items() if v is not None}}
    )
    out = {}
    return _resolve_multipass(aggregate_rules, names, out, "aggregate_rules", "")


def compute_draft(calc_rules: dict, fields: dict, context: dict) -> dict:
    """
    Full pass: recompute item fields, then aggregate fields.
    Never mutates input dicts. Returns a new fields dict with computed values filled in.
    """
    if not calc_rules:
        return dict(fields)

    item_rules = calc_rules.get("item_rules") or {}
    aggregate_rules = calc_rules.get("aggregate_rules") or {}

    new_fields = dict(fields)

    if item_rules and isinstance(fields.get("items"), list):
        new_fields["items"] = [
            compute_item_rules(item_rules, item, context) for item in fields["items"]
        ]

    if aggregate_rules:
        new_fields.update(compute_aggregate_rules(aggregate_rules, new_fields, context))

    return new_fields
