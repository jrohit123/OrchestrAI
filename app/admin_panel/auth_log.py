"""The sign-in log: what each quick button shows, and the filtered read behind the Sign-in log screen.

Every line in panel_audit has an action. The buttons group the actions by topic; "Problems" is every
line that did not go well, whatever its topic. tests/test_panel_login.py reads the code for every action
it can write and fails when one is in no group, so a new kind of line cannot be added without
deciding where it shows.

The search is a plain "contains" on the person's name, email, the words of the line, its action and the
address it came from, and every typed word must be found. Nothing typed is ever put into the SQL text."""

from __future__ import annotations

import re

LOG_GROUPS: dict[str, tuple[str, ...]] = {
    "messages": ("ask",),
    "sign_in": (
        "sign_in",
        "sign_in_failed",
        "sign_in_refused",
        "locked_out",
        "sign_out",
    ),
    "sign_up": (
        "sign_up",
        "sign_up_failed",
        "sign_up_unknown",
        "code_sent",
        "password_reset",
        "reset_failed",
        "reset_unknown",
    ),
    "access": (
        "access_given",
        "access_taken",
        "switched_on",
        "switched_off",
        "super_added",
        "signed_out_everywhere",
        "invite_again",
    ),
}
LOG_VIEWS = ("all", "messages", "sign_in", "problems", "sign_up", "access")
LOG_RANGES = ("all", "today", "7d", "30d")
LOG_VIEW_PATTERN = "^(" + "|".join(LOG_VIEWS) + ")$"
LOG_RANGE_PATTERN = "^(" + "|".join(LOG_RANGES) + ")$"

TIMEZONE = "Asia/Kolkata"  # "today" starts at midnight here
MAX_TERMS = 6  # words of a search that count; the rest are ignored

_SINCE = {
    "today": f"p.at >= (date_trunc('day', now() AT TIME ZONE '{TIMEZONE}') AT TIME ZONE '{TIMEZONE}')",
    "7d": "p.at >= now() - interval '7 days'",
    "30d": "p.at >= now() - interval '30 days'",
}
_FROM = "FROM panel_audit p LEFT JOIN panel_accounts a ON a.id = p.account_id"

# what ask.py writes: "Asked the super admins (1 of 2 emails sent): the message"
_ASKED = re.compile(
    r"^Asked the super admins \((\d+) of (\d+) emails sent\): (.*)$", re.DOTALL
)


def split_ask(detail: str | None) -> tuple[str | None, int | None, int | None]:
    """(the message, emails sent, emails tried) of an "ask" line; (None, None, None) for any other text."""
    found = _ASKED.match(detail or "")
    if not found:
        return None, None, None
    return found.group(3).strip(), int(found.group(1)), int(found.group(2))


def _filters(q: str, org: str, range_: str) -> tuple[list[str], list]:
    where: list[str] = []
    params: list = []

    def add(value) -> str:
        params.append(value)
        return f"${len(params)}"

    for word in (q or "").lower().split()[:MAX_TERMS]:
        where.append(
            "strpos(lower(concat_ws(' ', a.name, p.email, p.detail, "
            f"replace(p.action, '_', ' '), p.ip)), {add(word)}::text) > 0"
        )
    if org:
        key = add(org)
        # a line about the organisation, or by someone who is an admin of it
        where.append(
            f"(p.source_key = {key}::text OR {key}::text = ANY(a.source_keys))"
        )
    if range_ in _SINCE:
        where.append(_SINCE[range_])
    return where, params


def _line(r) -> dict:
    message, sent, tried = (
        split_ask(r["detail"]) if r["action"] == "ask" else (None, None, None)
    )
    if r["source_key"]:
        orgs = [r["source_key"]]
    elif r["level"] == "admin":
        orgs = list(r["account_orgs"] or [])
    else:
        orgs = []
    return {
        "id": r["id"],
        "at": r["at"].isoformat(),
        "who": r["who"],
        "email": r["email"],
        "action": r["action"],
        "ok": r["ok"],
        "org": r["source_key"],
        "orgs": orgs,
        "detail": r["detail"],
        "message": message,
        "emails_sent": sent,
        "emails_tried": tried,
        "ip": r["ip"],
    }


async def read_log(
    pool,
    *,
    view: str = "all",
    q: str = "",
    org: str = "",
    range_: str = "all",
    page: int = 1,
    page_size: int = 40,
) -> dict:
    """One page of the log, newest first, and how many lines each button would show under the same
    search, organisation and range (so the numbers on the buttons always match what a click shows)."""
    where, params = _filters(q, org, range_)
    base = " AND ".join(where) or "TRUE"

    count_params = list(params)
    parts = ["count(*) AS n_all", "count(*) FILTER (WHERE NOT p.ok) AS n_problems"]
    for key, actions in LOG_GROUPS.items():
        count_params.append(list(actions))
        parts.append(
            f"count(*) FILTER (WHERE p.action = ANY(${len(count_params)}::text[])) AS n_{key}"
        )
    got = await pool.fetchrow(
        f"SELECT {', '.join(parts)} {_FROM} WHERE {base}", *count_params
    )
    counts = {"all": got["n_all"], "problems": got["n_problems"]}
    counts.update({key: got[f"n_{key}"] for key in LOG_GROUPS})

    line_where, line_params = base, list(params)
    if view == "problems":
        line_where += " AND NOT p.ok"
    elif view in LOG_GROUPS:
        line_params.append(list(LOG_GROUPS[view]))
        line_where += f" AND p.action = ANY(${len(line_params)}::text[])"
    line_params += [page_size, (page - 1) * page_size]
    found = await pool.fetch(
        "SELECT p.id, p.at, p.email, COALESCE(a.name, p.email, 'Someone') AS who, p.action, p.ok, "
        "p.source_key, p.detail, p.ip, a.level, a.source_keys AS account_orgs "
        f"{_FROM} WHERE {line_where} ORDER BY p.id DESC "
        f"LIMIT ${len(line_params) - 1} OFFSET ${len(line_params)}",
        *line_params,
    )
    return {"total": counts[view], "counts": counts, "rows": [_line(r) for r in found]}
