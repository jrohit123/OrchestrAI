"""The schema editor's engine: turns a short list of plain changes ("ops") into the SQL and the registry rows they need.

A super admin (or the AI, drafting for one) never writes SQL. They describe changes with four ops:

  create_record_type   a new kind of record (Visitor, Booking ...): a real table, its statuses, its fields, the people
                       who can be on it, and a use case that keeps it
  add_field            one more field on a record type
  add_status           one more status on a record type
  set_field_active     switch a field off (or back on)

Everything here only ADDS. Nothing is renamed, nothing is dropped, no column is ever removed: a field that is no longer
wanted is switched off, so no data can be lost. Every name is checked before it reaches SQL, so a name typed in the
dashboard can never become code. build_plan() is a pure function (no database): it gets a snapshot of what exists and
returns the issues, a plain summary, the SQL, and the SQL that would undo it. The caller runs it inside one transaction,
first to try it and roll it back, then for real (app/admin_panel/schema.py)."""

import re
from dataclasses import dataclass, field
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool

# field kind -> (SQL type, default a NOT NULL column gets when records already exist, or None when none makes sense)
KINDS: dict[str, tuple[str, str | None]] = {
    "text": ("text", "''"),
    "number": ("numeric", "0"),
    "date": ("date", None),
    "time": ("time", None),
    "datetime": ("timestamptz", None),
    "choice": ("text", None),  # the default is its first choice
    "phone": ("text", "''"),
    "photo": ("jsonb", None),
    "person": ("uuid REFERENCES public.users(id) ON DELETE SET NULL", None),
    "yesno": ("boolean", "false"),
}
KIND_WORDS = {
    "text": "Words",
    "number": "Number",
    "date": "Date",
    "time": "Time",
    "datetime": "Date and time",
    "choice": "One of a list",
    "phone": "Phone number",
    "photo": "Photos",
    "person": "A person",
    "yesno": "Yes / no",
}

# columns every record table has, which a field may not reuse
RESERVED_COLUMNS = {
    "id", "org_id", "record_number", "status", "custom_fields", "created_by", "created_at", "updated_at",
}  # fmt: skip

# words PostgreSQL does not allow as a bare table or column name; flows write names unquoted, so they are refused up front
SQL_WORDS = set(
    ["all", "analyse", "analyze", "and", "any", "array", "as", "asc", "asymmetric", "authorization", "binary", "both", "case", "cast", "check", "collate", "column", "concurrently", "constraint", "create", "cross", "current_catalog", "current_date", "current_role", "current_schema", "current_time", "current_timestamp", "current_user", "default", "deferrable", "desc", "distinct", "do", "else", "end", "except", "false", "fetch", "for", "foreign", "freeze", "from", "full", "grant", "group", "having", "ilike", "in", "initially", "inner", "intersect", "into", "is", "isnull", "join", "lateral", "leading", "left", "like", "limit", "localtime", "localtimestamp", "natural", "not", "notnull", "null", "offset", "on", "only", "or", "order", "outer", "overlaps", "placing", "primary", "references", "returning", "right", "select", "session_user", "similar", "some", "symmetric", "table", "tablesample", "then", "to", "trailing", "true", "union", "unique", "user", "using", "variadic", "verbose", "when", "where", "window", "with"]
)  # fmt: skip

MAX_FIELDS = 40
MAX_STATUSES = 15
MAX_OPTIONS = 30
_NAME = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
_SLUG = re.compile(r"[^a-z0-9]+")


def slug(text: str, prefix: str = "x") -> str:
    s = _SLUG.sub("_", (text or "").lower()).strip("_")[:40]
    if not s or not s[0].isalpha():
        s = (prefix + "_" + s)[:40].rstrip("_")
    return s


def lit(text: str) -> str:
    """A SQL string literal, for a value that was checked and is only ever a short word."""
    return "'" + str(text).replace("'", "''") + "'"


# ───────────────────────── the ops ─────────────────────────


class FieldIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(min_length=1, max_length=60)
    kind: str = "text"
    required: StrictBool = False
    options: list[str] = Field(default_factory=list, max_length=MAX_OPTIONS)


class StatusIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(min_length=1, max_length=40)
    closed: StrictBool = False


class CreateRecordType(BaseModel):
    model_config = ConfigDict(extra="forbid")
    op: Literal["create_record_type"]
    label: str = Field(min_length=1, max_length=40)  # one: Visitor
    plural: str = Field(min_length=1, max_length=40)  # many: Visitors
    prefix: str = Field(default="", max_length=6)
    statuses: list[StatusIn] = Field(default_factory=list, max_length=MAX_STATUSES)
    fields: list[FieldIn] = Field(default_factory=list, max_length=MAX_FIELDS)
    people: list[str] = Field(default_factory=list, max_length=10)  # kinds of people besides "Created it"
    icon: str = Field(default="", max_length=8)
    about: str = Field(default="", max_length=200)
    read_by_roles: list[str] = Field(default_factory=list, max_length=30)


class AddField(BaseModel):
    model_config = ConfigDict(extra="forbid")
    op: Literal["add_field"]
    record_type: str = Field(min_length=1, max_length=40)
    field: FieldIn


class AddStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    op: Literal["add_status"]
    record_type: str = Field(min_length=1, max_length=40)
    status: StatusIn


class SetFieldActive(BaseModel):
    model_config = ConfigDict(extra="forbid")
    op: Literal["set_field_active"]
    record_type: str = Field(min_length=1, max_length=40)
    key: str = Field(min_length=1, max_length=40)
    active: StrictBool


Op = Annotated[
    CreateRecordType | AddField | AddStatus | SetFieldActive,
    Field(discriminator="op"),
]


# ───────────────────────── what exists, and what comes out ─────────────────────────


@dataclass
class World:
    """A snapshot of what exists now, so a plan can be checked without touching the database."""

    tables: set[str] = field(default_factory=set)
    types: dict[str, dict] = field(default_factory=dict)  # key -> {label, plural, table_name, is_system, statuses}
    fields: dict[str, dict[str, dict]] = field(default_factory=dict)  # type -> key -> {label, kind, is_system, is_active, storage}
    usecase_keys: set[str] = field(default_factory=set)
    roles: dict[str, str] = field(default_factory=dict)  # lower-case name -> id
    can_use_cases: bool = True
    can_role_tables: bool = True


@dataclass
class Plan:
    issues: list[str] = field(default_factory=list)  # anything here: refuse
    warnings: list[str] = field(default_factory=list)
    summary: list[str] = field(default_factory=list)
    sql_up: list[str] = field(default_factory=list)
    sql_down: list[str] = field(default_factory=list)
    writes: list[dict] = field(default_factory=list)  # registry rows to write, in order

    @property
    def ok(self) -> bool:
        return not self.issues


def _copy(w: World) -> World:
    return World(
        tables=set(w.tables),
        types={k: dict(v) for k, v in w.types.items()},
        fields={t: {k: dict(v) for k, v in fs.items()} for t, fs in w.fields.items()},
        usecase_keys=set(w.usecase_keys),
        roles=dict(w.roles),
        can_use_cases=w.can_use_cases,
        can_role_tables=w.can_role_tables,
    )


def _name_problem(name: str, what: str, taken: set[str], reserved: set[str] = frozenset()) -> str | None:
    if not _NAME.match(name):
        return f"“{what}” cannot be turned into a name the database accepts. Use letters and numbers."
    if name in SQL_WORDS:
        return f"“{what}” is a word the database keeps for itself. Pick another name."
    if name in reserved:
        return f"“{what}” is already used by the system on every record. Pick another name."
    if name in taken:
        return f"“{what}” is already taken."
    return None


def _field_problems(f: FieldIn, taken: set[str], *, new_table: bool) -> tuple[str, list[str]]:
    """(the column name, the problems)."""
    probs: list[str] = []
    key = slug(f.label, "f")
    if f.kind not in KINDS:
        probs.append(f"“{f.label}”: the kind “{f.kind}” is not one of: {', '.join(KINDS)}.")
        return key, probs
    p = _name_problem(key, f.label, taken, RESERVED_COLUMNS)
    if p:
        probs.append(p)
    opts = [o.strip() for o in f.options if o.strip()]
    if f.kind == "choice":
        if len(opts) < 2:
            probs.append(f"“{f.label}”: a list needs at least two choices.")
        if any(len(o) > 40 for o in opts) or len({o.lower() for o in opts}) != len(opts):
            probs.append(f"“{f.label}”: each choice must be different and under 40 letters.")
    elif opts:
        probs.append(f"“{f.label}”: only “One of a list” takes choices.")
    if f.required and not new_table and KINDS[f.kind][1] is None and f.kind != "choice":
        probs.append(
            f"“{f.label}” cannot be required on a record type that may already have records, because older ones have no value. Add it as optional."
        )
    return key, probs


def _column_sql(key: str, f: FieldIn, *, with_default: bool) -> str:
    sql_type, default = KINDS[f.kind]
    parts = [f'"{key}" {sql_type}']
    if f.required:
        parts.append("NOT NULL")
        if with_default:
            d = lit(f.options[0].strip()) if f.kind == "choice" else default
            if d is not None:
                parts.append(f"DEFAULT {d}")
    return " ".join(parts)


def _choice_check(table: str, key: str, options: list[str]) -> str:
    listed = ", ".join(lit(o.strip()) for o in options if o.strip())
    return f'CONSTRAINT "{table}_{key}_check" CHECK ("{key}" IS NULL OR "{key}" IN ({listed}))'


def _status_check(table: str, keys: list[str]) -> str:
    return f'CONSTRAINT "{table}_status_check" CHECK (status IN ({", ".join(lit(k) for k in keys)}))'


# ───────────────────────── the plan ─────────────────────────


def build_plan(ops: list, world: World) -> Plan:
    plan = Plan()
    if not ops:
        plan.issues.append("There is nothing to change.")
        return plan
    w = _copy(world)
    for op in ops:
        if isinstance(op, CreateRecordType):
            _create_type(op, w, plan)
        elif isinstance(op, AddField):
            _add_field(op, w, plan)
        elif isinstance(op, AddStatus):
            _add_status(op, w, plan)
        elif isinstance(op, SetFieldActive):
            _set_active(op, w, plan)
    if plan.ok and plan.sql_up:
        plan.warnings.append(
            "This only adds. Nothing is removed or renamed, so no record can be lost. The way back is kept in the history."
        )
    return plan


def _create_type(op: CreateRecordType, w: World, plan: Plan) -> None:
    key = slug(op.label, "r")
    table = slug(op.plural, "t")
    plan_start = len(plan.issues)
    for p in (
        _name_problem(key, op.label, set(w.types)),
        _name_problem(table, op.plural, w.tables | {t["table_name"] for t in w.types.values() if t.get("table_name")}),
    ):
        if p:
            plan.issues.append(p)
    if not w.can_use_cases:
        plan.issues.append("This database has no use cases yet (core-0027). Apply that first.")
    if table in w.tables:
        plan.issues.append(f"There is already a table called {table}.")
    if slug(op.plural, "u") in w.usecase_keys:
        plan.issues.append(f"There is already a use case called “{op.plural}”.")
    statuses = list(op.statuses) or [StatusIn(label="Open"), StatusIn(label="Done", closed=True)]
    skeys = [slug(s.label, "s") for s in statuses]
    if len(set(skeys)) != len(skeys):
        plan.issues.append("Two statuses have the same name.")
    if not any(s.closed for s in statuses) and len(statuses) > 1:
        statuses[-1] = StatusIn(label=statuses[-1].label, closed=True)
    prefix = re.sub(r"[^A-Z0-9]", "", (op.prefix or op.label[:2]).upper())[:6] or "R"
    taken: set[str] = set()
    cols, checks, field_rows = [], [], []
    for i, f in enumerate(op.fields, start=1):
        fkey, probs = _field_problems(f, taken, new_table=True)
        plan.issues.extend(probs)
        taken.add(fkey)
        if not probs:
            cols.append("    " + _column_sql(fkey, f, with_default=False))
            if f.kind == "choice":
                checks.append("    " + _choice_check(table, fkey, f.options))
            field_rows.append({
                "key": fkey, "label": f.label.strip(), "kind": f.kind, "required": f.required,
                "options": [o.strip() for o in f.options if o.strip()], "storage": "column", "sort_order": i,
            })  # fmt: skip
    roles = []
    for r in op.read_by_roles:
        rid = w.roles.get(r.strip().lower())
        if rid:
            roles.append(rid)
        else:
            plan.issues.append(f"There is no role called “{r}”.")
    if len(plan.issues) > plan_start:
        return
    body = [
        "    id uuid DEFAULT gen_random_uuid() PRIMARY KEY",
        "    org_id uuid NOT NULL REFERENCES public.orgs(id) ON DELETE CASCADE",
        "    record_number text",
        f"    status text NOT NULL DEFAULT {lit(skeys[0])}",
        *cols,
        "    custom_fields jsonb NOT NULL DEFAULT '{}'::jsonb",
        "    created_by uuid REFERENCES public.users(id) ON DELETE SET NULL",
        "    created_at timestamptz NOT NULL DEFAULT now()",
        "    updated_at timestamptz NOT NULL DEFAULT now()",
        "    " + _status_check(table, skeys),
        *checks,
    ]  # fmt: skip
    plan.sql_up.append(f'CREATE TABLE public."{table}" (\n' + ",\n".join(body) + "\n)")
    plan.sql_up.append(f'CREATE INDEX "idx_{table}_org" ON public."{table}" (org_id, created_at DESC)')
    plan.sql_down.insert(0, f'DROP TABLE public."{table}"')
    plan.writes.append({
        "what": "record_type", "key": key, "label": op.label.strip(), "plural": op.plural.strip(), "table": table,
        "prefix": prefix, "statuses": [{"key": k, "label": s.label.strip(), "closed": s.closed} for k, s in zip(skeys, statuses)],
    })  # fmt: skip
    plan.writes.extend({"what": "field", "record_type": key, **fr} for fr in field_rows)
    people = [("creator", "Created it", "raiser", False)]
    for name in op.people:
        pk = slug(name, "k")
        if pk not in {p[0] for p in people} and name.strip():
            people.append((pk, name.strip(), "other", True))
    plan.writes.append({"what": "usecase", "key": slug(op.plural, "u"), "name": op.plural.strip(), "icon": op.icon.strip(),
                        "about": op.about.strip(), "record_type": key})  # fmt: skip
    plan.writes.extend({"what": "people", "record_type": key, "key": k, "label": lab, "meaning": m, "added": a, "sort_order": i}
                       for i, (k, lab, m, a) in enumerate(people, start=1))  # fmt: skip
    for rid in roles:
        plan.writes.append({"what": "role_reads", "role_id": rid, "table": table})
    w.tables.add(table)
    w.types[key] = {"label": op.label.strip(), "plural": op.plural.strip(), "table_name": table, "is_system": False,
                    "statuses": [{"key": k, "label": s.label, "closed": s.closed} for k, s in zip(skeys, statuses)]}  # fmt: skip
    w.fields[key] = {fr["key"]: {**fr, "is_system": False, "is_active": True} for fr in field_rows}
    w.usecase_keys.add(slug(op.plural, "u"))
    plan.summary.append(f"A new kind of record, {op.label.strip()}, kept in its own table, with the use case {op.plural.strip()} in the menu.")
    plan.summary.append("Statuses: " + " → ".join(s.label.strip() for s in statuses) + ".")
    if field_rows:
        plan.summary.append("Fields: " + ", ".join(fr["label"] for fr in field_rows) + ".")
    plan.summary.append("People on it: " + ", ".join(lab for _, lab, _, _ in people) + ".")
    if roles:
        plan.summary.append(f"{len(roles)} role(s) may read it.")
    plan.summary.append("Flows can save and read these records as soon as it is applied. Make the flows in the use case’s box.")


def _type(op_type: str, w: World, plan: Plan) -> tuple[str, dict] | None:
    key = slug(op_type, "r")
    t = w.types.get(key)
    if not t:
        plan.issues.append(f"There is no kind of record called “{op_type}”.")
        return None
    return key, t


def _add_field(op: AddField, w: World, plan: Plan) -> None:
    got = _type(op.record_type, w, plan)
    if not got:
        return
    key, t = got
    existing = w.fields.get(key, {})
    taken = set(existing)
    custom = bool(t["is_system"]) or not t.get("table_name")
    # a field kept inside each record has no table to protect, so it may be required from now on
    fkey, probs = _field_problems(op.field, taken, new_table=custom)
    if probs:
        plan.issues.extend(probs)
        return
    row = {"what": "field", "record_type": key, "key": fkey, "label": op.field.label.strip(), "kind": op.field.kind,
           "required": op.field.required, "options": [o.strip() for o in op.field.options if o.strip()],
           "storage": "custom" if custom else "column", "sort_order": len(existing) + 1}  # fmt: skip
    table = t["table_name"]
    if not custom:
        plan.sql_up.append(f'ALTER TABLE public."{table}" ADD COLUMN {_column_sql(fkey, op.field, with_default=True)}')
        plan.sql_down.insert(0, f'ALTER TABLE public."{table}" DROP COLUMN "{fkey}"')
        if op.field.kind == "choice":
            plan.sql_up.append(f'ALTER TABLE public."{table}" ADD {_choice_check(table, fkey, op.field.options)}')
        plan.summary.append(f"A new column “{op.field.label.strip()}” on {t['plural']} ({KIND_WORDS[op.field.kind]}).")
    else:
        plan.summary.append(
            f"A new field “{op.field.label.strip()}” on {t['plural']} ({KIND_WORDS[op.field.kind]}), kept inside each record, so the table itself does not change."
        )
    plan.writes.append(row)
    w.fields.setdefault(key, {})[fkey] = {**row, "is_system": False, "is_active": True}


def _add_status(op: AddStatus, w: World, plan: Plan) -> None:
    got = _type(op.record_type, w, plan)
    if not got:
        return
    key, t = got
    if t["is_system"] or not t.get("table_name"):
        plan.issues.append(f"The statuses of {t['plural']} are set by their own rules, not here.")
        return
    skey = slug(op.status.label, "s")
    have = list(t.get("statuses") or [])
    if skey in {s["key"] for s in have}:
        plan.issues.append(f"{t['plural']} already have the status “{op.status.label}”.")
        return
    if len(have) >= MAX_STATUSES:
        plan.issues.append(f"{t['plural']} cannot have more than {MAX_STATUSES} statuses.")
        return
    table = t["table_name"]
    new = have + [{"key": skey, "label": op.status.label.strip(), "closed": op.status.closed}]
    plan.sql_up.append(f'ALTER TABLE public."{table}" DROP CONSTRAINT IF EXISTS "{table}_status_check"')
    plan.sql_up.append(f'ALTER TABLE public."{table}" ADD {_status_check(table, [s["key"] for s in new])}')
    plan.sql_down.insert(0, f'ALTER TABLE public."{table}" DROP CONSTRAINT IF EXISTS "{table}_status_check"')
    plan.sql_down.insert(1, f'ALTER TABLE public."{table}" ADD {_status_check(table, [s["key"] for s in have])}')
    plan.writes.append({"what": "statuses", "record_type": key, "statuses": new})
    t["statuses"] = new
    plan.summary.append(f"A new status “{op.status.label.strip()}” for {t['plural']}.")


def _set_active(op: SetFieldActive, w: World, plan: Plan) -> None:
    got = _type(op.record_type, w, plan)
    if not got:
        return
    key, t = got
    f = w.fields.get(key, {}).get(op.key)
    if not f:
        plan.issues.append(f"There is no field “{op.key}” on {t['plural']}.")
        return
    if f.get("is_system"):
        plan.issues.append(f"“{f['label']}” is made by the system and stays on.")
        return
    plan.writes.append({"what": "field_active", "record_type": key, "key": op.key, "active": op.active})
    f["is_active"] = op.active
    plan.summary.append(
        f"Switch “{f['label']}” {'on' if op.active else 'off'} on {t['plural']}. "
        + ("Its data stays in the record." if not op.active else "")
    )
