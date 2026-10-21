"""The plain-words builder's view of a workflow, and back.

The engine runs a flat list of steps; a step can carry a "when" guard and is skipped when the
guard is false. The builder shows the same list as boxes, and shows steps that share a guard as
one "If" box with a YES lane (the steps with the guard) and an OTHERWISE lane (the steps right
after them with the opposite guard). Nested Ifs are guards joined with "and".

Nothing else is translated: every other box carries its step exactly as it is, so a workflow the
builder opens and saves again is the same workflow (the round-trip test checks every live one).
When steps cannot be shown as Ifs without changing them, they stay plain boxes that keep their own
guard ("Only if …"), so nothing is ever lost.

The data panel ("what is known here") is worked out from the same steps: what the workflow asks
for, the records the steps find, the rows they save and the values they work out.
"""

import copy
import json

from app.services.step_catalog import ALIAS_MAKERS, normalize_steps

# guards that are each other's opposite: {"field": f, "equals": v} and {"field": f, "not_equals": v}
_OPPOSITE = {
    "equals": "not_equals",
    "not_equals": "equals",
    "in": "not_in",
    "not_in": "in",
    "gte": "lt",
    "lt": "gte",
    "lte": "gt",
    "gt": "lte",
}


def _same(a, b) -> bool:
    """Equal as stored: the database keeps steps as jsonb, which does not keep key order."""
    return json.dumps(a, sort_keys=True, default=str) == json.dumps(
        b, sort_keys=True, default=str
    )


def opposite(cond: dict) -> dict:
    """The guard that is true exactly when `cond` is false."""
    if isinstance(cond, dict) and set(cond) == {"not"}:
        return cond["not"]
    if isinstance(cond, dict) and "field" in cond and len(cond) == 2:
        (op,) = [k for k in cond if k != "field"]
        if op == "exists":
            return {"field": cond["field"], "exists": not bool(cond["exists"])}
        if op in _OPPOSITE:
            return {"field": cond["field"], _OPPOSITE[op]: cond[op]}
    return {"not": cond}


def _is_opposite(a: dict, b: dict) -> bool:
    return _same(opposite(a), b) or _same(opposite(b), a)


def _split(when):
    """(first test, the rest or None) of a guard: {"and": [A, B, C]} → (A, {"and": [B, C]})."""
    if isinstance(when, dict) and isinstance(when.get("and"), list) and len(when) == 1:
        parts = when["and"]
        if len(parts) >= 2:
            rest = parts[1] if len(parts) == 2 else {"and": parts[1:]}
            return parts[0], rest
    return when, None


def _join(outer: dict, inner):
    """outer and inner as one guard, flat: (A, {"and": [B, C]}) → {"and": [A, B, C]}."""
    if not inner:
        return outer
    if isinstance(inner, dict) and isinstance(inner.get("and"), list) and len(inner) == 1:
        return {"and": [outer, *inner["and"]]}
    return {"and": [outer, inner]}


def _head(step):
    if not isinstance(step, dict) or not step.get("when"):
        return None
    return _split(step["when"])[0]


def _without_head(step: dict) -> dict:
    s = copy.deepcopy(step)
    rest = _split(s.pop("when"))[1]
    if rest:
        s["when"] = rest
    return s


def _step_box(step) -> dict:
    return {"kind": "step", "step": copy.deepcopy(step)}


def _whole_head(steps: list, i: int):
    """The whole guard of steps[i] when it should be one If by itself: an If made with "All of
    these" ({"and": [A, B]}) that has an OTHERWISE lane ({"not": {"and": [A, B]}}). Otherwise
    the guard is taken apart into nested Ifs (see _split)."""
    whole, n, j = steps[i].get("when"), len(steps), i
    while j < n and isinstance(steps[j], dict) and _same(steps[j].get("when"), whole):
        j += 1
    if j < n and isinstance(steps[j], dict) and steps[j].get("when"):
        if _is_opposite(whole, steps[j]["when"]):
            return whole
    return None


def _group(steps: list) -> list:
    out, i, n = [], 0, len(steps)
    while i < n:
        head = _head(steps[i])
        if head is None:
            out.append(_step_box(steps[i]))
            i += 1
            continue
        whole = _whole_head(steps, i)
        if whole is not None and not _same(whole, head):
            box = _if_box(steps, i, whole, whole_guard=True)
            if box:
                out.append(box[0])
                i = box[1]
                continue
        box = _if_box(steps, i, head)
        if box:
            out.append(box[0])
            i = box[1]
        else:  # cannot be shown as an If without changing it: keep the steps as they are
            end = _run_end(steps, i, head)
            out.extend(_step_box(s) for s in steps[i:end])
            i = end
    return out


def _head_of(step, whole_guard: bool):
    if not isinstance(step, dict) or not step.get("when"):
        return None
    return step["when"] if whole_guard else _split(step["when"])[0]


def _without(step: dict, whole_guard: bool) -> dict:
    if not whole_guard:
        return _without_head(step)
    s = copy.deepcopy(step)
    s.pop("when", None)
    return s


def _run_end(steps: list, i: int, head) -> int:
    j = i
    while j < len(steps) and _same(_head(steps[j]), head):
        j += 1
    return max(j, i + 1)


def _if_box(steps: list, i: int, head, whole_guard: bool = False):
    """(the If box for the steps from i on that share `head`, the index after it), or None
    when the steps cannot be shown that way without changing them."""
    n = len(steps)
    yes_end = i
    while yes_end < n and _same(_head_of(steps[yes_end], whole_guard), head):
        yes_end += 1
    no_head, no_end = None, yes_end
    nxt = _head_of(steps[yes_end], whole_guard) if yes_end < n else None
    if nxt is not None and _is_opposite(head, nxt):
        no_head = nxt
        while no_end < n and _same(_head_of(steps[no_end], whole_guard), no_head):
            no_end += 1
    box = {
        "kind": "if",
        "rule": copy.deepcopy(head),
        "yes": _group([_without(s, whole_guard) for s in steps[i:yes_end]]),
        "no": _group([_without(s, whole_guard) for s in steps[yes_end:no_end]]),
    }
    if no_head is not None and not _same(no_head, opposite(head)):
        box["rule_no"] = copy.deepcopy(no_head)
    if yes_end > i and _same(from_boxes([box]), steps[i:no_end]):
        return box, no_end
    return None


def to_boxes(steps) -> list:
    """The steps as builder boxes. Saving the boxes again gives back the same steps."""
    steps = normalize_steps(steps)
    boxes = _group(steps)
    if not _same(from_boxes(boxes), steps):  # belt and braces: never show a changed flow
        return [_step_box(s) for s in steps]
    return boxes


def _with_guard(step: dict, cond: dict) -> dict:
    s = copy.deepcopy(step)
    s["when"] = _join(cond, s.get("when"))
    return s


def from_boxes(boxes) -> list:
    """The boxes as the engine's flat list of steps."""
    out = []
    for box in boxes or []:
        kind = box.get("kind")
        if kind == "step":
            out.append(copy.deepcopy(box["step"]))
        elif kind == "if":
            rule = box.get("rule")
            if not rule:
                raise ValueError("An If box has no rule.")
            no_rule = box.get("rule_no") or opposite(rule)
            out += [_with_guard(s, rule) for s in from_boxes(box.get("yes"))]
            out += [_with_guard(s, no_rule) for s in from_boxes(box.get("no"))]
        else:
            raise ValueError(f"Unknown kind of box: {kind!r}")
    return out


# ── the data panel ───────────────────────────────────────────────────────────


def _pretty(name: str) -> str:
    text = str(name or "").replace("_", " ").strip()
    return text[:1].upper() + text[1:]


def token_for(path: str) -> str:
    """How a piece of data is written inside a message: answers as {name}, the case as
    {case_column} (both understood since the start), anything else as {record.column}."""
    parts = path.lstrip("$").split(".")
    if parts[0] == "fields" and len(parts) == 2:
        return "{" + parts[1] + "}"
    if parts[0] == "case" and len(parts) == 2:
        return "{case_" + parts[1] + "}"
    return "{" + ".".join(parts) + "}"


def _item(label: str, path: str, group: str) -> dict:
    return {"label": label, "path": path, "token": token_for(path), "group": group}


def base_data(entity_schema: dict | None, kind: str = "workflow") -> list:
    """What is known before the first step: the person, and what the workflow asks for (for a
    building block: what it needs from the workflow that uses it)."""
    items = [
        _item("Name", "$user.name", "The person"),
        _item("Phone", "$user.phone", "The person"),
        _item("Email", "$user.email", "The person"),
        _item("Role", "$user.role", "The person"),
    ]
    group = "What it needs" if kind == "block" else "Their answers"
    for key, spec in (entity_schema or {}).items():
        spec = spec if isinstance(spec, dict) else {}
        items.append(_item(spec.get("label") or _pretty(key), f"$fields.{key}", group))
    return items


def data_made_by(
    step, schema: dict, workflows: dict | None = None, _seen: tuple = ()
) -> list:
    """What one step leaves for the steps after it, as data-panel items."""
    if not isinstance(step, dict):
        return []
    op = step.get("op")
    p = step.get("params") or {}
    workflows = workflows or {}
    items: list[dict] = []
    if op == "resolve_entity":
        table = p.get("table")
        into = p.get("into") or str(table or "").rstrip("s")
        group = _pretty(into)
        for col in sorted(schema.get(table) or []):
            items.append(_item(f"{group} – {_pretty(col)}", f"${into}.{col}", group))
        for alias in p.get("expose") or {}:
            items.append(_item(_pretty(alias), f"$fields.{alias}", group))
    elif op in ALIAS_MAKERS:
        key, default, extra = ALIAS_MAKERS[op]
        group = _pretty(p.get(key) or default)
        items += [_item(_pretty(f), f"$fields.{f}", group) for f in extra]
    elif op == "derive_field" and p.get("field"):
        items.append(_item(_pretty(p["field"]), f"$fields.{p['field']}", "Worked out"))
    elif op in ("db.insert_row", "sheets.insert_row") and isinstance(
        p.get("table"), str
    ):
        table = p["table"]
        group = "New " + _pretty(table).rstrip("s").lower()
        cols = set(schema.get(table) or []) | set((p.get("values") or {}).keys())
        seq = (p.get("sequence") or {}).get("field")
        if seq:
            cols.add(seq)
        for col in sorted(cols):
            items.append(
                _item(
                    f"{group} – {_pretty(col).lower()}", f"$inserted.{table}.{col}", group
                )
            )
    elif op == "ask_approval":
        into = p.get("into") or "approval"
        group = _pretty(into)
        items += [
            _item(f"{group} – answer", f"$fields.{into}", group),
            _item(f"{group} – who answered", f"$fields.{into}_by", group),
        ]
    elif op == "ai.ask":
        group = "The AI"
        if p.get("task") == "extract":
            items += [
                _item(_pretty(f.get("name")), f"$fields.{f.get('name')}", group)
                for f in p.get("fields") or []
                if isinstance(f, dict) and f.get("name")
            ]
        elif p.get("into"):
            items.append(_item(_pretty(p["into"]), f"$fields.{p['into']}", group))
    elif op == "run_workflow":
        key = p.get("workflow")
        block = workflows.get(key) or {}
        if key and key not in _seen:
            name = block.get("name") or _pretty(key)
            outputs = ((block.get("settings") or {}).get("outputs")) or []
            if outputs:  # the block names what it gives back
                items += [
                    _item(f"{name} – {o.get('label')}", o.get("path"), name)
                    for o in outputs
                    if isinstance(o, dict) and o.get("path") and o.get("label")
                ]
            else:  # otherwise everything its steps leave behind
                for s in normalize_steps(block.get("steps")):
                    items += data_made_by(s, schema, workflows, (*_seen, key))
    return items


def builder_view(
    steps, entity_schema: dict | None, schema: dict, workflows: dict, kind: str
) -> dict:
    """Everything the builder needs to show a workflow: its boxes, what is known before the
    first step, and what each step adds (in the order the steps run)."""
    steps = normalize_steps(steps)
    return {
        "boxes": to_boxes(steps),
        "base_data": base_data(entity_schema, kind),
        "step_data": [data_made_by(s, schema, workflows) for s in steps],
    }
