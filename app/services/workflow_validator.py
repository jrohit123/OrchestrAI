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
import re


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
    # Every place that WRITES workflow_type (compile_and_summarize,
    # workflow_publisher.py) defaults a missing/empty value to "action" via
    # `spec.get("workflow_type") or "action"`. If this check used a plain
    # dict.get(..., "action") default instead, an explicit "" or null from
    # the compiler LLM would read here as falsy-but-not-"action", skip the
    # action/steps consistency check below, and only surface as a broken
    # publish once the same value got defaulted to "action" downstream —
    # the exact "workflow_type is 'action' but steps[] is empty" failure
    # this function exists to catch. Normalize the same way here so it's
    # caught at the true point of origin instead of one write later.
    workflow_type   = spec.get("workflow_type") or "action"

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

    # ── 7. gates[] structural checks ──────────────────────────────────────
    gates = _parse(spec.get("gates"), []) or []
    if not isinstance(gates, list):
        problems.append("gates must be a JSON array")
        gates = []

    if gates and workflow_type == "read":
        problems.append(
            "workflow_type is 'read' but gates[] is non-empty — "
            "OTP/approval/permission gates only apply to action workflows"
        )

    seen_gate_ids = set()
    for idx, gate in enumerate(gates):
        if not isinstance(gate, dict):
            problems.append(f"gates[{idx}] must be an object")
            continue

        gate_id = gate.get("id")
        label = gate_id or f"gates[{idx}]"
        if not gate_id:
            problems.append(f"gates[{idx}] is missing 'id'")
        elif gate_id in seen_gate_ids:
            problems.append(f"gates[{idx}] has duplicate id '{gate_id}' — gate ids must be unique")
        else:
            seen_gate_ids.add(gate_id)

        gate_type = gate.get("type")
        if gate_type not in ("otp", "approval_chain", "permission"):
            problems.append(f"{label}: type must be 'otp', 'approval_chain', or 'permission' (got {gate_type!r})")
            continue

        if gate_type == "approval_chain":
            levels = gate.get("levels")
            if not levels or not isinstance(levels, list):
                problems.append(f"{label}: approval_chain gate must have a non-empty levels[] array")
                continue
            prev_level_num = None
            prev_max = None
            for lvl_idx, lvl in enumerate(levels):
                if not isinstance(lvl, dict):
                    problems.append(f"{label}.levels[{lvl_idx}] must be an object")
                    continue
                if not lvl.get("role"):
                    problems.append(f"{label}.levels[{lvl_idx}] is missing 'role'")
                level_num = lvl.get("level")
                if level_num is None:
                    problems.append(f"{label}.levels[{lvl_idx}] is missing 'level'")
                elif prev_level_num is not None and level_num <= prev_level_num:
                    problems.append(
                        f"{label}.levels[{lvl_idx}]: level numbers must strictly increase "
                        f"(got {level_num} after {prev_level_num})"
                    )
                max_amount = lvl.get("max_amount")
                if prev_max is None and prev_level_num is not None:
                    # Previous level had max_amount=null (no ceiling) — nothing
                    # after it could ever be reached, so a further level is dead code.
                    problems.append(
                        f"{label}.levels[{lvl_idx}]: unreachable — the previous level has "
                        f"max_amount=null (no ceiling), so this level can never trigger"
                    )
                if max_amount is not None and prev_max is not None and max_amount <= prev_max:
                    problems.append(
                        f"{label}.levels[{lvl_idx}]: max_amount ({max_amount}) must be greater "
                        f"than the previous level's max_amount ({prev_max})"
                    )
                prev_level_num = level_num if level_num is not None else prev_level_num
                prev_max = max_amount
        elif gate_type == "permission":
            if not gate.get("role_any_of"):
                problems.append(f"{label}: permission gate must have a non-empty role_any_of[] array")

    # ── 8. status literals in db.insert_row/db.update_row must be lowercase ──
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

    # ── 9. sql_template must only use numeric $N placeholders ───────────────
    # RULE 4a/5 (workflow_compiler.txt): sentinels like "$current_user"
    # belong ONLY in sql_params_order, resolved at runtime by
    # agent._resolve_sql_params. If one leaks into the SQL text itself,
    # Postgres can't parse it ("$current_user" isn't a valid bind parameter)
    # and the query fails for every real user who triggers it — found live
    # on godrej's /my_cases workflow, which shipped with
    # "complainant_id = $current_user" instead of "complainant_id = $2".
    sql_template = spec.get("sql_template")
    if workflow_type == "read" and sql_template:
        sql_params_order = _parse(spec.get("sql_params_order"), []) or []
        numeric_placeholders = []
        for token in re.findall(r"\$(\w+)", sql_template):
            if not token.isdigit():
                problems.append(
                    f"sql_template contains non-numeric placeholder '${token}' — "
                    f"parameter values (including sentinels like \"$current_user\") "
                    f"must be passed positionally as $1, $2... with the actual "
                    f"name/sentinel only in sql_params_order, never inlined in the SQL text"
                )
            else:
                numeric_placeholders.append(int(token))

        if numeric_placeholders:
            expected_max = 1 + len(sql_params_order)
            actual_max = max(numeric_placeholders)
            if actual_max != expected_max:
                problems.append(
                    f"sql_template's highest placeholder is ${actual_max} but "
                    f"sql_params_order has {len(sql_params_order)} entries — "
                    f"expected highest placeholder ${expected_max} "
                    f"($1 is always org_id, $2.. map 1:1 to sql_params_order in order)"
                )

    # ── 10. Two resolve_entity steps must not write into the same alias ─────
    # A second resolve_entity into an "into" already used by an earlier one
    # silently OVERWRITES the first's result rather than combining both
    # conditions — reproduced live: a workflow meant to find a resident by
    # wing AND flat_no used two separate resolve_entity calls (one per
    # column) into the same alias; the second call's flat_no-only match
    # silently won, so the wing filter was dropped entirely and the update
    # could target the wrong resident. Composite-key lookups must use a
    # single resolve_entity with match_columns instead (see RULE 14).
    resolve_targets: dict[str, int] = {}
    for idx, step in enumerate(steps):
        if isinstance(step, str):
            try:
                step = json.loads(step)
            except Exception:
                continue
        if not isinstance(step, dict) or step.get("op") != "resolve_entity":
            continue
        into = (step.get("params") or {}).get("into")
        if not into:
            continue
        if into in resolve_targets:
            problems.append(
                f"steps[{idx}] is a second resolve_entity writing into '{into}' "
                f"(steps[{resolve_targets[into]}] already does) — the second call "
                f"silently overwrites the first's result instead of combining both "
                f"conditions, so whichever column the second call matched on ends up "
                f"being the ONLY thing actually filtered on. Use a single resolve_entity "
                f"with match_columns to match on multiple columns together, not two "
                f"separate resolve_entity calls into the same alias."
            )
        else:
            resolve_targets[into] = idx

    return problems
