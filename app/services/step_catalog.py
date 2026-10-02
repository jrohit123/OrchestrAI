"""
step_catalog.py — What each workflow step type is called in plain words, which settings it
takes, and a checker that explains in plain language what is wrong with a list of steps.

The workflow editor in the admin panel builds its forms from STEP_TYPES, so a new step type
only has to be added here (and to PRIMITIVES in step_interpreter.py) to become editable.
The same table drives validate_steps(), which the editor runs before anything is saved and
which the chat assistant's proposals must also pass.

Nothing in here talks to a database: callers hand in the schema and the other workflows.
"""

import json
import re

# ── step types ────────────────────────────────────────────────────────────────
# param kinds the editor understands:
#   table, column (needs table_key), alias, value, text, longtext, number, bool, choice,
#   list_text, list_column, map_value (column -> value), map_column (field -> column),
#   map_text (free key -> text), sequence, workflow

STEP_TYPES: list[dict] = [
    {
        "op": "resolve_entity",
        "label": "Find a record",
        "group": "Look up and check",
        "help": "Finds one record (a case, a person, a flat) and keeps it for the steps after it.",
        "params": [
            {
                "key": "table",
                "label": "Where to look",
                "kind": "table",
                "required": True,
            },
            {
                "key": "into",
                "label": "Call it",
                "kind": "alias",
                "required": True,
                "help": "A short name later steps use, for example case.",
            },
            {
                "key": "name_from",
                "label": "Look it up by",
                "kind": "value",
                "required_unless": "match_columns",
            },
            {
                "key": "match_column",
                "label": "Compare with the column",
                "kind": "column",
                "table_key": "table",
                "default": "name",
            },
            {
                "key": "normalize",
                "label": "The text is",
                "kind": "choice",
                "options": [
                    ["", "A name or word"],
                    [
                        "identifier",
                        "A reference number (ignores spaces, dashes and capitals)",
                    ],
                ],
            },
            {
                "key": "match_columns",
                "label": "Or match several columns together",
                "kind": "map_value",
                "keys": "column",
                "table_key": "table",
                "advanced": True,
            },
            {
                "key": "expose",
                "label": "Copy columns into the fields",
                "kind": "map_column",
                "table_key": "table",
                "advanced": True,
            },
        ],
        "makes": "alias",
    },
    {
        "op": "conflict_check",
        "label": "Stop if it already exists",
        "group": "Look up and check",
        "help": "Stops with a message when a matching record is already there.",
        "params": [
            {
                "key": "table",
                "label": "Where to look",
                "kind": "table",
                "required": True,
            },
            {
                "key": "match_columns",
                "label": "It clashes when these match",
                "kind": "map_value",
                "keys": "column",
                "table_key": "table",
                "required": True,
            },
            {"key": "error_message", "label": "Message to show", "kind": "text"},
            {
                "key": "exclude_id",
                "label": "Ignore the record with this id",
                "kind": "value",
                "advanced": True,
            },
        ],
    },
    {
        "op": "require_permission",
        "label": "Check the person is allowed",
        "group": "Look up and check",
        "help": "Stops with a message unless the person has one of these permissions.",
        "params": [
            {
                "key": "any_of",
                "label": "Allowed if they have any of",
                "kind": "list_text",
            },
            {
                "key": "from",
                "label": "Or pick the permission from",
                "kind": "value",
                "advanced": True,
            },
            {
                "key": "map",
                "label": "…using this table (value → permission)",
                "kind": "map_text",
                "advanced": True,
            },
            {
                "key": "denied_message",
                "label": "Message when not allowed",
                "kind": "text",
            },
        ],
    },
    {
        "op": "derive_field",
        "label": "Work out a value",
        "group": "Look up and check",
        "help": "Calculates one value (for example a due date) and keeps it as a field.",
        "params": [
            {
                "key": "field",
                "label": "Name of the value",
                "kind": "text",
                "required": True,
            },
            {
                "key": "expr",
                "label": "How to work it out",
                "kind": "text",
                "required": True,
                "help": 'A short formula, for example due_from_tat(tat_minutes, "minutes").',
            },
        ],
    },
    {
        "op": "compute",
        "label": "Calculate totals",
        "group": "Look up and check",
        "help": "Runs the workflow's calculation rules (invoices, quotes).",
        "params": [],
    },
    {
        "op": "db.insert_row",
        "label": "Save a new record",
        "group": "Save changes",
        "help": "Adds a new row to a table.",
        "params": [
            {
                "key": "table",
                "label": "Where to save it",
                "kind": "table",
                "required": True,
            },
            {
                "key": "values",
                "label": "What to save",
                "kind": "map_value",
                "keys": "column",
                "table_key": "table",
                "required": True,
            },
            {
                "key": "sequence",
                "label": "Give it a number",
                "kind": "sequence",
                "table_key": "table",
                "advanced": True,
            },
        ],
        "makes": "inserted",
    },
    {
        "op": "db.update_row",
        "label": "Change a record",
        "group": "Save changes",
        "help": "Changes columns on an existing row.",
        "params": [
            {"key": "table", "label": "Which table", "kind": "table", "required": True},
            {
                "key": "set",
                "label": "Change these",
                "kind": "map_value",
                "keys": "column",
                "table_key": "table",
                "required": True,
            },
            {
                "key": "where",
                "label": "On the row where",
                "kind": "map_value",
                "keys": "column",
                "table_key": "table",
                "required": True,
            },
        ],
    },
    {
        "op": "db.upsert_row",
        "label": "Save or change a record",
        "group": "Save changes",
        "help": "Adds a row, or changes it if one with the same key already exists.",
        "params": [
            {"key": "table", "label": "Which table", "kind": "table", "required": True},
            {
                "key": "values",
                "label": "What to save",
                "kind": "map_value",
                "keys": "column",
                "table_key": "table",
                "required": True,
            },
            {
                "key": "conflict_columns",
                "label": "Same row when these match",
                "kind": "list_column",
                "table_key": "table",
                "required": True,
            },
        ],
    },
    {
        "op": "db.delete_row",
        "label": "Remove a record",
        "group": "Save changes",
        "help": "Deletes a row.",
        "params": [
            {"key": "table", "label": "Which table", "kind": "table", "required": True},
            {
                "key": "where",
                "label": "The row where",
                "kind": "map_value",
                "keys": "column",
                "table_key": "table",
                "required": True,
            },
        ],
    },
    {
        "op": "notify.user",
        "label": "Message someone",
        "group": "Tell people",
        "help": "Sends a message to a person found earlier.",
        "params": [
            {
                "key": "to",
                "label": "Send to",
                "kind": "value",
                "required": True,
                "help": "Needs a phone number: pick a person's phone (for example the assignee's phone), not their id.",
            },
            {
                "key": "message_template",
                "label": "Message",
                "kind": "longtext",
                "required": True,
                "help": "Use {field_name} to put a value in.",
            },
        ],
    },
    {
        "op": "notify.whatsapp",
        "label": "Send the confirmation",
        "group": "Tell people",
        "help": "Sends the person who started this the result (and the PDF, if there is one).",
        "params": [{"key": "attach_pdf", "label": "Attach the PDF", "kind": "bool"}],
    },
    {
        "op": "pdf.generate",
        "label": "Make a PDF",
        "group": "Tell people",
        "help": "Builds the workflow's PDF document.",
        "params": [{"key": "subtitle", "label": "Subtitle", "kind": "text"}],
    },
    {
        "op": "otp_gate",
        "label": "Ask for a one-time code",
        "group": "Approvals",
        "help": "Asks the person for a code sent to their email when an amount is large.",
        "params": [
            {"key": "amount_field", "label": "Amount to check", "kind": "value"}
        ],
    },
    {
        "op": "approval_gate",
        "label": "Ask for approval",
        "group": "Approvals",
        "help": "Waits for an approver when an amount is large.",
        "params": [
            {"key": "amount_field", "label": "Amount to check", "kind": "value"}
        ],
    },
    {
        "op": "ai_price_interpret",
        "label": "Read a typed price",
        "group": "Other",
        "help": "Turns a typed price such as 'fifty a piece' into a number before totals are worked out.",
        "params": [],
    },
    {
        "op": "case.categorize",
        "label": "Work out the category",
        "group": "Look up and check",
        "help": "Picks the category from the words in the complaint, using the keywords each category lists. Keeps it as 'category' and fills in the category fields.",
        "params": [
            {
                "key": "text_from",
                "label": "Read the words from",
                "kind": "list_text",
                "help": "For example $fields.title and $fields.description.",
            },
            {"key": "into", "label": "Call it", "kind": "alias", "default": "category"},
        ],
        "makes": "alias",
    },
    {
        "op": "case.route",
        "label": "Find who handles it",
        "group": "Look up and check",
        "help": "Looks up, from the routing rules, who a case in this category goes to, who is level 2 and how long it may take.",
        "params": [
            {
                "key": "category_from",
                "label": "Category",
                "kind": "value",
                "default": "$fields.category_id",
            },
            {
                "key": "priority_from",
                "label": "Priority",
                "kind": "value",
                "default": "$fields.priority",
            },
            {"key": "into", "label": "Call it", "kind": "alias", "default": "route"},
        ],
        "makes": "alias",
    },
    {
        "op": "case.authorize",
        "label": "Check the person is on the case",
        "group": "Look up and check",
        "help": "Stops with a message unless the person may act on this case. People whose role covers every case always pass.",
        "params": [
            {"key": "case", "label": "The case", "kind": "value", "default": "$case"},
            {
                "key": "denied_message",
                "label": "Message when not allowed",
                "kind": "text",
            },
        ],
    },
    {
        "op": "case.add_parties",
        "label": "Add people to the case",
        "group": "Save changes",
        "help": "Puts people on a case as level 2, helper or watcher, so they are told about it and can act on it.",
        "params": [
            {"key": "case_id", "label": "The case", "kind": "value", "required": True},
            {
                "key": "users_from",
                "label": "Who to add",
                "kind": "value",
                "required": True,
            },
            {
                "key": "role",
                "label": "As",
                "kind": "choice",
                "required": True,
                "options": [
                    ["level2", "Level 2"],
                    ["helper", "Helper"],
                    ["watcher", "Watcher"],
                ],
            },
        ],
    },
    {
        "op": "case.attach_photos",
        "label": "Attach the photos",
        "group": "Save changes",
        "help": "Keeps the photos sent with the request on the case's timeline.",
        "params": [
            {"key": "case_id", "label": "The case", "kind": "value", "required": True},
            {
                "key": "photos_from",
                "label": "The photos",
                "kind": "value",
                "advanced": True,
                "default": "$fields._photos",
            },
        ],
    },
    {
        "op": "notify.parties",
        "label": "Tell everyone on the case",
        "group": "Tell people",
        "help": "Messages everyone on the case (not the person doing this), once each. Can give the new handler a different message and add buttons.",
        "params": [
            {"key": "case", "label": "The case", "kind": "value", "required": True},
            {
                "key": "message_template",
                "label": "Message",
                "kind": "longtext",
                "required": True,
                "help": "Use {case_case_number}, {case_title}, {actor_name} or any field name in braces.",
            },
            {
                "key": "role_templates",
                "label": "A different message for some people",
                "kind": "map_text",
                "advanced": True,
                "help": "Role (assignee, level2, helper, requester) → message.",
            },
            {
                "key": "buttons",
                "label": "Buttons under the message",
                "kind": "map_text",
                "advanced": True,
                "help": "Button text → command, for example /update {case_case_number}.",
            },
            {
                "key": "roles",
                "label": "Who to tell",
                "kind": "list_text",
                "advanced": True,
            },
            {
                "key": "include_actor",
                "label": "Also tell the person doing this",
                "kind": "bool",
                "advanced": True,
            },
            {
                "key": "with_photos",
                "label": "Send the photos too",
                "kind": "bool",
                "advanced": True,
            },
        ],
    },
    {
        "op": "run_workflow",
        "label": "Run a building block",
        "group": "Other",
        "help": "Runs another workflow as one step. Change that workflow once and everything that runs it changes.",
        "params": [
            {
                "key": "workflow",
                "label": "Which one",
                "kind": "workflow",
                "required": True,
            },
            {
                "key": "inputs",
                "label": "Give it these (name → value)",
                "kind": "map_value",
                "keys": "free",
                "advanced": True,
                "help": "Only needed to rename or add values. It already sees everything this workflow has.",
            },
        ],
    },
]

STEP_BY_OP = {t["op"]: t for t in STEP_TYPES}
# steps that keep a record under a name, besides "Find a record":
# {op: (setting that holds the name, default name, fields the step also fills in)}
ALIAS_MAKERS = {
    "case.categorize": ("into", "category", ("category_id", "category_label")),
    "case.route": ("into", "route", ("assigned_name", "route_minutes")),
}
# aliases the engine also accepts, shown but never offered when adding a step
LEGACY_OPS = {"sheets.insert_row", "sheets.update_row", "sheets.delete_row"}

# columns a workflow field can hold, as the assistant understands them
FIELD_TYPES = [
    ["string", "Text"],
    ["integer", "Whole number"],
    ["float", "Number with decimals"],
    ["date", "Date"],
    ["boolean", "Yes or no"],
]

_ROOTS = {
    "fields",
    "computed",
    "generated",
    "inserted",
    "user",
    "org_id",
    "updated",
    "deleted",
}
_OPERATORS = (
    "equals",
    "not_equals",
    "in",
    "not_in",
    "exists",
    "gte",
    "lte",
    "gt",
    "lt",
)
_MAX_DEPTH = 5


def catalog_for_ui(supported_ops: set[str]) -> list[dict]:
    """The step types to offer: only ones the running engine can actually execute."""
    return [t for t in STEP_TYPES if t["op"] in supported_ops]


# ── helpers ───────────────────────────────────────────────────────────────────


def normalize_steps(steps) -> list:
    """Steps are normally a list of objects; very old rows hold JSON text per step."""
    if isinstance(steps, str):
        try:
            steps = json.loads(steps)
        except ValueError:
            return []
    out = []
    for s in steps or []:
        if isinstance(s, str):
            try:
                s = json.loads(s)
            except ValueError:
                pass
        out.append(s)
    return out


def used_blocks(steps) -> list[str]:
    """Intent keys of the workflows these steps run (run_workflow steps)."""
    found = []
    for s in normalize_steps(steps):
        if isinstance(s, dict) and s.get("op") == "run_workflow":
            key = (s.get("params") or {}).get("workflow")
            if key and key not in found:
                found.append(key)
    return found


def _walk_strings(value):
    if isinstance(value, dict):
        for v in value.values():
            yield from _walk_strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _walk_strings(v)
    elif isinstance(value, str):
        yield value


def aliases_made_by(steps) -> dict[str, str | None]:
    """Records a list of steps keeps for later steps: {alias: table}."""
    out: dict[str, str | None] = {}
    for s in normalize_steps(steps):
        if isinstance(s, dict) and s.get("op") == "resolve_entity":
            p = s.get("params") or {}
            into = p.get("into") or (p.get("table") or "").rstrip("s")
            if into:
                out[into] = p.get("table")
        elif isinstance(s, dict) and s.get("op") in ALIAS_MAKERS:
            key, default, _ = ALIAS_MAKERS[s["op"]]
            out[(s.get("params") or {}).get(key) or default] = None
    return out


def aliases_needed_by(steps) -> list[str]:
    """Records a list of steps uses but never finds itself: what a building block expects the
    workflow that runs it to have found first (for example the case)."""
    made: set[str] = set()
    needed: list[str] = []
    for s in normalize_steps(steps):
        if not isinstance(s, dict):
            continue
        p = s.get("params") or {}
        for text in (*_walk_strings(p), *_walk_strings(s.get("when"))):
            if text.startswith("$") and not text.startswith("$inserted."):
                root = text[1:].split(".")[0]
                if root not in _ROOTS and root not in made and root not in needed:
                    needed.append(root)
        if s.get("op") == "resolve_entity":
            into = p.get("into") or (p.get("table") or "").rstrip("s")
            if into:
                made.add(into)
    return needed


def _reaches(start: str, target: str, workflows: dict, seen: set | None = None) -> bool:
    """True when running `start` could end up running `target`."""
    seen = seen if seen is not None else set()
    if start in seen:
        return False
    seen.add(start)
    for nxt in used_blocks((workflows.get(start) or {}).get("steps")):
        if nxt == target or _reaches(nxt, target, workflows, seen):
            return True
    return False


def _depth(key: str, workflows: dict, seen: tuple = ()) -> int:
    if key in seen:
        return _MAX_DEPTH + 1
    kids = used_blocks((workflows.get(key) or {}).get("steps"))
    return 1 + max((_depth(k, workflows, (*seen, key)) for k in kids), default=0)


def _atoms(cond) -> set[str]:
    """The separate tests inside a 'when' guard, so two guards can be compared."""
    if not isinstance(cond, dict) or not cond:
        return set()
    if "and" in cond:
        out: set[str] = set()
        for c in cond["and"] if isinstance(cond["and"], list) else []:
            out |= _atoms(c)
        return out
    return {json.dumps(cond, sort_keys=True)}


def _cond_text(atoms: set[str]) -> str:
    parts = []
    for a in sorted(atoms):
        c = json.loads(a)
        field = str(c.get("field", "")).replace("$fields.", "").replace("$", "")
        op = next((o for o in _OPERATORS if o in c), "")
        parts.append(f"{field} {op.replace('_', ' ')} {c.get(op, '')}".strip())
    return " and ".join(parts)


def _check_when(cond, label: str, ctx: dict, errors: list, warnings: list) -> None:
    if cond is None or cond == {}:
        return
    if not isinstance(cond, dict):
        errors.append(f"{label}: the 'only if' condition is not valid.")
        return
    if "and" in cond:
        for c in cond["and"] if isinstance(cond["and"], list) else []:
            _check_when(c, label, ctx, errors, warnings)
        return
    field = cond.get("field")
    if not isinstance(field, str) or not field.startswith("$"):
        errors.append(f"{label}: the 'only if' condition needs something to look at.")
        return
    _check_path(field, label, ctx, errors, warnings)
    if not any(op in cond for op in _OPERATORS):
        errors.append(
            f"{label}: the 'only if' condition has no test (is, is not, has a value…)."
        )


def _check_path(path: str, label: str, ctx: dict, errors: list, warnings: list) -> None:
    parts = path[1:].split(".")
    root = parts[0]
    if root in _ROOTS:
        if (
            root == "fields"
            and len(parts) > 1
            and not ctx["is_block"]
            and parts[1] not in ctx["fields"]
        ):
            warnings.append(
                f"{label} uses the field '{parts[1]}', which this workflow does not ask for "
                "and no earlier step creates."
            )
        return
    if root in ctx["aliases"]:
        needs = ctx["alias_when"].get(root) or set()
        guarded_by_it = any(f.startswith(f"${root}.") for f in ctx["now_fields"])
        if needs and not needs <= ctx["now_when"] and not guarded_by_it:
            warnings.append(
                f"{label} uses ${root}, but an earlier step only finds it when "
                f"{_cond_text(needs)}. In other cases it will be empty."
            )
        table = ctx["aliases"][root]
        cols = ctx["schema"].get(table) if table else None
        if cols is not None and len(parts) > 1 and parts[1] not in cols:
            errors.append(
                f"{label}: the record called '{root}' ({table}) has no column '{parts[1]}'."
            )
        return
    if ctx["is_block"]:
        ctx["expects"].add(root)  # said once, at the end
        return
    errors.append(
        f"{label} uses ${root}, but no earlier step finds a record called '{root}'. "
        "Add a 'Find a record' step before it."
    )


def _check_columns(
    label: str, table, cols, schema: dict, errors: list, what: str
) -> None:
    if not table or table.startswith("sheet:"):
        return
    known = schema.get(table)
    if known is None:
        return
    for c in cols:
        if c not in known:
            errors.append(f"{label}: '{table}' has no column '{c}' ({what}).")


def validate_steps(
    steps,
    *,
    schema: dict,
    entity_schema: dict | None = None,
    kind: str = "workflow",
    intent_key: str | None = None,
    workflows: dict | None = None,
) -> dict:
    """
    Explain, in plain language, what is wrong with a list of steps.

    schema:     {table: set_of_columns} (the org's real tables)
    workflows:  {intent_key: {"steps": [...], "is_active": bool, "name": str}} for every
                other workflow, so run_workflow targets can be checked
    Returns {"errors": [...], "warnings": [...]}. Errors block saving; warnings do not.
    """
    errors: list[str] = []
    warnings: list[str] = []
    workflows = workflows or {}
    steps = normalize_steps(steps)
    if not isinstance(steps, list):
        return {"errors": ["The steps must be a list."], "warnings": []}

    ctx = {
        "schema": schema,
        "aliases": {},
        "alias_when": {},
        "now_when": set(),
        "now_fields": set(),
        "expects": set(),
        "fields": set((entity_schema or {}).keys()),
        "is_block": kind == "block",
    }
    inserted: set[str] = set()

    for n, step in enumerate(steps, 1):
        if not isinstance(step, dict):
            errors.append(f"Step {n} is not a step.")
            continue
        op = step.get("op")
        spec = STEP_BY_OP.get(op)
        if not spec:
            if op in LEGACY_OPS:
                continue
            errors.append(f"Step {n}: '{op}' is not a step type this assistant knows.")
            continue
        label = f"Step {n} ({spec['label']})"
        params = step.get("params") or {}
        if not isinstance(params, dict):
            errors.append(f"{label}: its settings are not valid.")
            continue
        ctx["now_when"] = _atoms(step.get("when"))
        ctx["now_fields"] = {json.loads(a).get("field", "") for a in ctx["now_when"]}

        _check_when(step.get("when"), label, ctx, errors, warnings)

        # required settings
        for p in spec["params"]:
            value = params.get(p["key"])
            empty = value in (None, "", [], {})
            unless = p.get("required_unless")
            if p.get("required") and empty:
                errors.append(f"{label}: '{p['label']}' is empty.")
            elif unless and empty and not params.get(unless):
                errors.append(
                    f"{label}: '{p['label']}' (or '{unless.replace('_', ' ')}') is needed."
                )

        # tables and columns
        table = params.get("table")
        if (
            isinstance(table, str)
            and table
            and not table.startswith("sheet:")
            and table not in schema
        ):
            errors.append(f"{label}: there is no table called '{table}'.")
            table = None
        for p in spec["params"]:
            v = params.get(p["key"])
            if v in (None, "", [], {}):
                continue
            if p["kind"] == "column" and isinstance(v, str):
                _check_columns(label, table, [v], schema, errors, p["label"].lower())
            elif (
                p["kind"] == "map_value"
                and p.get("keys") == "column"
                and isinstance(v, dict)
            ):
                _check_columns(
                    label, table, list(v.keys()), schema, errors, p["label"].lower()
                )
            elif p["kind"] == "map_column" and isinstance(v, dict):
                _check_columns(
                    label,
                    table,
                    [c for c in v.values() if isinstance(c, str)],
                    schema,
                    errors,
                    p["label"].lower(),
                )
            elif p["kind"] == "list_column" and isinstance(v, list):
                _check_columns(
                    label,
                    table,
                    [c for c in v if isinstance(c, str)],
                    schema,
                    errors,
                    p["label"].lower(),
                )
            elif p["kind"] == "sequence" and isinstance(v, dict) and v.get("field"):
                _check_columns(
                    label, table, [v["field"]], schema, errors, "number column"
                )

        if op == "notify.user":
            to = params.get("to")
            if isinstance(to, str) and to.startswith("$") and not to.endswith(".phone"):
                errors.append(
                    f"{label}: 'Send to' must be a phone number. Pick the person's phone, not '{to}'."
                )

        # every $reference must point at something that will exist by now
        for text in _walk_strings(
            {k: v for k, v in params.items() if k != "message_template"}
        ):
            if text.startswith("$"):
                if text.startswith("$inserted."):
                    parts = text.split(".")
                    if len(parts) > 1 and parts[1] not in inserted and ctx["is_block"]:
                        # a block may use a record its caller saved just before
                        ctx["expects"].add(f"a new record saved in '{parts[1]}'")
                    elif len(parts) > 1 and parts[1] not in inserted:
                        errors.append(
                            f"{label} uses {text}, but no earlier step saves a new record in '{parts[1]}'."
                        )
                else:
                    _check_path(text, label, ctx, errors, warnings)

        # what this step leaves behind for the next ones
        if op == "resolve_entity":
            into = params.get("into") or (params.get("table") or "").rstrip("s")
            if into:
                ctx["aliases"][into] = params.get("table")
                ctx["alias_when"][into] = _atoms(step.get("when"))
            for alias in (
                (params.get("expose") or {})
                if isinstance(params.get("expose"), dict)
                else {}
            ):
                ctx["fields"].add(alias)
        elif op == "derive_field" and params.get("field"):
            ctx["fields"].add(params["field"])
        elif op in ALIAS_MAKERS:
            key, default, extra = ALIAS_MAKERS[op]
            ctx["aliases"][params.get(key) or default] = None
            ctx["alias_when"][params.get(key) or default] = _atoms(step.get("when"))
            ctx["fields"].update(extra)
        elif op == "db.insert_row" and isinstance(params.get("table"), str):
            inserted.add(params["table"])
        elif op in ("otp_gate", "approval_gate") and kind == "block":
            errors.append(
                f"{label}: a building block cannot ask for a code or approval. "
                "Put this step in the workflow that runs the block."
            )
        elif op == "require_permission" and kind == "block":
            warnings.append(
                f"{label}: checks on who may do something belong on the workflow people start, "
                "not inside a building block."
            )
        elif op == "run_workflow":
            key = params.get("workflow")
            target = workflows.get(key) if key else None
            if key and key == intent_key:
                errors.append(f"{label}: a workflow cannot run itself.")
            elif key and target is None:
                errors.append(f"{label}: there is no workflow called '{key}'.")
            elif key and not target.get("steps"):
                errors.append(
                    f"{label}: '{target.get('name') or key}' has no steps to run "
                    "(a report only shows a list), so it cannot be used as a step."
                )
            elif key and target is not None:
                if not target.get("is_active", True):
                    warnings.append(
                        f"{label}: '{target.get('name') or key}' is switched off, so this step will stop the workflow."
                    )
                if intent_key and _reaches(key, intent_key, workflows):
                    errors.append(
                        f"{label}: '{target.get('name') or key}' runs this workflow again, which would never end."
                    )
                elif _depth(key, workflows) + 1 > _MAX_DEPTH:
                    errors.append(
                        f"{label}: blocks inside blocks go too deep (more than {_MAX_DEPTH} levels)."
                    )
                given = set(ctx["fields"]) | set(params.get("inputs") or {})
                missing = [
                    k
                    for k, f in (target.get("entity_schema") or {}).items()
                    if isinstance(f, dict) and f.get("required") and k not in given
                ]
                if missing:
                    warnings.append(
                        f"{label}: '{target.get('name') or key}' needs "
                        f"{', '.join(missing)}, but this workflow neither asks for it nor gives it "
                        "a value. Add it under 'What it asks for', or give it a value under "
                        "'More options'."
                    )
                for alias in aliases_needed_by(target.get("steps")):
                    if alias not in ctx["aliases"]:
                        errors.append(
                            f"{label}: '{target.get('name') or key}' needs a record called "
                            f"'{alias}', but no earlier step finds one. Run the block that "
                            "finds it (or add a 'Find a record' step) before this step."
                        )
                for alias, tbl in aliases_made_by(target.get("steps")).items():
                    ctx["aliases"].setdefault(alias, tbl)
                    ctx["alias_when"].setdefault(alias, _atoms(step.get("when")))
                inserted.update(
                    (s.get("params") or {}).get("table")
                    for s in normalize_steps(target.get("steps"))
                    if isinstance(s, dict) and s.get("op") == "db.insert_row"
                )

    if ctx["expects"]:
        warnings.append(
            "This building block expects the workflow that runs it to have found, first: "
            + ", ".join(sorted(ctx["expects"]))
            + "."
        )

    # same alias found twice silently overwrites the first, so say so
    seen: dict[str, int] = {}
    for n, step in enumerate(steps, 1):
        if isinstance(step, dict) and step.get("op") == "resolve_entity":
            into = (step.get("params") or {}).get("into")
            if into in seen:
                warnings.append(
                    f"Step {n} finds another record called '{into}' (step {seen[into]} already does), "
                    "so it replaces the first one."
                )
            elif into:
                seen[into] = n
    return {"errors": errors, "warnings": warnings}


def slugify_key(text: str) -> str:
    """intent_key from a title: lowercase letters, digits and underscores."""
    return (
        re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")[:60] or "workflow"
    )
