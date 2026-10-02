"""
step_sql.py — what a workflow step runs, written out for people.

For the dashboard's "Technical view": each step gets
  * the SQL it runs, with $1, $2 ... and a plain line saying where each value comes from, and
  * a tag saying whether it is done by code or by the assistant (AI).

The SQL here is built the same way the engine builds it (step_interpreter.py), from the same
settings, so what is shown is what runs. Nothing is executed and nothing is read from the database.
"""

import json

# the only step that asks the assistant (a language model) anything while a workflow runs
AI_OPS = {"ai_price_interpret"}


def is_ai(op: str) -> bool:
    return op in AI_OPS


def _value_note(value) -> str:
    """Where a value comes from, in a few words."""
    if value is None:
        return "nothing (clears it)"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    if not isinstance(value, str):
        return str(value)
    if not value.startswith("$"):
        special = {
            "NOW()": "the time it runs",
            "TODAY": "today",
            "TODAY+7": "a week from today",
            "TODAY+30": "30 days from today",
        }
        return special.get(value, f"the text “{value}”")
    parts = value[1:].split(".")
    root = parts[0]
    rest = " › ".join(p.replace("_", " ") for p in parts[1:])
    if root == "fields":
        return f"what the person answered: {rest}"
    if root == "user":
        return f"the person doing it: {rest}"
    if root == "org_id":
        return "this organisation"
    if root == "inserted":
        return f"the new {parts[1] if len(parts) > 1 else 'record'} just saved: {' › '.join(parts[2:]) or 'id'}"
    return f"{root.replace('_', ' ')} found earlier: {rest}" if rest else root


def _legend(args: list) -> list[str]:
    return [f"${i + 1} = {note}" for i, note in enumerate(args)]


def _sql(
    title: str, sql: str, args: list | None = None, note: str | None = None
) -> dict:
    return {
        "title": title,
        "sql": sql,
        "values": _legend(args or []),
        "note": note or "",
    }


def _cols(d) -> list[str]:
    return list(d.keys()) if isinstance(d, dict) else []


def _resolve_entity(p: dict) -> list[dict]:
    table = p.get("table") or "?"
    into = p.get("into") or table.rstrip("s")
    where = p.get("where") or {}
    extra_sql = "".join(f" AND {c} = ${i + 3}" for i, c in enumerate(where))
    extra_args = [_value_note(v) for v in where.values()]
    if p.get("match_columns"):
        cols = _cols(p["match_columns"])
        conds = " AND ".join(f"{c}::text ILIKE ${i + 2}" for i, c in enumerate(cols))
        args = ["this organisation"] + [
            _value_note(v) + " (matched anywhere in the text)"
            for v in p["match_columns"].values()
        ]
        return [
            _sql(
                f"Find the {into}",
                f"SELECT * FROM {table}\n WHERE org_id = $1 AND {conds}\n LIMIT 5",
                args,
                "More than one match asks the person which one they meant.",
            )
        ]
    col = p.get("match_column") or "name"
    source = _value_note(p.get("name_from"))
    if p.get("normalize") == "identifier":
        return [
            _sql(
                f"Find the {into} by its reference number",
                f"SELECT * FROM {table}\n WHERE org_id = $1 AND {col}_norm = $2{extra_sql}\n LIMIT 5",
                [
                    "this organisation",
                    f"{source}, with spaces and dashes removed and in capitals",
                    *extra_args,
                ],
                "If nothing matches, it tries the end of the number, then just the digits, "
                "then the number without its zeros. More than one match asks which one.",
            )
        ]
    return [
        _sql(
            f"Find the {into}",
            f"SELECT * FROM {table}\n WHERE org_id = $1 AND lower(btrim({col}::text)) = lower(btrim($2)){extra_sql}\n LIMIT 2",
            ["this organisation", source, *extra_args],
            "An exact match wins. If there is not exactly one, it looks for the words anywhere in "
            f"the {col} (ILIKE '%…%'). More than one match asks the person which one.",
        )
    ]


def _insert_row(p: dict) -> list[dict]:
    table = p.get("table") or "?"
    values = p.get("values") or {}
    cols = ["org_id", *values.keys()]
    holders = ", ".join(f"${i + 1}" for i in range(len(cols)))
    args = ["this organisation", *[_value_note(v) for v in values.values()]]
    note = ""
    seq = p.get("sequence")
    if seq:
        note = (
            f"The {seq.get('field')} is made first: the highest number so far with the prefix "
            f"“{seq.get('prefix')}” plus one, padded to {seq.get('pad', 0)} digits, under a lock so "
            "two people never get the same number."
        )
        if seq.get("field") and seq["field"] not in cols:
            cols.append(seq["field"])
            holders += f", ${len(cols)}"
            args.append("the new number")
    return [
        _sql(
            f"Save a new {table.rstrip('s')}",
            f"INSERT INTO {table} ({', '.join(cols)})\nVALUES ({holders})\nRETURNING *",
            args,
            note,
        )
    ]


def _update_row(p: dict) -> list[dict]:
    table = p.get("table") or "?"
    sets, where = p.get("set") or {}, p.get("where") or {}
    set_sql = ", ".join(
        f"{c} = {c} || ${i + 1}::jsonb" if c == "custom_fields" else f"{c} = ${i + 1}"
        for i, c in enumerate(sets)
    )
    where_cols = [*where.keys(), "org_id"]
    where_sql = " AND ".join(
        f"{c} = ${i + 1 + len(sets)}" for i, c in enumerate(where_cols)
    )
    args = (
        [_value_note(v) for v in sets.values()]
        + [_value_note(v) for v in where.values()]
        + ["this organisation"]
    )
    return [
        _sql(
            f"Change the {table.rstrip('s')}",
            f"UPDATE {table}\n SET {set_sql}\n WHERE {where_sql}\nRETURNING *",
            args,
            "Stops with an error if no row matches.",
        )
    ]


def _upsert_row(p: dict) -> list[dict]:
    table = p.get("table") or "?"
    values = p.get("values") or {}
    cols = ["org_id", *values.keys()]
    conflict = p.get("conflict_columns") or []
    update = ", ".join(f"{c} = EXCLUDED.{c}" for c in values if c not in conflict)
    return [
        _sql(
            f"Save or change a {table.rstrip('s')}",
            f"INSERT INTO {table} ({', '.join(cols)})\nVALUES ({', '.join(f'${i + 1}' for i in range(len(cols)))})\n"
            f"ON CONFLICT ({', '.join(conflict)}) DO UPDATE SET {update}\nRETURNING *",
            ["this organisation", *[_value_note(v) for v in values.values()]],
        )
    ]


def _delete_row(p: dict) -> list[dict]:
    table = p.get("table") or "?"
    where = p.get("where") or {}
    cols = [*where.keys(), "org_id"]
    return [
        _sql(
            f"Remove the {table.rstrip('s')}",
            f"DELETE FROM {table}\n WHERE "
            + " AND ".join(f"{c} = ${i + 1}" for i, c in enumerate(cols))
            + "\nRETURNING *",
            [_value_note(v) for v in where.values()] + ["this organisation"],
        )
    ]


def _conflict_check(p: dict) -> list[dict]:
    table = p.get("table") or "?"
    mc = p.get("match_columns") or {}
    conds = " AND ".join(f"{c} = ${i + 2}" for i, c in enumerate(mc))
    return [
        _sql(
            f"Look for an existing {table.rstrip('s')}",
            f"SELECT id FROM {table}\n WHERE org_id = $1 AND {conds}\n LIMIT 1",
            ["this organisation", *[_value_note(v) for v in mc.values()]],
            "If a row is found, the workflow stops with the message.",
        )
    ]


def sql_for_step(step: dict) -> list[dict]:
    """The SQL a step runs, as [{title, sql, values, note}]. Empty when it runs none."""
    op = step.get("op")
    p = step.get("params") or {}
    if op == "resolve_entity":
        return _resolve_entity(p)
    if op in ("db.insert_row", "sheets.insert_row"):
        return _insert_row(p)
    if op in ("db.update_row", "sheets.update_row"):
        return _update_row(p)
    if op == "db.upsert_row":
        return _upsert_row(p)
    if op in ("db.delete_row", "sheets.delete_row"):
        return _delete_row(p)
    if op == "conflict_check":
        return _conflict_check(p)
    if op == "case.route":
        return [
            _sql(
                "Ask the routing rules",
                "SELECT * FROM route_case($1, $2, '{}'::jsonb, $3, $4)",
                [
                    "this organisation",
                    _value_note(p.get("category_from") or "$fields.category_id"),
                    "this workflow",
                    _value_note(p.get("priority_from") or "$fields.priority"),
                ],
                "route_case picks the most specific matching rule, then looks up who holds the "
                "seat today and who is level 2. Then the names and phone numbers are read:",
            ),
            _sql(
                "Read the people it named",
                "SELECT id, name, phone FROM users WHERE id = ANY($1)",
                ["the handler and the level 2 people"],
            ),
        ]
    if op == "case.categorize":
        return [
            _sql(
                "Read the categories and their keywords",
                "SELECT id, parent_id, key, label, default_priority, target_minutes, keywords\n"
                "  FROM case_categories\n WHERE org_id = $1 AND is_active",
                ["this organisation"],
                "Then, in code: each keyword that starts a word in "
                + ", ".join(
                    _value_note(t)
                    for t in (
                        p.get("text_from") or ["$fields.title", "$fields.description"]
                    )
                )
                + " scores a point. The category with the most points wins; a sub-category beats "
                "its parent on a tie.",
            )
        ]
    if op == "case.authorize":
        return [
            _sql(
                "Is this person on the case?",
                "SELECT party_role FROM case_parties\n WHERE case_id = $1 AND user_id = $2 AND ended_at IS NULL",
                [
                    _value_note(p.get("case") or "$case") + " › id",
                    "the person doing it",
                ],
                "People whose role covers every case skip this check. Everyone else must hold one "
                "of the roles the workflow allows (its settings, who_can_use).",
            )
        ]
    if op == "case.add_parties":
        return [
            _sql(
                "Put people on the case",
                "INSERT INTO case_parties (org_id, case_id, user_id, party_role, added_by)\n"
                "VALUES ($1, $2, $3, $4, $5)\nON CONFLICT (case_id, user_id, party_role) WHERE ended_at IS NULL DO NOTHING",
                [
                    "this organisation",
                    _value_note(p.get("case_id")),
                    _value_note(p.get("users_from")) + " (one row each)",
                    f"the role: {p.get('role')}",
                    "the person doing it",
                ],
            )
        ]
    if op == "case.attach_photos":
        return [
            _sql(
                "Keep each photo on the timeline",
                "INSERT INTO case_activity (org_id, case_id, activity_type, actor_user_id, payload)\n"
                "VALUES ($1, $2, 'evidence', $3, $4)",
                [
                    "this organisation",
                    _value_note(p.get("case_id")),
                    "the person doing it",
                    "the photo’s Telegram id",
                ],
            )
        ]
    if op == "notify.parties":
        return [
            _sql(
                "Who is told",
                "SELECT u.id, u.name, u.phone, p.party_role\n  FROM case_parties p JOIN users u ON u.id = p.user_id\n"
                " WHERE p.case_id = $1 AND p.ended_at IS NULL AND p.party_role = ANY($2)\n"
                "   AND u.is_active AND u.phone IS NOT NULL",
                [_value_note(p.get("case") or "$case") + " › id", "the roles to tell"],
                "Each person is told once, whatever roles they hold; the person doing it is left out.",
            )
        ]
    if op == "run_workflow":
        return []
    return []


def tag_for(step: dict) -> dict:
    """Whether the step is done by code or by the assistant, and a short reason."""
    op = step.get("op")
    if is_ai(op):
        return {
            "by": "ai",
            "why": "The assistant (a language model) reads the typed price.",
        }
    if op == "run_workflow":
        return {
            "by": "code",
            "why": "Runs the steps of another workflow, which are code too unless they say otherwise.",
        }
    return {"by": "code", "why": "Exact rules and SQL. No AI."}


# ── one plain sentence per step (the dashboard's JavaScript writes the same ones for the editor) ──


def _short(value) -> str:
    if value is None:
        return "nothing"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (list, dict)):
        return "…"
    text = str(value)
    if not text.startswith("$"):
        return f"“{text}”"
    parts = text[1:].split(".")
    if parts[0] == "fields":
        return "‹" + (parts[1] if len(parts) > 1 else "answer").replace("_", " ") + "›"
    if parts[0] == "user":
        return (
            "‹the person’s "
            + (parts[1] if len(parts) > 1 else "record").replace("_", " ")
            + "›"
        )
    if parts[0] == "inserted":
        return (
            "‹the new "
            + (parts[1] if len(parts) > 1 else "record")
            + "’s "
            + (parts[-1] if len(parts) > 2 else "id")
            + "›"
        )
    return (
        "‹"
        + parts[0].replace("_", " ")
        + ("’s " + " ".join(parts[1:]).replace("_", " ") if len(parts) > 1 else "")
        + "›"
    )


def _pairs(d, joiner=" ← ") -> str:
    items = list((d or {}).items())
    shown = ", ".join(f"{k.replace('_', ' ')}{joiner}{_short(v)}" for k, v in items[:3])
    return shown + (" …" if len(items) > 3 else "")


def describe_step(step: dict, names: dict | None = None) -> str:
    """The step in a sentence. `names` maps a workflow's intent_key to its name."""
    op = step.get("op")
    p = step.get("params") or {}
    t = (p.get("table") or "record").replace("sheet:", "").rstrip("s").replace("_", " ")
    if op == "resolve_entity":
        if p.get("match_columns"):
            return f"Find the {t} where {_pairs(p['match_columns'], ' is ')}"
        return f"Find the {t} whose {(p.get('match_column') or 'name').replace('_', ' ')} is {_short(p.get('name_from'))}"
    if op == "conflict_check":
        return f"Stop if a {t} already has {_pairs(p.get('match_columns'), ' = ')}"
    if op == "require_permission":
        return "Check the person is allowed" + (
            f" ({' or '.join(p['any_of'])})" if p.get("any_of") else ""
        )
    if op == "derive_field":
        return f"Work out {(p.get('field') or 'a value').replace('_', ' ')}"
    if op == "compute":
        return "Calculate totals"
    if op in ("db.insert_row", "sheets.insert_row"):
        return f"Save a new {t}: {_pairs(p.get('values'))}"
    if op in ("db.update_row", "sheets.update_row"):
        return f"Change the {t}: {_pairs(p.get('set'))}"
    if op == "db.upsert_row":
        return f"Save or change a {t}: {_pairs(p.get('values'))}"
    if op in ("db.delete_row", "sheets.delete_row"):
        return f"Remove a {t}"
    if op == "notify.user":
        return f"Message {_short(p.get('to'))}"
    if op == "notify.whatsapp":
        return "Send the confirmation"
    if op == "pdf.generate":
        return "Make the PDF"
    if op == "otp_gate":
        return "Ask for a one-time code"
    if op == "approval_gate":
        return "Ask for approval"
    if op == "ai_price_interpret":
        return "Read the typed prices"
    if op == "run_workflow":
        key = p.get("workflow")
        return "Run “" + ((names or {}).get(key) or key or "a building block") + "”"
    if op == "case.categorize":
        return "Work out the category from the words in the complaint"
    if op == "case.route":
        return "Find who handles it, who is level 2 and how long it may take"
    if op == "case.authorize":
        return "Check the person is on the case"
    if op == "case.add_parties":
        return f"Put {_short(p.get('users_from'))} on the case as {(p.get('role') or 'a helper').replace('level2', 'level 2')}"
    if op == "case.attach_photos":
        return "Attach the photos to the case"
    if op == "notify.parties":
        return "Tell everyone on the case"
    return str(op)
