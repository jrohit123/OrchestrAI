"""Writes the SQL that keeps the standard texts in a client's database.

A standard text is a row of `system_messages` (a message) or `prompts` (an AI text) with scope
'global' (the same for every client) or 'pack' (one industry's). It is the wording the code has always
used, so storing it changes nothing for anyone. An organisation's own version (scope 'tenant') still
wins over it, and the code keeps its own copy as the last fallback (see app/services/config_store.py).

    python -m tools.seed_texts messages                       every message, version 1
    python -m tools.seed_texts messages --keys a.b,c.d --version 2
    python -m tools.seed_texts prompt agent.reply_style --scope global --file app/prompts/response_formatting.txt
    python -m tools.seed_texts prompt agent.industry --scope pack --ref housing_society --file app/prompts/housing_society.txt

It only prints SQL. Put the output in a NEW numbered file under migrations/ (a file that was applied
must never change), then change the standard wording of something later by writing a new file that
inserts the next version. tests/test_standard_texts.py checks that the newest stored text of every
row is the same as the text in the code, so the two cannot drift apart unnoticed.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

LOCALE = "en-IN"  # the same as the table's default and app/admin_panel/message_texts.py
CREATED_BY = "seed"
_NAME = re.compile(r"\{([a-z_][a-z0-9_]*)\}")


def dollar(text: str) -> str:
    """The text as one SQL value that needs no escaping: between $tag$ ... $tag$, with a tag the
    text does not contain."""
    tag, n = "txt", 0
    while f"${tag}$" in text:
        n += 1
        tag = f"txt{n}"
    return f"${tag}${text}${tag}$"


def _names(text: str) -> list[str]:
    """The {names} a text fills in, sorted (what the `variables` column holds)."""
    return sorted(set(_NAME.findall(text)))


def _json(items: list[str]) -> str:
    return "'" + json.dumps(items) + "'::jsonb"


def _quote(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def messages_sql(version: int = 1, keys: list[str] | None = None) -> str:
    """One INSERT with the standard wording of the given messages (all of them by default)."""
    from app.services.messages import MESSAGES

    chosen = [MESSAGES[k] for k in keys] if keys else list(MESSAGES.values())
    rows = [
        f"    ({_quote(m.key)}, {_quote(LOCALE)}, 'global', '', {version}, {dollar(m.text)}, "
        f"{_json(sorted(m.values))}, true, 'Standard wording', {_quote(CREATED_BY)})"
        for m in chosen
    ]
    return (
        "INSERT INTO public.system_messages\n"
        "    (key, locale, scope, scope_ref, version, body, variables, is_active, note, created_by)\n"
        "VALUES\n" + ",\n".join(rows) + "\n"
        "ON CONFLICT (key, locale, scope, scope_ref, version) DO NOTHING;\n"
    )


def prompt_sql(
    key: str,
    scope: str,
    scope_ref: str,
    text: str,
    *,
    version: int = 1,
    note: str = "Standard text",
) -> str:
    """One INSERT with the standard text of one AI instruction."""
    if scope not in ("global", "pack"):
        raise ValueError("a standard text is 'global' or 'pack'")
    if (scope == "pack") != bool(scope_ref):
        raise ValueError(
            "a 'pack' text needs the industry as its reference, a global one none"
        )
    return (
        "INSERT INTO public.prompts\n"
        "    (key, scope, scope_ref, version, body, variables, is_active, note, created_by)\n"
        "VALUES\n"
        f"    ({_quote(key)}, {_quote(scope)}, {_quote(scope_ref)}, {version}, {dollar(text)}, "
        f"{_json(_names(text))}, true, {_quote(note)}, {_quote(CREATED_BY)})\n"
        "ON CONFLICT (key, scope, scope_ref, version) DO NOTHING;\n"
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="what", required=True)
    m = sub.add_parser("messages", help="the standard wording of messages")
    m.add_argument("--version", type=int, default=1)
    m.add_argument("--keys", help="only these message keys, separated by commas")
    t = sub.add_parser("prompt", help="the standard text of one AI instruction")
    t.add_argument("key")
    t.add_argument("--scope", choices=["global", "pack"], required=True)
    t.add_argument("--ref", default="", help="the industry, for a 'pack' text")
    t.add_argument("--file", required=True, type=Path)
    t.add_argument("--version", type=int, default=1)
    t.add_argument("--note", default="Standard text")
    args = p.parse_args(argv)
    if args.what == "messages":
        keys = (
            [k.strip() for k in args.keys.split(",") if k.strip()]
            if args.keys
            else None
        )
        sys.stdout.write(messages_sql(args.version, keys))
    else:
        # the same reading the app does: the text of the file without the blank edges
        text = args.file.read_text(encoding="utf-8").strip()
        sys.stdout.write(
            prompt_sql(
                args.key,
                args.scope,
                args.ref,
                text,
                version=args.version,
                note=args.note,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
