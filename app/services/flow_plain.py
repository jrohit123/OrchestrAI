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
    return []


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
            self.paths[a["label"]] = f"$fields.{_key(a['label'])}"
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
            elif a == "if":
                self.n_if += 1
                flag = f"_if_{self.n_if}"
                self.emit({"op": "flow.decide", "params": {"into": flag, "when": self.guard(s)}}, when)
                self.walk(s.get("yes"), when + [{"field": f"$fields.{flag}", "equals": "yes"}])
                self.walk(s.get("no"), when + [{"field": f"$fields.{flag}", "equals": "no"}])


def entity_schema(plain: dict) -> dict:
    out = {}
    for a in plain.get("asks") or []:
        kind = a.get("kind") if a.get("kind") in KINDS else "text"
        f = {
            "type": {"number": "float", "date": "date", "yesno": "boolean"}.get(kind, "string"),
            "label": a["label"],
            "question": a.get("q") or a["label"],
            "required": not a.get("optional"),
        }
        if kind == "date":
            f["format"] = "date"
        if kind == "choice" and _options(a):
            f["enum"] = _options(a)
        out[_key(a["label"])] = f
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
    return {"entity_schema": entity_schema(plain), "steps": steps, "training_phrases": words, "precheck": precheck}


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
