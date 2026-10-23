"""A flow as a non-technical admin builds it with the AI ("Build with AI"), and how it becomes engine steps.

The plain flow is what the admin and the AI edit, and what the dashboard draws as the simple chart. It is kept in
workflows.settings.plain; the engine steps are made from it on every save (compile), never the other way round.

    {"start": {"type": "chat", "words": "book clubhouse"}            or {"type": "time", ...cadence}  (flow_triggers)
     "before": [step, ...],   checks run BEFORE any question (on the first message): they know only Name, Phone, Role, Flat
     "asks":  [{"label": "Place", "q": "Which place?", "kind": "choice", "options": ["Clubhouse", "Party hall"]}, ...],
     "steps": [step, ...]}

Steps (a = what it is):
    say      {text}                                      reply to the person who asked, in their own chat
    tell     {role, text}                                a message to everyone with that role
    set      {name, value}                               keep a value made from a text: "Wing [Wing]"
    find     {list, match: {column label: value}, name}  look in a list; gives "<name> found" (yes / no)
    save     {list, values: {column label: value}}       add a row to a list; gives "<list label> number"
    if       {match: all|any, tests: [{q, op, value}], yes: [...], no: [...]}   decided once (flow.decide)
    stop     {}                                          end here
    approve  {role, text}                                ask everyone in a role to approve; gives "Approval" (Approve / Reject)
    block    {key}                                       run an existing building block
    engine   {step, words, when_words}                   a step from the older editor, kept exactly as it is (a flow
                                                         opened here from the Flows editor; see from_workflow)

Values are written as [Name]: an answer's label, Name / Phone / Role / Flat of the person who asked, or what an
earlier step gives. check() says, in plain words, which step needs a value nothing before it gives."""

import re

from app.services.schema_ops import slug

BASICS = {"Name": "$user.user_name", "Phone": "$user.phone", "Role": "$user.role", "Flat": "$fields._flat"}
KINDS = {"text", "number", "choice", "date", "time", "yesno"}
OPS = {"is": "equals", "not": "not_equals", "oneof": "in", "more": "gt", "less": "lt"}
_REF = re.compile(r"\[([^\[\]]+)\]")


def refs(text) -> list[str]:
    return [m.strip() for m in _REF.findall(str(text or ""))]


def _key(label: str) -> str:
    return slug(label, "a")


def _options(a: dict) -> list[str]:
    o = a.get("options") or []
    return [x.strip() for x in (o.split(",") if isinstance(o, str) else o) if str(x).strip()]


def _list(lists: dict, name) -> dict | None:
    """A list (record type) by its key, label or plural, without minding capitals."""
    want = str(name or "").strip().lower()
    for key, t in lists.items():
        if want in (key.lower(), str(t.get("label", "")).lower(), str(t.get("plural", "")).lower()):
            return {"key": key, **t}
    return None


def _column(lst: dict, label) -> str | None:
    want = str(label or "").strip().lower()
    for key, f in (lst.get("fields") or {}).items():
        if want in (key.lower(), str(f.get("label", "")).lower()):
            return key
    return None


def gives(step: dict, lists: dict) -> list[str]:
    a = step.get("a")
    if a == "set":
        return [step.get("name") or ""]
    if a == "find":
        return [f"{step.get('name') or 'Found'} found"]
    if a == "save":
        lst = _list(lists, step.get("list"))
        return [f"{lst['label'] if lst else step.get('list')} number"]
    if a == "approve":
        return ["Approval"]
    return []


def needs(step: dict) -> list[str]:
    a = step.get("a")
    if a in ("say", "tell", "approve"):
        return refs(step.get("text"))
    if a == "set":
        return refs(step.get("value"))
    if a in ("find", "save"):
        vals = step.get("match") if a == "find" else step.get("values")
        return [r for v in (vals or {}).values() for r in refs(v)]
    if a == "if":
        return [t.get("q") for t in step.get("tests") or [] if t.get("q")]
    return []  # an "engine" step (from the older editor) works with its own names


def ends(lane: list) -> bool:
    return bool(lane) and lane[-1].get("a") == "stop"


def check(plain: dict, lists: dict, roles: set[str] | None = None, blocks: set[str] | None = None) -> list[dict]:
    """[{path, need, text}]: every place a step uses something that is not there. Empty when the flow fits."""
    return analyse(plain, lists, roles, blocks)[0]


def analyse(plain: dict, lists: dict, roles: set[str] | None = None, blocks: set[str] | None = None) -> tuple[list, dict]:
    """(problems, info). info[path] = {needs: [{n, ok}], gives: [...], known: [...]} for every step, what the Card shows:
    what it needs (and whether that is known there), what it gives, and every value known at that place."""
    problems: list[dict] = []
    info: dict = {}
    roles_low = {r.lower() for r in (roles or set())}

    def walk(steps, path, known: set):
        for i, s in enumerate(steps or []):
            p = f"{path}.{i}"
            a = s.get("a")
            info[p] = {"needs": [{"n": n, "ok": n in known} for n in needs(s)], "gives": gives(s, lists), "known": sorted(known)}
            for n in needs(s):
                if n not in known:
                    problems.append({"path": p, "need": n, "text": f"This step uses {n}, and nothing before it gives that."})
            if a in ("find", "save"):
                lst = _list(lists, s.get("list"))
                if not lst:
                    problems.append({"path": p, "need": str(s.get("list")), "text": f"There is no list called {s.get('list')}."})
                else:
                    for col in (s.get("match") if a == "find" else s.get("values")) or {}:
                        if not _column(lst, col):
                            problems.append({"path": p, "need": col, "text": f"The list {lst['label']} has nothing called {col}."})
            if a in ("tell", "approve") and roles is not None and str(s.get("role") or "").lower() not in roles_low:
                problems.append({"path": p, "need": str(s.get("role")), "text": f"There is no role called {s.get('role')}."})
            if a == "if" and roles is not None:  # "Role is Defaulter": a role that does not exist never matches anyone
                for t in s.get("tests") or []:
                    if t.get("q") == "Role" and t.get("op") in ("is", "not", "oneof"):
                        for v in [x.strip() for x in str(t.get("value") or "").split(",") if x.strip()]:
                            if v.lower() not in roles_low:
                                problems.append({"path": p, "need": v, "text": f"There is no role called {v}, so this check never matches anyone."})
            if a == "block" and blocks is not None and s.get("key") not in blocks:
                problems.append({"path": p, "need": str(s.get("key")), "text": f"There is no building block called {s.get('key')}."})
            if a == "if":
                y, n = set(known), set(known)
                walk(s.get("yes"), p + ".yes", y)
                walk(s.get("no"), p + ".no", n)
                ys, ns = ends(s.get("yes") or []), ends(s.get("no") or [])
                known |= (n if ys and not ns else y if ns and not ys else y & n)
            known |= set(gives(s, lists))

    known = set(BASICS)
    walk(plain.get("before"), "before", known)
    info["before"] = {"known": sorted(known)}
    if ends(plain.get("before") or []):
        problems.append({"path": "before", "need": "", "text": "The checks before the questions always stop the flow, so nobody is ever asked anything."})
    after = known | {a.get("label") for a in plain.get("asks") or []}
    info["steps"] = {"known": sorted(after)}
    walk(plain.get("steps"), "steps", after)
    return problems, info


# ───────────────────────── plain -> engine ─────────────────────────


class _Compiler:
    def __init__(self, plain: dict, lists: dict):
        self.plain, self.lists = plain, lists
        self.paths = dict(BASICS)
        for a in plain.get("asks") or []:
            self.paths[a["label"]] = f"$fields.{ask_key(a)}"
        self.steps: list[dict] = []
        self.n_if = 0
        self.n_tmp = 0
        self.uses_flat = False

    def path(self, name: str) -> str:
        if name == "Flat":
            self.uses_flat = True
        return self.paths.get(name) or f"$fields.{_key(name)}"

    def text(self, text) -> str:
        """[Name] -> {$path}, the form flow_ops.fill reads."""
        return _REF.sub(lambda m: "{" + self.path(m.group(1).strip()) + "}", str(text or ""))

    def value(self, v, when):
        """A value for a list column: a whole [Name] is that value; a text with [Names] in it is made first."""
        v = str(v if v is not None else "")
        r = refs(v)
        if len(r) == 1 and v.strip() == f"[{r[0]}]":
            return self.path(r[0])
        if r:
            self.n_tmp += 1
            name = f"_v{self.n_tmp}"
            self.emit({"op": "flow.set", "params": {"field": name, "value": self.text(v)}}, when)
            return f"$fields.{name}"
        return v

    @staticmethod
    def join(when: list) -> dict | None:
        return None if not when else when[0] if len(when) == 1 else {"and": list(when)}

    def emit(self, step: dict, when: list) -> None:
        w = self.join(when)
        self.steps.append({**step, "when": w} if w else step)

    def guard(self, s: dict) -> dict:
        atoms = []
        for t in s.get("tests") or []:
            op, field, value = t.get("op") or "is", self.path(t.get("q") or ""), t.get("value")
            if op == "empty":
                atoms.append({"field": field, "exists": False})
            elif op == "filled":
                atoms.append({"field": field, "exists": True})
            elif op == "oneof":
                atoms.append({"field": field, "in": [x.strip() for x in str(value or "").split(",") if x.strip()]})
            else:
                atoms.append({"field": field, OPS.get(op, "equals"): value})
        if len(atoms) == 1:
            return atoms[0]
        return {"or" if s.get("match") == "any" else "and": atoms}

    def walk(self, steps: list, when: list) -> None:
        for s in steps or []:
            a = s.get("a")
            if a == "say":
                self.emit({"op": "flow.say", "params": {"text": self.text(s.get("text"))}}, when)
            elif a == "tell":
                self.emit({"op": "flow.tell", "params": {"role": s.get("role"), "text": self.text(s.get("text"))}}, when)
            elif a == "set":
                key = _key(s.get("name") or "value")
                self.paths[s.get("name")] = f"$fields.{key}"
                self.emit({"op": "flow.set", "params": {"field": key, "value": self.text(s.get("value"))}}, when)
            elif a == "find":
                lst = _list(self.lists, s.get("list")) or {"key": "", "table_name": "", "fields": {}}
                into = _key(s.get("name") or lst["key"] or "found")
                match = {_column(lst, c) or _key(c): self.value(v, when) for c, v in (s.get("match") or {}).items()}
                self.paths[f"{s.get('name') or 'Found'} found"] = f"$fields.{into}_found"
                self.emit({"op": "flow.lookup", "params": {"table": lst["table_name"], "match": match, "into": into}}, when)
            elif a == "save":
                lst = _list(self.lists, s.get("list")) or {"key": "", "label": str(s.get("list")), "table_name": "", "fields": {}, "prefix": "R"}
                vals = {_column(lst, c) or _key(c): self.value(v, when) for c, v in (s.get("values") or {}).items()}
                table = lst["table_name"]
                self.paths[f"{lst['label']} number"] = f"$inserted.{table}.record_number"
                self.emit({"op": "db.insert_row", "params": {"table": table, "values": vals,
                           "sequence": {"field": "record_number", "prefix": (lst.get("prefix") or "R") + "-{YY}{MM}-", "pad": 4}}}, when)  # fmt: skip
            elif a == "approve":
                self.paths["Approval"] = "$fields.approval"
                self.emit({"op": "ask_approval", "params": {"role": s.get("role"), "message": self.text(s.get("text")), "into": "approval"}}, when)  # fmt: skip
            elif a == "block":
                self.emit({"op": "run_workflow", "params": {"workflow": s.get("key")}}, when)
            elif a == "stop":
                self.emit({"op": "flow.stop", "params": {}}, when)
            elif a == "engine":
                own = (s.get("step") or {}).get("when")
                lane = list(when) + ([own] if own else [])
                step = {k: v for k, v in (s.get("step") or {}).items() if k != "when"}
                w = self.join(lane)
                self.steps.append({**step, "when": w} if w else step)
            elif a == "if":
                self.n_if += 1
                flag = f"_if_{self.n_if}"
                self.emit({"op": "flow.decide", "params": {"into": flag, "when": self.guard(s)}}, when)
                self.walk(s.get("yes"), when + [{"field": f"$fields.{flag}", "equals": "yes"}])
                self.walk(s.get("no"), when + [{"field": f"$fields.{flag}", "equals": "no"}])


def ask_key(a: dict) -> str:
    return a.get("key") or _key(a["label"])


def _seen(a: dict) -> dict:
    """What the admin sees of a question; when none of it changed, a question from the older editor is kept as it was."""
    return {"label": a.get("label"), "q": a.get("q"), "kind": a.get("kind"), "options": _options(a), "optional": bool(a.get("optional"))}


def entity_schema(plain: dict) -> dict:
    out = {}
    for a in plain.get("asks") or []:
        if a.get("spec") and a.get("seen") == _seen(a):
            out[ask_key(a)] = a["spec"]
            continue
        kind = a.get("kind") if a.get("kind") in KINDS else "text"
        f = {
            **(a.get("spec") or {}),
            "type": {"number": "float", "date": "date", "yesno": "boolean"}.get(kind, "string"),
            "label": a["label"],
            "question": a.get("q") or a["label"],
            "required": not a.get("optional"),
        }
        f.pop("enum", None)
        if kind == "date":
            f["format"] = "date"
        if kind == "choice" and _options(a):
            f["enum"] = _options(a)
        out[ask_key(a)] = f
    return out


def compile_flow(plain: dict, lists: dict) -> dict:
    """{"entity_schema", "steps", "training_phrases"} for the workflows row."""
    c = _Compiler(plain, lists)
    c.walk(plain.get("before") or [], [])
    precheck = list(c.steps)
    c.walk(plain.get("steps") or [], [])
    steps = c.steps
    if c.uses_flat:
        steps = [{"op": "flow.my_flat", "params": {}}] + steps
        precheck = [{"op": "flow.my_flat", "params": {}}] + precheck if precheck else precheck
    start = plain.get("start") or {}
    words = [w.strip() for w in str(start.get("words") or "").split(",") if w.strip()]
    if isinstance(start.get("phrases"), list):  # the exact phrases of a flow from the older editor, while not changed
        words = start["phrases"]
    return {"entity_schema": entity_schema(plain), "steps": steps, "training_phrases": words, "precheck": precheck}


# ───────────────────────── a flow from the older editor, opened here ─────────────────────────


def _pretty(key: str) -> str:
    return str(key or "").replace("_", " ").strip().capitalize()


def guard_words(cond, labels: dict) -> str:
    """A "when" condition in words: "Category is filled in and Priority is urgent"."""
    if not isinstance(cond, dict):
        return ""
    if "and" in cond or "or" in cond:
        parts = [guard_words(c, labels) for c in cond.get("and") or cond.get("or") or []]
        return (" and " if "and" in cond else " or ").join(p for p in parts if p)
    if "not" in cond:
        return "not (" + guard_words(cond["not"], labels) + ")"
    f = str(cond.get("field") or "")
    name = labels.get(f[len("$fields."):]) if f.startswith("$fields.") else None
    name = name or _pretty(f.lstrip("$").split(".")[-1])
    for k, w in (("equals", "is"), ("not_equals", "is not"), ("gt", "is more than"), ("gte", "is at least"), ("lt", "is less than"), ("lte", "is at most")):
        if k in cond:
            return f"{name} {w} {cond[k]}"
    if "in" in cond:
        return f"{name} is one of {', '.join(str(x) for x in cond['in'])}"
    if "not_in" in cond:
        return f"{name} is not one of {', '.join(str(x) for x in cond['not_in'])}"
    if "exists" in cond:
        return f"{name} is {'filled in' if cond['exists'] else 'empty'}"
    return name


def engine_words(step: dict, names: dict, labels: dict) -> tuple[str, str]:
    """(what a kept step does, when it runs) in words, with each answer called by its question's short name."""
    from app.services.step_sql import describe_step

    def named(m):
        key = m.group(1).strip().replace(" ", "_")
        return f"[{labels[key]}]" if key in labels else m.group(1)

    return re.sub(r"‹([^›]+)›", named, describe_step(step, names)), guard_words(step.get("when"), labels)


def refresh_words(plain: dict, names: dict) -> dict:
    """The words of the kept steps, worked out again (block names or question labels may have changed)."""
    labels = {ask_key(a): a["label"] for a in plain.get("asks") or [] if a.get("label")}

    def walk(steps):
        for s in steps or []:
            if s.get("a") == "engine":
                s["words"], s["when_words"] = engine_words(s.get("step") or {}, names, labels)
            walk(s.get("yes"))
            walk(s.get("no"))

    walk(plain.get("before"))
    walk(plain.get("steps"))
    return plain


def from_workflow(row: dict, names: dict, schedule: dict | None = None) -> tuple[dict | None, str | None]:
    """(plain flow, None), or (None, the reason in words) when the flow cannot be opened here. Every step is kept exactly
    as it is (an "engine" step, shown in words); the questions keep their own keys. The result is checked: it must give
    back the very same steps, questions and phrases, or it is not used."""
    import json

    from app.services.step_catalog import normalize_steps

    def jb(v, d):
        if v is None:
            return d
        try:
            return json.loads(v) if isinstance(v, str) else v
        except ValueError:
            return None

    kind = row.get("kind") or "workflow"
    report = row.get("workflow_type") == "read"
    raw = row.get("steps")
    steps = [] if report else normalize_steps(jb(raw, []))
    unreadable = not isinstance(steps, list) or any(not isinstance(x, dict) for x in steps)
    if not report and not steps and raw not in (None, "", "[]", []):
        unreadable = True  # there is something there, but not steps: never shown (or saved) as an empty flow
    if unreadable:
        return None, "Its steps could not be read, so it stays in the Advanced editor."
    schema = jb(row.get("entity_schema"), {}) or {}
    asks, labels, used = [], {}, set()
    for key, spec in schema.items():
        spec = spec if isinstance(spec, dict) else {}
        label = str(spec.get("label") or _pretty(key))[:40]
        if label in used or label in BASICS:
            label = f"{label} ({key})"[:40]
        used.add(label)
        labels[key] = label
        typ, akind = str(spec.get("type") or "string"), "text"
        if spec.get("enum"):
            akind = "choice"
        elif typ == "date" or spec.get("format") == "date":
            akind = "date"
        elif typ == "boolean":
            akind = "yesno"
        elif typ in ("integer", "float", "number"):
            akind = "number"
        a = {"label": label, "q": str(spec.get("question") or spec.get("description") or label), "kind": akind, "key": key, "spec": spec}
        if akind == "choice":
            a["options"] = [str(o) for o in spec["enum"]]
        if spec.get("required") is False:
            a["optional"] = True
        a["seen"] = _seen(a)
        asks.append(a)
    phrases = [str(p) for p in jb(row.get("training_phrases"), []) or []]
    if schedule:
        start = {"type": "time", **schedule}
    elif kind == "block":  # runs inside other flows
        start = {"type": "block", "phrases": phrases}
    elif kind == "case_action":  # a button on a ticket
        start = {"type": "button", "phrases": phrases}
    else:
        start = {"type": "chat", "words": ", ".join(phrases), "phrases": phrases}
    plain = {
        "start": start,
        "before": [],
        "asks": asks,
        "steps": [{"a": "engine", "step": st, "words": engine_words(st, names, labels)[0], "when_words": guard_words(st.get("when"), labels)} for st in steps],
    }
    if report:  # a saved report: no steps, one saved question answered and written up
        plain["report"] = {"words": str(row.get("description") or row.get("name") or "the saved question"),
                           "format": "list" if row.get("response_format") == "list" else "ai"}  # fmt: skip
    out = compile_flow(plain, {})
    same = (
        json.dumps(out["steps"], sort_keys=True, default=str) == json.dumps(steps, sort_keys=True, default=str)
        and json.dumps(out["entity_schema"], sort_keys=True, default=str) == json.dumps(schema, sort_keys=True, default=str)
        and (schedule or out["training_phrases"] == phrases)
    )
    if not same:
        return None, "It could not be turned into plain words without changing it, so it stays in the Flows editor."
    return plain, None


# ───────────────────────── what the AI is told about the organisation ─────────────────────────


def lists_from_world(world) -> dict:
    """schema_ops.World -> {key: {label, plural, table_name, fields: {key: {label, kind, options}}}} (active fields)."""
    out = {}
    for key, t in (world.types or {}).items():
        if not t.get("table_name"):
            continue
        out[key] = {
            "label": t.get("label") or key,
            "plural": t.get("plural") or key,
            "table_name": t["table_name"],
            "prefix": re.sub(r"[^A-Z0-9]", "", str(t.get("label") or key).upper())[:2] or "R",
            "fields": {
                fk: {"label": f.get("label") or fk, "kind": f.get("kind")}
                for fk, f in (world.fields.get(key) or {}).items()
                if f.get("is_active", True)
            },
        }
    return out


def lists_text(lists: dict) -> str:
    if not lists:
        return "(none yet)"
    return "\n".join(
        f"- {t['label']} (many: {t['plural']}): " + ", ".join(f"{f['label']} ({f.get('kind') or 'text'})" for f in t["fields"].values())
        for t in lists.values()
    )
