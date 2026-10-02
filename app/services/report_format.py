"""
report_format.py — turns the rows of a stored report into the message people read.

Rows come from a stored SQL query. Rewording them with a language model can drop a row or
change a number, so a report whose response_format is 'list' is formatted here, by code:
every row appears exactly once and every value is shown as stored.

Layout: a title line, an optional one-line count by status/priority, then one block per row:
    *first column* — second column (when it is text)
    label: value · label: value · ...
Empty values are left out. Dates show as "27 Sep, 1:20 pm" in Indian time. Long lists are cut
into paragraphs of ROWS_PER_PARAGRAPH rows, which messaging.send_text splits on if the message
is longer than one chat message allows.
"""

import json
import re
from collections import Counter
from datetime import date, datetime
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
ROWS_PER_PARAGRAPH = 5
_DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATE_TIME = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}")


def _label(column: str) -> str:
    c = column.lower()
    for suffix in ("_name", "_at", "_date"):
        if c.endswith(suffix) and len(c) > len(suffix):
            c = c[: -len(suffix)]
            break
    return c.replace("_", " ")


def _indian(n: int) -> str:
    s = str(abs(n))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts + [tail])
    return ("-" if n < 0 else "") + s


def _when(value: str) -> str | None:
    try:
        if _DATE_ONLY.match(value):
            d = date.fromisoformat(value)
            return f"{d.day} {d.strftime('%b')}" + (
                "" if d.year == datetime.now(IST).year else f" {d.year}"
            )
        if _DATE_TIME.match(value):
            dt = datetime.fromisoformat(value)
            dt = dt.astimezone(IST) if dt.tzinfo else dt
            text = f"{dt.day} {dt.strftime('%b')}"
            if dt.year != datetime.now(IST).year:
                text += f" {dt.year}"
            if (dt.hour, dt.minute) != (0, 0):
                text += ", " + dt.strftime("%I:%M %p").lstrip("0").lower()
            return text
    except ValueError:
        return None
    return None


def _value(v) -> str | None:
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, int):
        return _indian(v) if abs(v) >= 1000 else str(v)
    if isinstance(v, float):
        return f"{v:g}"
    if isinstance(v, (list, dict)):
        return json.dumps(v, ensure_ascii=False)
    text = str(v).strip()
    return _when(text) or text


def format_list(title: str, raw: str) -> str:
    """raw is what query_engine.execute_query returned in its JSON form."""
    raw = (raw or "").strip()
    if raw.startswith(("No results", "EMPTY")):
        return f"*{title}*\nNothing found."
    if raw.startswith("ERROR"):
        if "not permitted" in raw:
            return "You do not have access to that report."
        return "Sorry, I could not get that report right now. Please try again."
    try:
        rows = json.loads(raw)
    except ValueError:
        return raw
    if not isinstance(rows, list) or not rows:
        return f"*{title}*\nNothing found."

    head = f"*{title}*, {len(rows)} found"
    counts = []
    for column in ("status", "priority"):
        if all(isinstance(r, dict) and column in r for r in rows):
            tally = Counter(str(r[column]) for r in rows if r[column] not in (None, ""))
            if 1 < len(tally) <= 6:
                counts.append(" · ".join(f"{k} {n}" for k, n in tally.most_common()))
    if len(rows) >= 5 and counts:
        head += "\n" + "\n".join(counts)

    blocks = []
    for row in rows:
        items = [(k, _value(v)) for k, v in row.items()]
        first = items[0][1] if items else None
        line = f"*{first}*" if first else "*—*"
        rest = items[1:]
        if rest and rest[0][1] and not _when(rest[0][1]) and not rest[0][1].isdigit():
            line += f" — {rest[0][1]}"
            rest = rest[1:]
        details = [f"{_label(k)}: {v}" for k, v in rest if v]
        blocks.append(line + ("\n" + " · ".join(details) if details else ""))

    paragraphs = [
        "\n".join(blocks[i : i + ROWS_PER_PARAGRAPH])
        for i in range(0, len(blocks), ROWS_PER_PARAGRAPH)
    ]
    return head + "\n\n" + "\n\n".join(paragraphs)
