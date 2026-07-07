"""
workflow_validator.py — Deterministic consistency checker for workflow configs.

Returns a list of problems (empty = valid).
Called from every code path that writes to the workflows table:
  1. workflow_compiler.py — inside the retry loop before returning a spec
  2. workflow_publisher.py — hard gate before INSERT/UPDATE
  3. admin.py PUT /workflow/{id} — validates the merged result before saving

Distinct from qa_verifier.py:
  qa_verifier checks a DRAFT'S DATA against a workflow's schema (per-transaction, at message time).
  This checks a WORKFLOW'S SCHEMA against ITSELF (per-definition, at save time).
  Different layers, both needed.
"""
import json


def _parse(val, default=None):
    if isinstance(val, str):
        try:
            return json.loads(val)
        except Exception:
            return default
    return val if val is not None else default


def validate_workflow_config(spec: dict) -> list[str]:
    """
    Check a workflow spec for internal consistency.
    Returns a list of human-readable problem strings.
    Empty list = valid.
    """
    problems = []

    entity_schema   = _parse(spec.get("entity_schema"), {}) or {}
    calc_rules      = _parse(spec.get("calc_rules"), {}) or {}
    item_rules      = calc_rules.get("item_rules") or {}
    aggregate_rules = calc_rules.get("aggregate_rules") or {}
    items_def       = entity_schema.get("items") or {}
    item_schema     = (items_def.get("item_schema") if isinstance(items_def, dict) else None) or {}
    steps           = _parse(spec.get("steps"), []) or []
    workflow_type   = spec.get("workflow_type", "action")

    # ── 1. Every calc_rules output must be declared computed:true ────────────
    for field in item_rules:
        fs = item_schema.get(field)
        if not fs or not (fs.get("computed") if isinstance(fs, dict) else False):
            problems.append(
                f"calc_rules.item_rules['{field}'] has no matching "
                f"entity_schema.items.item_schema['{field}'].computed=true"
            )

    for field in aggregate_rules:
        fs = entity_schema.get(field)
        if not fs or not (fs.get("computed") if isinstance(fs, dict) else False):
            problems.append(
                f"calc_rules.aggregate_rules['{field}'] has no matching "
                f"entity_schema['{field}'].computed=true"
            )

    # ── 2. No computed field may be required (user never supplies it) ────────
    for field, fs in entity_schema.items():
        if not isinstance(fs, dict):
            continue
        if fs.get("computed") and fs.get("required"):
            problems.append(
                f"entity_schema['{field}'] is both computed=true and required=true — "
                f"computed fields are filled by the system, not collected from the user"
            )
        # Check item_schema too
        for sub_field, sub_fs in (item_schema.items() if field == "items" else {}.items()):
            if isinstance(sub_fs, dict) and sub_fs.get("computed") and sub_fs.get("required"):
                problems.append(
                    f"entity_schema.items.item_schema['{sub_field}'] is both computed and required"
                )

    # ── 3. If item_rules produces 'total', all three canonical totals required ─
    if "total" in item_rules:
        for required_agg in ("subtotal", "gst_amount", "total_amount"):
            if required_agg not in aggregate_rules:
                problems.append(
                    f"item_rules produces a per-item 'total' but aggregate_rules is missing "
                    f"'{required_agg}' — the PDF renderer needs subtotal, gst_amount, and "
                    f"total_amount to render the totals block correctly"
                )

    # ── 4. Steps referencing $computed.X must have X in aggregate_rules ─────
    produced_computed = set(aggregate_rules.keys())
    for step in steps:
        if isinstance(step, str):
            try:
                step = json.loads(step)
            except Exception:
                continue
        if not isinstance(step, dict):
            continue
        params = step.get("params") or {}
        for _, v in params.items():
            if isinstance(v, str) and v.startswith("$computed."):
                field = v.split(".", 1)[1]
                if field not in produced_computed:
                    problems.append(
                        f"step '{step.get('op')}' references $computed.{field} "
                        f"but calc_rules.aggregate_rules never produces it"
                    )

    # ── 5. Action workflows must have at least one step ─────────────────────
    if workflow_type == "action" and not steps:
        problems.append(
            "workflow_type is 'action' but steps[] is empty — "
            "action workflows must define execution steps"
        )

    # ── 6. Read workflows should not have steps ──────────────────────────────
    if workflow_type == "read" and steps:
        # Warn but don't block — might be intentional
        pass

    # ── 7. status literals in db.insert_row/db.update_row must be lowercase ──
    for step in steps:
        if isinstance(step, str):
            try:
                step = json.loads(step)
            except Exception:
                continue
        if not isinstance(step, dict):
            continue
        op = step.get("op", "")
        if op in ("db.insert_row", "db.update_row"):
            values = (step.get("params") or {}).get("values") or {}
            set_vals = (step.get("params") or {}).get("set") or {}
            for col, val in {**values, **set_vals}.items():
                if col == "status" and isinstance(val, str) and val != val.lower():
                    problems.append(
                        f"step '{op}' sets status='{val}' — status values must be "
                        f"lowercase (e.g. 'pending' not 'PENDING')"
                    )

    return problems
