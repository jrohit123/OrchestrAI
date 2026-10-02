"""
Checks for app/services/field_reader.py: the exact rules that read an answer without a language model.
No database needed: the table lookup is replaced by a small fake list of cases and people.

    python tests/check_field_reader.py
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for k in ("ROUTING_DATABASE_URL", "TELEGRAM_BOT_TOKEN", "OPENAI_API_KEY"):
    os.environ.setdefault(k, "x")

from app.services import field_reader as fr

CASES = [
    {"case_number": "CS-26-10-00001", "title": "Lift stuck"},
    {"case_number": "CS-26-10-00002", "title": "Garden light"},
]
PEOPLE = [
    {"name": "Kartik Batchu"},
    {"name": "Rajeswari Batchu"},
    {"name": "Venkatesh Batchu"},
    {"name": "RJ"},
]


async def fake_lookup(cfg, text, user):
    if cfg["table"] == "cases":
        # "CS-26-10-1" finds CS-26-10-00001: the last group is compared by its number
        tail = "".join(ch for ch in text.split("-")[-1] if ch.isdigit())
        hit = [
            c
            for c in CASES
            if tail
            and "-" in text
            and int(c["case_number"].split("-")[-1]) == int(tail)
        ]
    else:
        t = text.strip().casefold()
        exact = [p for p in PEOPLE if p["name"].casefold() == t]
        hit = (
            exact
            if len(exact) == 1
            else [p for p in PEOPLE if t in p["name"].casefold()]
        )
    if not hit:
        return "none", None
    return ("one", hit[0]) if len(hit) == 1 else ("many", hit)


fr.lookup_one = fake_lookup

CASE_LOOKUP = {
    "lookup": {
        "table": "cases",
        "match_column": "case_number",
        "normalize": "identifier",
        "show": ["case_number", "title"],
    }
}
PERSON_LOOKUP = {"lookup": {"table": "users", "match_column": "name", "show": ["name"]}}
ASSIGN = {
    "case_number": {"required": True, "read_by": CASE_LOOKUP},
    "assignee_name": {"required": True, "read_by": PERSON_LOOKUP},
    "comment_text": {"required": False, "read_by": "typed"},
}
UPDATE = {
    "case_number": {"required": True, "read_by": CASE_LOOKUP},
    "comment_text": {"required": True, "read_by": "typed"},
}
COMPLAINT = {
    "title": {"required": True, "read_by": "typed"},
    "location": {"required": True, "read_by": "typed"},
    "priority": {"required": True, "enum": ["urgent", "high", "medium", "low"]},
}
USER = {"org_id": "o", "source_key": "s"}

ok = bad = 0


def check(name, cond, detail=""):
    global ok, bad
    if cond:
        ok += 1
    else:
        bad += 1
        print("  FAIL", name, "|", str(detail)[:400])


async def main():
    # how a field is read
    check("lookup", fr.reader_of(ASSIGN["case_number"])["kind"] == "lookup")
    check("typed", fr.reader_of(ASSIGN["comment_text"])["kind"] == "typed")
    check("enum is a choice", fr.reader_of(COMPLAINT["priority"])["kind"] == "choice")
    check(
        "plain text is left to the assistant", fr.reader_of({"type": "string"}) is None
    )
    check(
        "read_by ai wins over an enum",
        fr.reader_of({"enum": ["a"], "read_by": "ai"}) is None,
    )
    check(
        "computed fields are never asked",
        fr.reader_of({"computed": True, "enum": ["a"]}) is None,
    )
    check(
        "first missing follows schema order",
        fr.first_missing(ASSIGN, {})[0] == "case_number"
        and fr.first_missing(ASSIGN, {"case_number": "x"})[0] == "assignee_name",
    )
    check(
        "optional fields are not asked",
        fr.first_missing(ASSIGN, {"case_number": "x", "assignee_name": "y"}) is None,
    )
    check(
        "the written question wins",
        fr.question_for(
            "p",
            {"question": "How urgent?", "description": "guidance", "enum": ["a", "b"]},
        )
        == "How urgent? (a / b)",
    )
    check(
        "the description is the fallback",
        fr.question_for("p", {"description": "Where is it?"}) == "Where is it?",
    )
    check(
        "buttons for fixed answers",
        [b["id"] for b in fr.buttons_for(COMPLAINT["priority"])]
        == ["urgent", "high", "medium", "low"],
    )
    check("no buttons for text", fr.buttons_for(ASSIGN["comment_text"]) is None)

    # answers to a question
    ask = lambda field, **more: {"asking": field, **more}
    r = await fr.read_answer("priority please high", USER, ask("priority"), COMPLAINT)
    check("a sentence is not a choice", r is None, r)
    r = await fr.read_answer("High", USER, ask("priority"), COMPLAINT)
    check(
        "a choice is matched without caring about case",
        r and r["fields"] == {"priority": "high"},
        r,
    )
    r = await fr.read_answer("urg", USER, ask("priority"), COMPLAINT)
    check(
        "a unique start of a choice is accepted",
        r and r["fields"] == {"priority": "urgent"},
        r,
    )
    r = await fr.read_answer("Lift stuck on 5th floor", USER, ask("title"), COMPLAINT)
    check(
        "typed text is taken as typed",
        r and r["fields"] == {"title": "Lift stuck on 5th floor"},
        r,
    )
    r = await fr.read_answer("/cancel", USER, ask("title"), COMPLAINT)
    check("a command is never taken as text", r is None, r)
    r = await fr.read_answer("cs-26-10-1", USER, ask("case_number"), ASSIGN)
    check(
        "a case is found and shown with its title",
        r
        and r["fields"] == {"case_number": "CS-26-10-00001"}
        and r["display"]["case_number"]["label"] == "CS-26-10-00001 — Lift stuck",
        r,
    )
    r = await fr.read_answer("to Rajeswari Batchu", USER, ask("assignee_name"), ASSIGN)
    check(
        "little words around a name are ignored",
        r and r["fields"] == {"assignee_name": "Rajeswari Batchu"},
        r,
    )
    r = await fr.read_answer("Batchu", USER, ask("assignee_name"), ASSIGN)
    check(
        "a name that fits three people asks which",
        r
        and r["reply"]
        and r["candidates"]
        and len(r["candidates"]) == 3
        and len(r["buttons"]) == 3,
        r,
    )
    r = await fr.read_answer(
        "2", USER, ask("assignee_name", candidates=r["candidates"]), ASSIGN
    )
    check(
        "the number picks the person",
        r and r["fields"] == {"assignee_name": "Rajeswari Batchu"},
        r,
    )
    r = await fr.read_answer("RJ", USER, ask("assignee_name"), ASSIGN)
    check(
        "an exact short name is found", r and r["fields"] == {"assignee_name": "RJ"}, r
    )
    r = await fr.read_answer("CS-99-99-99999", USER, ask("case_number"), ASSIGN)
    check(
        "a missing case number gets its own reply",
        r and "could not find a case" in r["reply"],
        r,
    )
    r = await fr.read_answer("Zebra", USER, ask("assignee_name"), ASSIGN)
    check(
        "a missing name gets its own reply",
        r and "could not find a person called" in r["reply"],
        r,
    )
    r = await fr.read_answer(
        "please give it to somebody who is free in the evenings",
        USER,
        ask("assignee_name"),
        ASSIGN,
    )
    check("a long sentence is left to the assistant", r is None, r)

    # words typed after a command
    r = await fr.prefill_from_args(ASSIGN, "CS-26-10-1 Rajeswari Batchu", USER)
    check(
        "assign: case and person",
        r
        and r["fields"]
        == {"case_number": "CS-26-10-00001", "assignee_name": "Rajeswari Batchu"}
        and not r["reply"],
        r,
    )
    r = await fr.prefill_from_args(ASSIGN, "CS-26-10-1 to RJ", USER)
    check(
        "assign: 'to' is ignored",
        r
        and r["fields"].get("assignee_name") == "RJ"
        and "comment_text" not in r["fields"],
        r,
    )
    r = await fr.prefill_from_args(
        ASSIGN, "CS-26-10-1 Rajeswari please check today", USER
    )
    check(
        "assign: the rest is the note",
        r
        and r["fields"].get("assignee_name") == "Rajeswari Batchu"
        and r["fields"].get("comment_text") == "check today",
        r,
    )
    r = await fr.prefill_from_args(
        UPDATE, "CS-26-10-2 vendor visited, part ordered", USER
    )
    check(
        "update: the rest is the note",
        r
        and r["fields"]
        == {
            "case_number": "CS-26-10-00002",
            "comment_text": "vendor visited, part ordered",
        },
        r,
    )
    r = await fr.prefill_from_args(ASSIGN, "CS-26-10-1 Batchu", USER)
    check(
        "assign: an ambiguous name asks which, keeping the case",
        r
        and r["fields"] == {"case_number": "CS-26-10-00001"}
        and r["asking"] == "assignee_name"
        and len(r["candidates"]) == 3,
        r,
    )
    r = await fr.prefill_from_args(ASSIGN, "CS-99-99-99999 Rajeswari", USER)
    check(
        "assign: a missing case number is reported, the person is kept",
        r
        and r["fields"] == {"assignee_name": "Rajeswari Batchu"}
        and "could not find a case" in r["reply"]
        and r["asking"] == "case_number",
        r,
    )
    r = await fr.prefill_from_args(COMPLAINT, "lift stuck in wing 2 urgent", USER)
    check("complaint: several free-text details go to the assistant", r is None, r)
    r = await fr.prefill_from_args(UPDATE, "", USER)
    check("nothing typed means nothing to read", r is None, r)
    r = await fr.prefill_from_args(ASSIGN, "Rajeswari", USER)
    check(
        "assign: a name alone is still read",
        r and r["fields"] == {"assignee_name": "Rajeswari Batchu"},
        r,
    )

    print(f"field_reader: {ok} of {ok + bad} checks passed")
    sys.exit(1 if bad else 0)


asyncio.run(main())
