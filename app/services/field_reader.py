"""
field_reader.py — reads the answers to a workflow's questions with exact rules and SQL, before any
language model is involved.

A field in a workflow's entity_schema can say how its answer is read:

    "case_number": {"type": "string", "required": true, "description": "...",
                    "read_by": {"lookup": {"table": "cases", "match_column": "case_number",
                                            "normalize": "identifier", "show": ["case_number", "title"]}}}
    "comment_text": {"type": "string", "required": true, "description": "...", "read_by": "typed"}
    "priority":     {"type": "string", "required": true, "enum": ["urgent", "high", "medium", "low"]}

  lookup  the reply is looked up in a table (a case number, a person's name)
  typed   the whole reply is the value (a note, a title)
  choice  the field has an "enum": the reply must be one of the allowed answers
  ai      "read_by": "ai" leaves the field to the assistant even when it has an enum

A field with none of these is read by the assistant, exactly as before.

Code reads an answer only when it is sure: one exact match. Not sure means None, and the assistant
handles that turn as it always did. When a reply matches several records, code asks which one, with
numbers. A value that code reads is always the stored one (the real case number, the real full
name), so the confirmation shows real records.
"""

import json
import re

from app.logging_config import get_context_logger

logger = get_context_logger(__name__)

# words that may sit around the values in a typed command ("/assign CS-26-10-1 to Rajeswari")
_FILLER = {
    "to",
    "for",
    "the",
    "a",
    "an",
    "of",
    "on",
    "it",
    "please",
    "pls",
    "with",
    "as",
    "and",
    "case",
    "number",
    "no",
    "give",
    "assign",
    "pass",
}
_MAX_OPTIONS = 5
_TYPED_LIMIT = 500
_MAX_ARG_WORDS = 14
_NOUNS = {"users": "person", "cases": "case"}
# something typed like a reference number: CS-26-10-1, cs260900001 (letters, then digits)
_REFERENCE = re.compile(r"^[A-Za-z]{1,4}-?\d[\d-]*$")


def reader_of(spec) -> dict | None:
    """How a field is read by code, or None when it is left to the assistant."""
    if not isinstance(spec, dict) or spec.get("computed"):
        return None
    rb = spec.get("read_by")
    if rb == "ai":
        return None
    if rb in ("typed", "as_typed"):
        return {"kind": "typed"}
    if isinstance(rb, dict) and isinstance(rb.get("lookup"), dict):
        cfg = rb["lookup"]
        if cfg.get("table") and cfg.get("match_column"):
            return {"kind": "lookup", "cfg": cfg}
    options = spec.get("enum")
    if (
        isinstance(options, list)
        and options
        and all(isinstance(o, str) for o in options)
    ):
        return {"kind": "choice", "options": options}
    return None


def first_missing(entity_schema: dict, fields: dict):
    """The next required question, in schema order (the same rule the first question uses)."""
    for name, spec in (entity_schema or {}).items():
        if not isinstance(spec, dict) or spec.get("computed"):
            continue
        if spec.get("required") and not fields.get(name):
            return name, spec
    return None


def question_for(name: str, spec: dict) -> str:
    """What the person is asked. "question" is written for them; "description" is the guidance
    the assistant reads, and is used when no question was written."""
    q = (
        spec.get("question")
        or spec.get("description")
        or f"What is the {name.replace('_', ' ')}?"
    )
    if spec.get("enum"):
        q += f" ({' / '.join(spec['enum'])})"
    return q


def buttons_for(spec: dict) -> list[dict] | None:
    """Tap-to-answer buttons for a field with fixed answers (None when there are none)."""
    reader = reader_of(spec)
    if not reader or reader["kind"] != "choice" or len(reader["options"]) > 8:
        return None
    return [{"id": o, "title": o[:1].upper() + o[1:]} for o in reader["options"]]


def _label(cfg: dict, row: dict) -> str:
    cols = cfg.get("show") or [cfg["match_column"]]
    parts = [str(row.get(c)) for c in cols if row.get(c) not in (None, "")]
    return " — ".join(parts) or str(row.get(cfg["match_column"]))


def _noun(cfg: dict) -> str:
    return cfg.get("noun") or _NOUNS.get(cfg["table"]) or str(cfg["table"]).rstrip("s")


def _is_filler(word: str) -> bool:
    return word.casefold().strip(".,:;!?") in _FILLER


def _strip_filler(text: str) -> str:
    """Drop little words at the two ends: 'to Rajeswari' -> 'Rajeswari'."""
    words = text.split()
    while words and _is_filler(words[0]):
        words.pop(0)
    while words and _is_filler(words[-1]):
        words.pop()
    return " ".join(words)


def _match_option(text: str, options: list[str], *, loose: bool = True) -> str | None:
    t = text.strip().casefold().strip(".,!")
    exact = [o for o in options if o.casefold() == t]
    if len(exact) == 1:
        return exact[0]
    if loose and len(t) >= 3:
        prefix = [o for o in options if o.casefold().startswith(t)]
        if len(prefix) == 1:
            return prefix[0]
    return None


async def lookup_one(cfg: dict, text: str, user: dict):
    """('one', row) | ('many', rows) | ('none', None). Uses the same lookup the workflow steps use."""
    from app.services.step_interpreter import (
        StepError,
        UserFacingStepError,
        _op_resolve_entity,
    )

    ctx = {
        "org_id": user["org_id"],
        "source_key": user["source_key"],
        "user": user,
        "fields": {"__answer": text},
        "workflow": {},
    }
    params = {
        "table": cfg["table"],
        "match_column": cfg["match_column"],
        "name_from": "$fields.__answer",
        "into": "found",
    }
    if cfg.get("normalize"):
        params["normalize"] = cfg["normalize"]
    if isinstance(cfg.get("where"), dict):
        params["where"] = cfg["where"]
    try:
        out = await _op_resolve_entity(params, ctx)
        return "one", out["found"]
    except UserFacingStepError:
        return "none", None
    except StepError as e:
        msg = str(e)
        if msg.startswith("AMBIGUOUS:"):
            try:
                rows = json.loads(msg.split(":", 3)[3])
                return "many", rows
            except (ValueError, IndexError):
                return "none", None
        return "none", None
    except Exception as e:  # a lookup problem must never break the conversation
        logger.warning(f"field_reader lookup failed: {e}")
        return "none", None


def _looks_like_identifier(text: str) -> bool:
    return (
        " " not in text.strip() and any(c.isdigit() for c in text) and len(text) <= 30
    )


def _accepted(field: str, value: str, label: str | None) -> dict:
    return {
        "fields": {field: value},
        "display": {field: {"value": value, "label": label}}
        if label and label != value
        else {},
        "reply": None,
        "candidates": None,
        "buttons": None,
    }


def _ask_which(field: str, text: str, cfg: dict, rows: list[dict]) -> dict:
    col = cfg["match_column"]
    options = [
        {"value": str(r[col]), "label": _label(cfg, r)} for r in rows[:_MAX_OPTIONS]
    ]
    lines = "\n".join(f"{i + 1}. {o['label']}" for i, o in enumerate(options))
    return {
        "fields": {},
        "display": {},
        "reply": f"I found more than one match for “{text}”. Which one?\n{lines}\n\nReply with the number.",
        "candidates": options,
        "buttons": [
            {"id": str(i + 1), "title": o["label"][:60]} for i, o in enumerate(options)
        ],
        "asking": field,
    }


def _pick_candidate(text: str, candidates: list[dict]):
    t = text.strip()
    if t.isdigit() and 1 <= int(t) <= len(candidates):
        return candidates[int(t) - 1]
    exact = [
        c
        for c in candidates
        if c["label"].casefold() == t.casefold()
        or c["value"].casefold() == t.casefold()
    ]
    return exact[0] if len(exact) == 1 else None


async def read_answer(text: str, user: dict, pending: dict, entity_schema: dict):
    """Read the answer to the question the code just asked (pending['asking']).

    Returns None (leave it to the assistant) or a dict:
      fields / display : what was understood (may be empty when a choice must be made)
      reply            : a question to send now (which one? / not found), or None
      candidates       : the numbered options offered, or None
      buttons          : tap-to-answer buttons for the reply, or None
    """
    asking = pending.get("asking")
    spec = (entity_schema or {}).get(asking)
    text = " ".join((text or "").split())
    if not text or not isinstance(spec, dict):
        return None

    candidates = pending.get("candidates")
    if candidates:
        picked = _pick_candidate(text, candidates)
        if picked:
            return _accepted(asking, picked["value"], picked["label"])

    reader = reader_of(spec)
    if not reader:
        return None

    if reader["kind"] == "typed":
        if text.startswith("/") or len(text) > _TYPED_LIMIT:
            return None
        return _accepted(asking, text, None)

    if reader["kind"] == "choice":
        value = _match_option(text, reader["options"])
        return _accepted(asking, value, None) if value else None

    cfg = reader["cfg"]
    query = _strip_filler(text)
    if not query:
        return None
    kind, found = await lookup_one(cfg, query, user)
    col = cfg["match_column"]
    if kind == "one":
        return _accepted(asking, str(found[col]), _label(cfg, found))
    if kind == "many":
        exact = [
            r
            for r in found[:_MAX_OPTIONS]
            if str(r.get(col, "")).casefold() == query.casefold()
        ]
        if len(exact) == 1:
            return _accepted(asking, str(exact[0][col]), _label(cfg, exact[0]))
        return _ask_which(asking, query, cfg, found)

    noun = _noun(cfg)
    if cfg.get("normalize") == "identifier":
        if _looks_like_identifier(query):
            return {
                "fields": {},
                "display": {},
                "reply": f"I could not find a {noun} “{query}”. Please check it and send it again.",
                "candidates": None,
                "buttons": None,
            }
    elif len(query.split()) <= 3 and not any(c.isdigit() for c in query):
        return {
            "fields": {},
            "display": {},
            "reply": f"I could not find a {noun} called “{query}”. Please check the name and send it again.",
            "candidates": None,
            "buttons": None,
        }
    return None


def _spans(left: list[str], identifier: bool) -> list[list[str]]:
    """The groups of typed words worth looking up, longest first."""
    if identifier:
        return [[t] for t in left if any(c.isdigit() for c in t)]
    spans = []
    for size in (3, 2, 1):
        for i in range(len(left) - size + 1):
            span = left[i : i + size]
            if not _is_filler(span[0]) and not _is_filler(span[-1]):
                spans.append(span)
    return spans


async def prefill_from_args(entity_schema: dict, args: str, user: dict):
    """Fill fields from the words typed after a command ("/assign CS-26-10-1 Rajeswari").

    Returns None when anything is left that code cannot explain (the assistant then reads the
    whole message), or a dict like read_answer's with the fields that were understood, plus
    `asking` when a choice between several matches has to be made."""
    tokens = (args or "").split()
    if not tokens or len(tokens) > _MAX_ARG_WORDS:
        return None
    left = list(tokens)
    fields: dict = {}
    display: dict = {}
    pick = None  # (field, text, cfg, rows) when a name matches several people

    schema = entity_schema or {}
    readers = {n: reader_of(s) for n, s in schema.items()}
    typed = [n for n, r in readers.items() if r and r["kind"] == "typed"]

    # 1. lookups: words that match exactly one record
    for name, reader in readers.items():
        if not reader or reader["kind"] != "lookup" or not left:
            continue
        cfg = reader["cfg"]
        col = cfg["match_column"]
        found = None
        many = None
        for span in _spans(left, cfg.get("normalize") == "identifier"):
            text = " ".join(span)
            kind, row = await lookup_one(cfg, text, user)
            if kind == "one":
                found = (row, span)
                break
            if kind == "many" and many is None and (len(text) >= 3 or text.isdigit()):
                many = (text, row, span)
        if found:
            row, span = found
            fields[name] = str(row[col])
            label = _label(cfg, row)
            if label != fields[name]:
                display[name] = {"value": fields[name], "label": label}
            for tok in span:
                left.remove(tok)
        elif many:
            pick = (name, many[0], cfg, many[1])
            for tok in many[2]:
                left.remove(tok)
            break

    # a reference number that matched nothing: say so, rather than guess what it was
    missing_ref = None
    if pick is None:
        for name, reader in readers.items():
            if (
                reader
                and reader["kind"] == "lookup"
                and reader["cfg"].get("normalize") == "identifier"
                and not fields.get(name)
            ):
                tok = next((t for t in left if _REFERENCE.match(t)), None)
                if tok:
                    missing_ref = (name, tok, reader["cfg"])
                    left.remove(tok)
                    break

    # 2. fixed answers, only when no free text could be hiding the same word
    typed_open = [n for n in typed if not fields.get(n)]
    if not typed_open:
        for name, reader in readers.items():
            if not reader or reader["kind"] != "choice" or fields.get(name):
                continue
            for tok in list(left):
                value = _match_option(tok, reader["options"], loose=False)
                if value:
                    fields[name] = value
                    left.remove(tok)
                    break

    # 3. what is left over is the one free-text answer, if there is exactly one place for it
    rest = _strip_filler(" ".join(left))
    if rest:
        if len(typed_open) == 1 and pick is None:
            fields[typed_open[0]] = rest[:_TYPED_LIMIT]
        else:
            return None

    if not fields and pick is None and missing_ref is None:
        return None
    out = {
        "fields": fields,
        "display": display,
        "reply": None,
        "candidates": None,
        "buttons": None,
    }
    if pick:
        name, text, cfg, rows = pick
        out.update(_ask_which(name, text, cfg, rows))
        out["fields"] = fields
        out["display"] = display
    elif missing_ref:
        name, tok, cfg = missing_ref
        out["reply"] = (
            f"I could not find a {_noun(cfg)} “{tok}”. Please check it and send it again."
        )
        out["asking"] = name
    return out
