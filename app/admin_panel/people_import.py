"""Adding and updating many people at once from a CSV or Excel file: who they are, their role, and (where the
organisation keeps a resident list) which flat they are in and how.

One row of the file is one person in one flat. A person with two flats has two rows with the same number or email;
a person with no flat has one row and empty flat columns.

Two steps, so nothing is saved by surprise:
  * preview: the file is read and compared with what is already saved. A person already here is FOUND (by number,
             then by email) and only what differs is listed: an empty detail is filled in, a different one is shown
             as old -> new. Nothing is written. Each change has a tick (on unless it needs a look) and can be unticked.
  * commit:  the same rows come back with the changes that were unticked. The plan is worked out again from the
             database as it is now (the screen is not trusted), and each person is saved on their own, so one bad
             row never stops the others.

An empty cell never erases what is saved. People who are not in the file are not touched. Both a super admin and an
admin of the organisation may use it. Nothing here names a role: roles and the words for values are read from the
database."""

import csv
import io
import re
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.admin_panel.common import (
    CtxDep,
    PanelRoute,
    check_values,
    log_event,
    people_channel,
    tx,
)
from app.admin_panel.people import _EMAIL
from app.db import fetch_all
from app.logging_config import get_context_logger

logger = get_context_logger(__name__)

router = APIRouter(
    prefix="/admin/{org_slug}/api/v2", tags=["admin-panel"], route_class=PanelRoute
)

MAX_ROWS = 500
MAX_CHARS = 1_500_000
MAX_BYTES = 4_000_000  # an Excel file
# What a column may be called in the file (lower case, letters only), for each thing we read.
ALIASES = {
    "name": {"name", "fullname", "person", "member", "resident", "contactname"},
    "email": {"email", "emailaddress", "mail", "emailid"},
    "phone": {
        "phone",
        "mobile",
        "mobilenumber",
        "mobileno",
        "phonenumber",
        "phoneno",
        "contact",
        "contactnumber",
        "whatsapp",
        "whatsappnumber",
        "number",
    },
    "role": {"role", "type", "access", "accesslevel", "usertype"},
    "wing": {"wing", "tower", "block", "building"},
    "flat": {"flat", "flatno", "flatnumber", "unit", "unitno", "apartment", "house"},
    "relation": {
        "relation",
        "relationtoflat",
        "relationship",
        "occupancy",
        "residenttype",
        "ownerortenant",
    },
    "primary": {"primary", "primarymember", "isprimary", "primaryowner"},
    "lives": {
        "liveshere",
        "lives",
        "residing",
        "residinghere",
        "stayshere",
        "livesinflat",
        "livesintheflat",
    },
}
# Other words people write for a relation value (the values themselves and their dashboard words always work).
RELATION_WORDS = {
    "co_owner": {"coowner", "jointowner", "associatemember", "associate"},
    "owner_family": {"family", "familymember", "ownersfamily", "ownerfamily"},
    "tenant_family": {"tenantsfamily", "tenantfamily"},
}
# Which side of the flat a relation is on: a new person with no role in the file gets the role with that name, if any.
RELATION_SIDE = {
    "owner": "owner",
    "co_owner": "owner",
    "owner_family": "owner",
    "tenant": "tenant",
    "tenant_family": "tenant",
}
TENANT_SIDE = {"tenant", "tenant_family"}
YES = {"yes", "y", "true", "1", "haan", "ha", "ok"}
NO = {"no", "n", "false", "0", "nahi", "na"}
FLAT_IN_ONE = re.compile(r"^([A-Z]{1,3})\s*[-/ ]\s*(\w+)$")


def _key(text: str) -> str:
    return re.sub(r"[^a-z]", "", (text or "").lower())


def _csv_table(text: str) -> list[list[str]]:
    text = (text or "").lstrip("﻿")
    if not text.strip():
        raise ValueError("The file is empty.")
    if len(text) > MAX_CHARS:
        raise ValueError("The file is too big. Split it into smaller files.")
    if "\x00" in text:  # an Excel or other binary file read as text
        raise ValueError(
            "This file cannot be read. Upload a CSV or an Excel (.xlsx) file."
        )
    first = next((ln for ln in text.splitlines() if ln.strip()), "")
    delimiter = (
        max(",;	|", key=first.count) if any(d in first for d in ",;	|") else ","
    )
    try:
        return [
            [c.strip() for c in row]
            for row in csv.reader(io.StringIO(text), delimiter=delimiter)
            if any(c.strip() for c in row)
        ]
    except csv.Error as e:
        raise ValueError(
            "This file cannot be read as a CSV. Upload a CSV or an Excel (.xlsx) file."
        ) from e


def _cell_text(v) -> str:
    """One Excel cell as text: a whole number stays whole (a phone number typed as a number keeps no .0)."""
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def _xlsx_table(data: bytes) -> list[list[str]]:
    """The first sheet of an Excel file as rows of text."""
    import openpyxl

    if len(data) > MAX_BYTES:
        raise ValueError("The file is too big. Split it into smaller files.")
    try:
        book = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as e:
        raise ValueError(
            "This Excel file cannot be read. Save it again as .xlsx, or as a CSV."
        ) from e
    try:
        sheet = book.worksheets[0]
        table = []
        for row in sheet.iter_rows(values_only=True):
            cells = [_cell_text(v) for v in row]
            if any(cells):
                table.append(cells)
            if len(table) > MAX_ROWS + 1:
                break
        return table
    finally:
        book.close()


def read_csv(text: str) -> tuple[dict[str, int], list[list[str]]]:
    """(which column holds what, the rows under the header) of a CSV. Raises ValueError with a sentence for the person."""
    return _columns(_csv_table(text))


def read_upload(
    text: str = "", xlsx: bytes | None = None
) -> tuple[dict[str, int], list[list[str]]]:
    """A CSV (as text) or an Excel file (as bytes): the same columns and rows either way."""
    return _columns(_xlsx_table(xlsx) if xlsx is not None else _csv_table(text))


def _columns(table: list[list[str]]) -> tuple[dict[str, int], list[list[str]]]:
    if len(table) < 2:
        raise ValueError(
            "The file needs a first row with column names (for example Name, Phone, Email) and at least one person."
        )
    header = [_key(c) for c in table[0]]
    columns: dict[str, int] = {}
    for field, names in ALIASES.items():
        for i, h in enumerate(header):
            if h in names and field not in columns and i not in columns.values():
                columns[field] = i
    if "name" not in columns or not ({"email", "phone"} & set(columns)):
        raise ValueError(
            "The first row must have a Name column and a Phone or Email column. Download the sample file to see the layout."
        )
    if len(table) - 1 > MAX_ROWS:
        raise ValueError(
            f"Up to {MAX_ROWS} rows at a time. This file has {len(table) - 1}."
        )
    return columns, table[1:]


def clean_number(raw: str, country: str) -> str:
    """A number the way the chat bot knows it (+ and digits). A 10-digit number needs the country code from the screen."""
    text = re.sub(r"[\s().-]", "", raw or "")
    if text.startswith("00"):
        text = "+" + text[2:]
    code = re.sub(r"\D", "", country or "")
    if code and re.fullmatch(r"\d{10}", text):
        text = "+" + code + text
    elif code and text.startswith("0") and re.fullmatch(r"0\d{10}", text):
        text = "+" + code + text[1:]
    elif code and re.fullmatch(re.escape(code) + r"\d{10}", text):
        text = "+" + text
    if not re.fullmatch(r"\+\d{8,15}", text):
        raise ValueError(
            "The number needs its country code, like +91 98765 43210."
            if not code
            else "That does not look like a phone number."
        )
    return text


def flat_parts(wing: str, flat: str) -> tuple[str | None, str]:
    """(wing, flat) the way they are saved: trimmed and in capitals. "A-101" with no wing becomes ("A", "101")."""
    wing = " ".join((wing or "").split()).upper()
    flat = " ".join((flat or "").split()).upper()
    if flat and not wing:
        m = FLAT_IN_ONE.match(flat)
        if m:
            wing, flat = m.group(1), m.group(2)
    return (wing or None), flat


def flat_name(wing: str | None, flat: str) -> str:
    return f"{wing}-{flat}" if wing else flat


def _yes_no(text: str) -> bool | None:
    t = _key(text) or (text or "").strip()
    if t in YES:
        return True
    if t in NO:
        return False
    return None


# ── one line of the file, as the screen sends it back ────────────────────────


class Entry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    line: int = 0
    name: str = Field("", max_length=80)
    email: str = Field("", max_length=160)
    phone: str | None = Field(None, max_length=40)  # already cleaned (+ and digits)
    phone_note: str = Field("", max_length=200)
    role_text: str = Field("", max_length=80)
    wing: str = Field("", max_length=40)
    flat: str = Field("", max_length=40)
    relation_text: str = Field("", max_length=60)
    primary_text: str = Field("", max_length=20)
    lives_text: str = Field("", max_length=20)


def entries_from(
    columns: dict[str, int], data: list[list[str]], country: str, by_number: bool
) -> list[dict]:
    def cell(row, field):
        i = columns.get(field)
        return row[i].strip() if i is not None and i < len(row) else ""

    out = []
    for n, row in enumerate(data, start=2):  # n is the line number in the file
        phone, note, raw = None, "", cell(row, "phone")
        if by_number and raw:
            try:
                phone = clean_number(raw, country)
            except ValueError as e:
                note = f"{e} ({raw})"
        out.append(
            Entry(
                line=n,
                name=" ".join(cell(row, "name").split())[:80],
                email=cell(row, "email").lower()[:160],
                phone=phone,
                phone_note=note,
                role_text=cell(row, "role")[:80],
                wing=cell(row, "wing")[:40],
                flat=cell(row, "flat")[:40],
                relation_text=cell(row, "relation")[:60],
                primary_text=cell(row, "primary")[:20],
                lives_text=cell(row, "lives")[:20],
            ).model_dump()
        )
    return out


# ── comparing the file with what is saved ────────────────────────────────────


async def _relations(ctx) -> tuple[list[str], dict[str, str]]:
    """The relation values this database allows, and every word (value, dashboard word, other words) -> value."""
    values = await check_values(ctx, "residents", "relation")
    labels = (ctx.settings or {}).get("labels") or {}
    words: dict[str, str] = {}
    for v in values:
        words[_key(v)] = v
        if isinstance(labels.get(v), str):
            words[_key(labels[v])] = v
        for w in RELATION_WORDS.get(v, ()):
            words.setdefault(w, v)
    return values, words


def _flats_on(ctx) -> bool:
    return bool(ctx.caps.get("residents") and ctx.caps.get("flat_people"))


def _same_person(a: str, b: str) -> bool:
    """Whether two names could be the same person: they share at least one word."""
    wa, wb = set(_key_words(a)), set(_key_words(b))
    return bool(wa & wb)


def _key_words(name: str) -> list[str]:
    return [w for w in (_key(x) for x in (name or "").split()) if len(w) > 1]


async def build_plan(ctx, entries: list[dict]) -> dict:
    """What saving these lines would do, person by person. Writes nothing."""
    by_number = await people_channel(ctx.source_key) != "telegram"
    flats_on = _flats_on(ctx)
    roles = await fetch_all(
        "SELECT id, name FROM roles WHERE org_id = $1",
        ctx.org_id,
        source_key=ctx.source_key,
    )
    role_by = {_key(r["name"]): r for r in roles}
    role_name = {r["id"]: r["name"] for r in roles}
    users = await fetch_all(
        "SELECT id, name, lower(email) AS email, phone, role_id FROM users WHERE org_id = $1",
        ctx.org_id,
        source_key=ctx.source_key,
    )
    by_phone = {u["phone"]: u for u in users if u["phone"]}
    by_email = {u["email"]: u for u in users if u["email"]}
    homes: dict = {}  # (user_id, wing, flat) -> row
    primary_of: dict = {}  # (wing, flat) -> (user_id, name)
    rel_values, rel_words = [], {}
    if flats_on:
        rel_values, rel_words = await _relations(ctx)
        for h in await fetch_all(
            "SELECT h.id, h.user_id, COALESCE(h.wing, '') AS wing, h.flat_no, h.relation, h.is_primary, "
            "h.lives_here, u.name FROM residents h LEFT JOIN users u ON u.id = h.user_id WHERE h.org_id = $1",
            ctx.org_id,
            source_key=ctx.source_key,
        ):
            if h["user_id"]:
                homes[(h["user_id"], h["wing"], h["flat_no"])] = h
            if h["is_primary"]:
                primary_of[(h["wing"], h["flat_no"])] = (h["user_id"], h["name"])
    labels = (ctx.settings or {}).get("labels") or {}

    def rel_word(v):
        return labels.get(v) or (v or "").replace("_", " ").capitalize()

    # 1. lines -> people (the same number or email is the same person)
    groups: list[dict] = []
    index: dict[str, dict] = {}
    skipped: list[dict] = []
    for e in entries:
        email = (e.get("email") or "").strip().lower()
        phone = e.get("phone") if by_number else None
        name = " ".join((e.get("name") or "").split())
        if email and not _EMAIL.match(email):
            skipped.append(
                {
                    "line": e["line"],
                    "name": name,
                    "reason": f"The email “{email}” does not look right.",
                }
            )
            continue
        if not phone and not email:
            skipped.append(
                {
                    "line": e["line"],
                    "name": name or "(no name)",
                    "reason": e.get("phone_note")
                    or (
                        "No email, so this person cannot be told apart from others."
                        if not by_number
                        else "No phone and no email, so this person could never be reached."
                    ),
                }
            )
            continue
        keys = [k for k in (phone and "p:" + phone, email and "e:" + email) if k]
        found = [index[k] for k in keys if k in index]
        if len({id(g) for g in found}) > 1:
            skipped.append(
                {
                    "line": e["line"],
                    "name": name,
                    "reason": "Its number and its email belong to two different people higher up in the file.",
                }
            )
            continue
        g = found[0] if found else None
        if g is None:
            g = {"lines": [], "phone": None, "email": None, "name": "", "notes": []}
            groups.append(g)
        if phone and g["phone"] and g["phone"] != phone:
            g["notes"].append(
                f"Line {e['line']} has another number for the same person; the first one is used."
            )
        if email and g["email"] and g["email"] != email:
            g["notes"].append(
                f"Line {e['line']} has another email for the same person; the first one is used."
            )
        g["phone"] = g["phone"] or phone
        g["email"] = g["email"] or email or None
        g["name"] = g["name"] or name
        if e.get("phone_note"):
            g["notes"].append(f"Line {e['line']}: {e['phone_note']}")
        g["lines"].append(e)
        for k in keys:
            index[k] = g

    # 2. each person: found or new, and what would change
    people: list[dict] = []
    primary_taken: dict = {}  # (wing, flat) -> key of the person in this file who gets it
    for g in groups:
        first = g["lines"][0]
        key = f"L{first['line']}"
        p = {
            "key": key,
            "lines": [e["line"] for e in g["lines"]],
            "name": g["name"],
            "email": g["email"],
            "phone": g["phone"],
            "match": None,
            "status": "new",
            "problems": [],
            "notes": list(g["notes"]),
            "changes": [],
            "role_id": None,
        }
        u_phone = by_phone.get(g["phone"]) if g["phone"] else None
        u_email = by_email.get(g["email"]) if g["email"] else None
        if u_phone and u_email and u_phone["id"] != u_email["id"]:
            p["status"] = "skip"
            p["problems"].append(
                f"The number belongs to {u_phone['name']} and the email to {u_email['name']}. Fix the file."
            )
            people.append(p)
            continue
        u = u_phone or u_email
        role_texts = [e["role_text"] for e in g["lines"] if e.get("role_text")]
        role = None
        if role_texts:
            role = role_by.get(_key(role_texts[0]))
            if not role:
                p["notes"].append(f"No role called “{role_texts[0]}”.")

        def change(cid, kind, label, old, new, use=True, warn="", p=p, key=key):
            p["changes"].append(
                {
                    "id": f"{key}:{cid}",
                    "kind": kind,
                    "label": label,
                    "old": old,
                    "new": new,
                    "use": use,
                    "warn": warn,
                }
            )

        if u:
            p["match"] = {
                "id": str(u["id"]),
                "name": u["name"],
                "role": role_name.get(u["role_id"]),
            }
            p["status"] = "same"
            if g["name"] and g["name"] != u["name"]:
                same = _same_person(g["name"], u["name"])
                change(
                    "name",
                    "person",
                    "Name",
                    u["name"],
                    g["name"],
                    use=same,
                    warn=""
                    if same
                    else "The names do not match. Is this the same person? Tick only if it is.",
                )
            if g["email"] and g["email"] != (u["email"] or None):
                other = by_email.get(g["email"])
                if other and other["id"] != u["id"]:
                    p["notes"].append(
                        f"The email {g['email']} is already used by {other['name']}, so it is not changed."
                    )
                else:
                    change("email", "person", "Email", u["email"], g["email"])
            if g["phone"] and g["phone"] != u["phone"]:
                other = by_phone.get(g["phone"])
                if other and other["id"] != u["id"]:
                    p["notes"].append(
                        f"The number is already used by {other['name']}, so it is not changed."
                    )
                else:
                    change("phone", "person", "Number", u["phone"], g["phone"])
            if role and role["id"] != u["role_id"]:
                mine = (
                    ctx.level != "super"
                    and ctx.account_email
                    and (u["email"] or "") == ctx.account_email.lower()
                )
                if mine:
                    p["notes"].append(
                        "Your own role is not changed from a file. Ask a super admin."
                    )
                else:
                    change(
                        "role",
                        "person",
                        "Role",
                        role_name.get(u["role_id"]),
                        role["name"],
                        warn="This changes what they can do in the chat bot.",
                    )
                    p["changes"][-1]["role_id"] = str(role["id"])
        else:
            if len(g["name"]) < 2:
                p["status"] = "skip"
                p["problems"].append("The name is missing.")
                people.append(p)
                continue
            if not role:
                rels = [
                    rel_words.get(_key(e.get("relation_text") or ""))
                    for e in g["lines"]
                ]
                side = next((RELATION_SIDE.get(r) for r in rels if r), None)
                role = role_by.get(side) if side else None
            p["role_id"] = str(role["id"]) if role else None
            change(
                "new",
                "new",
                "New person",
                None,
                g["name"] + (f" as {role['name']}" if role else ""),
            )

        # flats
        seen_flats: set = set()
        for e in g["lines"]:
            if not (e.get("flat") or "").strip():
                if (
                    e.get("wing")
                    or e.get("relation_text")
                    or e.get("primary_text")
                    or e.get("lives_text")
                ):
                    p["notes"].append(
                        f"Line {e['line']}: no flat number, so the flat details are left out."
                    )
                continue
            if not flats_on:
                if not p.get("_flat_note"):
                    p["notes"].append(
                        "This organisation does not keep flats yet, so the flat columns are left out."
                    )
                    p["_flat_note"] = True
                continue
            wing, flat = flat_parts(e.get("wing") or "", e["flat"])
            where = flat_name(wing, flat)
            fk = (wing or "", flat)
            if fk in seen_flats:
                p["notes"].append(
                    f"Line {e['line']}: {where} is listed twice for this person; the first line is used."
                )
                continue
            seen_flats.add(fk)
            have = homes.get((u["id"], fk[0], fk[1])) if u else None
            rel_text = (e.get("relation_text") or "").strip()
            rel = rel_words.get(_key(rel_text)) if rel_text else None
            if rel_text and not rel:
                p["notes"].append(
                    f"Line {e['line']}: “{rel_text}” is not a relation we know"
                    + (
                        ", so the saved one is kept."
                        if have
                        else ". Pick one below, or that flat is left out."
                    )
                )
            if not rel and not have:
                change(
                    "flat:" + where,
                    "flat",
                    where,
                    None,
                    None,
                    use=False,
                    warn="Pick how they are linked to the flat (Owner, Tenant...).",
                )
                p["changes"][-1].update(
                    {
                        "line": e["line"],
                        "needs_relation": True,
                        "relations": [[v, rel_word(v)] for v in rel_values],
                    }
                )
                continue
            rel = rel or have["relation"]
            prim = _yes_no(e.get("primary_text") or "")
            lives = _yes_no(e.get("lives_text") or "")
            if (e.get("primary_text") or "").strip() and prim is None:
                p["notes"].append(
                    f"Line {e['line']}: “{e['primary_text']}” under Primary member is not Yes or No; it is left as it was."
                )
            if (e.get("lives_text") or "").strip() and lives is None:
                p["notes"].append(
                    f"Line {e['line']}: “{e['lives_text']}” under Lives here is not Yes or No; it is left as it was."
                )
            prim = prim if prim is not None else (have["is_primary"] if have else False)
            if lives is None:
                lives = have["lives_here"] if have else True
                if not have:
                    p["notes"].append(
                        f"{where}: “Lives here” is empty, so we took it as Yes."
                    )
            if prim and rel in TENANT_SIDE:
                prim = False
                p["notes"].append(
                    f"{where}: a tenant cannot be the primary member, so Primary member is No."
                )
            warn = ""
            if prim:
                if fk in primary_taken and primary_taken[fk] != key:
                    prim = False
                    p["notes"].append(
                        f"{where} already has a primary member higher up in the file, so this one is not."
                    )
                else:
                    primary_taken[fk] = key
                    holder = primary_of.get(fk)
                    if holder and (not u or holder[0] != u["id"]):
                        warn = f"{holder[1] or 'Someone else'} stops being the primary member of {where}."
            new = {"relation": rel, "is_primary": prim, "lives_here": lives}

            def text(d):
                return ", ".join(
                    [rel_word(d["relation"])]
                    + (["★ primary member"] if d["is_primary"] else [])
                    + ["lives here" if d["lives_here"] else "lives elsewhere"]
                )

            if have:
                old = {
                    "relation": have["relation"],
                    "is_primary": have["is_primary"],
                    "lives_here": have["lives_here"],
                }
                if old != new:
                    change(
                        "flat:" + where, "flat", where, text(old), text(new), warn=warn
                    )
                    p["changes"][-1].update({"line": e["line"], **new})
            else:
                change("flat:" + where, "flat", where, None, text(new), warn=warn)
                p["changes"][-1].update({"line": e["line"], **new})
        p.pop("_flat_note", None)
        if p["match"] and p["changes"]:
            p["status"] = "update"
        if any(c["warn"] and not c["use"] for c in p["changes"]):
            p["status"] = "check" if p["status"] != "new" else "new"
        people.append(p)

    counts = {
        k: sum(1 for p in people if p["status"] == k)
        for k in ("new", "update", "same", "check", "skip")
    }
    counts["skip"] += len(skipped)
    return {
        "people": people,
        "skipped": skipped,
        "counts": counts,
        "flats": flats_on,
        "by_number": by_number,
        "relations": [[v, rel_word(v)] for v in rel_values],
    }


# ── the two calls ────────────────────────────────────────────────────────────


class PreviewBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    csv_text: str = ""
    file_b64: str | None = Field(None, max_length=6_000_000)  # an Excel file, base64
    file_name: str = Field("", max_length=200)
    country: str = Field("", max_length=8)  # for 10-digit numbers, like +91


@router.post("/people/import/preview")
async def preview(ctx: CtxDep, body: PreviewBody):
    try:
        if body.file_b64:
            import base64

            try:
                raw = base64.b64decode(body.file_b64, validate=True)
            except ValueError as e:
                raise ValueError(
                    "The file did not arrive whole. Choose it again."
                ) from e
            columns, data = read_upload(xlsx=raw)
        else:
            columns, data = read_upload(body.csv_text)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    by_number = await people_channel(ctx.source_key) != "telegram"
    entries = entries_from(columns, data, body.country, by_number)
    plan = await build_plan(ctx, entries)
    roles = await fetch_all(
        "SELECT id, name FROM roles WHERE org_id = $1 ORDER BY name",
        ctx.org_id,
        source_key=ctx.source_key,
    )
    return {
        **plan,
        "columns": sorted(columns),
        "entries": entries,
        "roles": [{"id": str(r["id"]), "name": r["name"]} for r in roles],
    }


class CommitBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entries: list[Entry] = Field(..., max_length=MAX_ROWS)
    skip: list[str] = Field(
        default_factory=list, max_length=5000
    )  # change ids left unticked
    use: list[str] = Field(
        default_factory=list, max_length=5000
    )  # change ids ticked that start unticked
    roles: dict[str, UUID] = Field(
        default_factory=dict
    )  # person key -> role, for new people
    relations: dict[str, str] = Field(
        default_factory=dict
    )  # line number -> relation picked on screen


@router.post("/people/import/commit")
async def commit(ctx: CtxDep, body: CommitBody):
    """Save what was kept. The plan is worked out again here from the database as it is now."""
    entries = [e.model_dump() for e in body.entries]
    if not entries:
        raise HTTPException(400, "There is nobody to save.")
    # a relation picked on the screen goes into its line, as if the file had said it
    for e in entries:
        if str(e["line"]) in body.relations:
            e["relation_text"] = body.relations[str(e["line"])]
    plan = await build_plan(ctx, entries)
    skip, use = set(body.skip), set(body.use)
    role_ids = {
        r["id"]
        for r in await fetch_all(
            "SELECT id FROM roles WHERE org_id = $1",
            ctx.org_id,
            source_key=ctx.source_key,
        )
    }
    added, updated, skipped = [], [], list(plan["skipped"])
    async with tx(ctx) as conn:
        for p in plan["people"]:
            picked = [
                c
                for c in p["changes"]
                if not c.get("needs_relation")
                and c["id"] not in skip
                and (c["use"] or c["id"] in use)
            ]
            if p["status"] == "skip":
                skipped += [
                    {"line": p["lines"][0], "name": p["name"], "reason": r}
                    for r in p["problems"]
                ]
                continue
            new = next((c for c in picked if c["kind"] == "new"), None)
            if not p["match"] and not new:
                continue
            if not picked:
                continue
            role_id = body.roles.get(p["key"]) or (
                UUID(p["role_id"]) if p["role_id"] else None
            )
            if new and (not role_id or role_id not in role_ids):
                skipped.append(
                    {
                        "line": p["lines"][0],
                        "name": p["name"],
                        "reason": "Choose a role for this person.",
                    }
                )
                continue
            try:
                async with conn.transaction():  # one person never stops the others
                    if new:
                        uid = await conn.fetchval(
                            "INSERT INTO users (org_id, role_id, name, email, phone) VALUES ($1, $2, $3, $4, $5) RETURNING id",
                            ctx.org_id,
                            role_id,
                            p["name"],
                            p["email"],
                            p["phone"],
                        )
                    else:
                        uid = UUID(p["match"]["id"])
                        sets, vals = [], []
                        for c in picked:
                            if c["kind"] != "person":
                                continue
                            field = c["id"].rsplit(":", 1)[1]
                            if field == "role":
                                sets.append(f"role_id = ${len(vals) + 2}")
                                vals.append(UUID(c["role_id"]))
                            else:
                                sets.append(f"{field} = ${len(vals) + 2}")
                                vals.append(c["new"])
                        if sets:
                            await conn.execute(
                                f"UPDATE users SET {', '.join(sets)} WHERE id = $1",
                                uid,
                                *vals,
                            )
                    for c in picked:
                        if c["kind"] != "flat":
                            continue
                        e = next(x for x in entries if x["line"] == c["line"])
                        wing, flat = flat_parts(e.get("wing") or "", e["flat"])
                        if c["is_primary"]:
                            await conn.execute(
                                "UPDATE residents SET is_primary = false WHERE org_id = $1 "
                                "AND COALESCE(wing, '') = $2 AND flat_no = $3 AND is_primary "
                                "AND user_id IS DISTINCT FROM $4",
                                ctx.org_id,
                                wing or "",
                                flat,
                                uid,
                            )
                        done = await conn.fetchval(
                            "UPDATE residents SET relation = $5, is_primary = $6, lives_here = $7 "
                            "WHERE org_id = $1 AND user_id = $2 AND COALESCE(wing, '') = $3 AND flat_no = $4 "
                            "RETURNING id",
                            ctx.org_id,
                            uid,
                            wing or "",
                            flat,
                            c["relation"],
                            c["is_primary"],
                            c["lives_here"],
                        )
                        if not done:
                            await conn.execute(
                                "INSERT INTO residents (org_id, user_id, wing, flat_no, relation, is_primary, "
                                "lives_here, status, residential_status) "
                                "VALUES ($1, $2, $3, $4, $5, $6, $7, 'active', NULL)",
                                ctx.org_id,
                                uid,
                                wing,
                                flat,
                                c["relation"],
                                c["is_primary"],
                                c["lives_here"],
                            )
                    said = "; ".join(
                        c["label"]
                        + (
                            f": {c['old']} → {c['new']}"
                            if c["old"]
                            else f": {c['new']}"
                        )
                        for c in picked
                        if c["kind"] != "new"
                    )
                    await log_event(
                        ctx,
                        "people",
                        "create" if new else "update",
                        (
                            f"Imported {p['name']}"
                            if new
                            else f"{p['match']['name']}: from a file"
                        )
                        + (f" ({said})" if said else ""),
                        target_type="user",
                        target_id=uid,
                        after={"changes": [c["id"] for c in picked]},
                        conn=conn,
                    )
            except Exception as e:
                logger.warning(
                    f"people import: line {p['lines'][0]} failed ({type(e).__name__}): {e}"
                )
                skipped.append(
                    {
                        "line": p["lines"][0],
                        "name": p["name"],
                        "reason": "The database refused this person. Nothing of theirs was saved.",
                    }
                )
                continue
            (added if new else updated).append(
                {"line": p["lines"][0], "name": p["name"], "changes": len(picked)}
            )
        await log_event(
            ctx,
            "people",
            "import",
            f"Imported a file: {len(added)} added, {len(updated)} updated, {len(skipped)} skipped",
            target_type="orgs",
            target_id=ctx.org_id,
            conn=conn,
        )
    return {"added": added, "updated": updated, "skipped": skipped}
