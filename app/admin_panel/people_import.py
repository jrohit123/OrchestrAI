"""Adding many people at once from a CSV file, with their role and responsibilities (seats).

Two steps, so nothing is saved by surprise:
  * preview: the file is read and every row is checked (name, email, number, role, seats, already here, repeated in the file).
             Nothing is written. The screen shows the rows, lets the person fix a role or seat in a list, and skip rows.
  * commit:  the rows that were kept are added the same way "Add person" adds one, each in its own step, so one bad row
             never stops the others. A seat that already has a holder is left alone unless the person said to replace.

Both a super admin and an admin of the organisation may use it. What a person may be given is the same as on the People
screen: any role of this organisation. Nothing here names a role or a seat; both are read from the database."""

import csv
import io
import re
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.admin_panel.common import CtxDep, PanelRoute, log_event, people_channel, tx
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
        "phonenumber",
        "contact",
        "contactnumber",
        "whatsapp",
        "whatsappnumber",
        "number",
    },
    "role": {"role", "type", "access", "accesslevel", "usertype"},
    "seat": {
        "seat",
        "seats",
        "responsibility",
        "responsibilities",
        "position",
        "positions",
        "committee",
        "committeeposition",
    },
}
SEAT_SPLIT = re.compile(r"\s*[;|/]\s*")


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
            "The file needs a first row with column names (for example Name, Email, Role) and at least one person."
        )
    header = [_key(c) for c in table[0]]
    columns: dict[str, int] = {}
    for field, names in ALIASES.items():
        for i, h in enumerate(header):
            if h in names and field not in columns and i not in columns.values():
                columns[field] = i
    if "name" not in columns or "email" not in columns:
        raise ValueError(
            "The first row must have a Name column and an Email column. Download the sample file to see the layout."
        )
    if len(table) - 1 > MAX_ROWS:
        raise ValueError(
            f"Up to {MAX_ROWS} people at a time. This file has {len(table) - 1}."
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
    if not re.fullmatch(r"\+\d{8,15}", text):
        raise ValueError(
            "The number needs its country code, like +91 98765 43210."
            if not code
            else "That does not look like a phone number."
        )
    return text


async def _lookup(ctx):
    roles = await fetch_all(
        "SELECT id, name FROM roles WHERE org_id = $1",
        ctx.org_id,
        source_key=ctx.source_key,
    )
    seats, holders = [], {}
    if False:  # seats are not used any more: a role does that job (the rows stay in the database)
        seats = await fetch_all(
            "SELECT id, name FROM committee_positions WHERE org_id = $1",
            ctx.org_id,
            source_key=ctx.source_key,
        )
        for h in await fetch_all(
            "SELECT m.position_id, u.name FROM committee_members m JOIN users u ON u.id = m.user_id "
            "WHERE m.org_id = $1 AND m.status = 'active'",
            ctx.org_id,
            source_key=ctx.source_key,
        ):
            holders[str(h["position_id"])] = h["name"]
    existing = await fetch_all(
        "SELECT lower(email) AS email, phone, name FROM users WHERE org_id = $1",
        ctx.org_id,
        source_key=ctx.source_key,
    )
    return roles, seats, holders, existing


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
    roles, _seats, holders, existing = await _lookup(ctx)
    role_by = {_key(r["name"]): r for r in roles}
    have_email = {e["email"]: e["name"] for e in existing if e["email"]}
    have_phone = {e["phone"]: e["name"] for e in existing if e["phone"]}
    seen_email: set[str] = set()
    seen_phone: set[str] = set()
    out = []

    def cell(row, field):
        i = columns.get(field)
        return row[i].strip() if i is not None and i < len(row) else ""

    for n, row in enumerate(data, start=2):  # n is the line number in the file
        name = " ".join(cell(row, "name").split())
        email = cell(row, "email").lower()
        phone_raw = cell(row, "phone")
        role_raw = cell(row, "role")
        problems, notes = [], []
        if len(name) < 2:
            problems.append("The name is missing.")
        if not _EMAIL.match(email):
            problems.append("The email is missing or does not look right.")
        phone = None
        if by_number and phone_raw:
            try:
                phone = clean_number(phone_raw, body.country)
            except ValueError as e:
                notes.append(str(e) + " It will be added without a number.")
        exists = have_email.get(email) or (have_phone.get(phone) if phone else None)
        if exists:
            problems.append(f"{exists} is already here with that email or number.")
        if email in seen_email or (phone and phone in seen_phone):
            problems.append("This email or number is repeated higher up in the file.")
        seen_email.add(email)
        if phone:
            seen_phone.add(phone)
        role = role_by.get(_key(role_raw)) if role_raw else None
        if role_raw and not role:
            notes.append(f"No role called “{role_raw}”. Choose one.")
        picked: list[
            str
        ] = []  # seats are not used any more (a role does that job): a Seat column is ignored
        out.append(
            {
                "line": n,
                "name": name,
                "email": email,
                "phone": phone,
                "role_id": str(role["id"]) if role else None,
                "role_text": role_raw,
                "seat_ids": picked,
                "problems": problems,
                "notes": notes,
                "ok": not problems,
            }
        )
    return {
        "columns": sorted(columns),
        "by_number": by_number,
        "rows": out,
        "holders": holders,
        "ok": sum(1 for r in out if r["ok"]),
    }


class ImportRow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    line: int = 0
    name: str = Field(..., max_length=80)
    email: str = Field(..., max_length=160)
    phone: str | None = Field(None, max_length=40)
    role_id: UUID
    seat_ids: list[UUID] = []


class CommitBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rows: list[ImportRow] = Field(..., max_length=MAX_ROWS)
    replace_seats: bool = False


@router.post("/people/import/commit")
async def commit(ctx: CtxDep, body: CommitBody):
    """Add the kept rows. Every row is checked again here (the screen is not trusted), and each is saved on its own."""
    if not body.rows:
        raise HTTPException(400, "There is nobody to add.")
    by_number = await people_channel(ctx.source_key) != "telegram"
    roles, _seats, _holders, existing = await _lookup(ctx)
    role_name = {r["id"]: r["name"] for r in roles}
    taken_email = {e["email"] for e in existing if e["email"]}
    taken_phone = {e["phone"] for e in existing if e["phone"]}
    added, skipped = [], []
    async with tx(ctx) as conn:
        for r in body.rows:
            name = " ".join(r.name.split())
            email = r.email.strip().lower()
            phone = r.phone.strip() if by_number and r.phone else None
            why = None
            if len(name) < 2:
                why = "The name is missing."
            elif not _EMAIL.match(email):
                why = "The email does not look right."
            elif r.role_id not in role_name:
                why = "That role does not exist."
            elif email in taken_email or (phone and phone in taken_phone):
                why = "Already here with that email or number."
            elif phone and not re.fullmatch(r"\+\d{8,15}", phone):
                why = "The number is not valid."
            if why:
                skipped.append({"line": r.line, "name": name, "reason": why})
                continue
            try:
                async with conn.transaction():  # one row never stops the others
                    uid = await conn.fetchval(
                        "INSERT INTO users (org_id, role_id, name, email, phone) VALUES ($1, $2, $3, $4, $5) RETURNING id",
                        ctx.org_id,
                        r.role_id,
                        name,
                        email,
                        phone,
                    )
                    seat_notes = []
                    final_role = await conn.fetchval(
                        "SELECT r.name FROM users u JOIN roles r ON r.id = u.role_id WHERE u.id = $1",
                        uid,
                    )
                    await log_event(
                        ctx,
                        "people",
                        "create",
                        f"Imported {name} as {final_role or role_name[r.role_id]}"
                        + (f" with {len(r.seat_ids)} seat(s)" if r.seat_ids else ""),
                        target_type="user",
                        target_id=uid,
                        after={
                            "name": name,
                            "role_id": r.role_id,
                            "seats": [str(s) for s in r.seat_ids],
                            "has_number": bool(phone),
                        },
                        conn=conn,
                    )
            except Exception as e:
                logger.warning(
                    f"people import: row {r.line} failed ({type(e).__name__}): {e}"
                )
                skipped.append(
                    {
                        "line": r.line,
                        "name": name,
                        "reason": "The database refused this row.",
                    }
                )
                continue
            taken_email.add(email)
            if phone:
                taken_phone.add(phone)
            added.append({"line": r.line, "name": name, "notes": seat_notes})
        await log_event(
            ctx,
            "people",
            "import",
            f"Imported {len(added)} people from a file ({len(skipped)} skipped)",
            target_type="orgs",
            target_id=ctx.org_id,
            conn=conn,
        )
    return {"added": added, "skipped": skipped}
