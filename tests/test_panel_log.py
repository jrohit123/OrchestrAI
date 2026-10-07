"""The Sign-in log: the quick buttons, the search, the organisation and range filters, the message
lines, and that only a super admin can read it.

The first tests need no database. The rest call the dashboard in-process on the throwaway databases of
test_migrate.py (see test_panel_login.py)."""

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.admin_panel import auth_log
from tests.test_migrate import needs_pg
from tests.test_panel_login import GOOD, run

APP = Path(__file__).resolve().parent.parent / "app" / "admin_panel"
ASKED = "Asked the super admins ({} of {} emails sent): {}"


# ─────────────────────────────── no database needed ───────────────────────────────


def test_every_kind_of_line_the_code_can_write_has_a_button():
    """A new action cannot be added to the log without deciding which button shows it."""
    written = set()
    for name in ("auth_routes.py", "auth_accounts.py", "auth.py", "ask.py"):
        source = (APP / name).read_text(encoding="utf-8")
        written |= set(re.findall(r'audit\(\s*"([a-z_]+)"', source))
    written |= {
        "switched_on",
        "switched_off",
    }  # written as `"switched_on" if on else ...`
    grouped = [a for actions in auth_log.LOG_GROUPS.values() for a in actions]
    assert written, "the scan found nothing: the pattern no longer fits the code"
    assert written <= set(grouped), sorted(written - set(grouped))
    assert len(grouped) == len(set(grouped)), "an action is in two buttons"
    assert set(auth_log.LOG_GROUPS) | {"all", "problems"} == set(auth_log.LOG_VIEWS)


def test_the_screen_and_the_server_agree_on_the_buttons_and_ranges():
    from app.admin_panel.ui import js_super

    for view in auth_log.LOG_VIEWS:
        assert f"['{view}'," in js_super.JS, view
    for rng in auth_log.LOG_RANGES:
        assert f"['{rng}'," in js_super.JS, rng


def test_a_message_line_is_split_into_the_words_and_the_emails_that_went_out():
    assert auth_log.split_ask(ASKED.format(1, 2, "Please add Zoya")) == (
        "Please add Zoya",
        1,
        2,
    )
    long = "line one\nline two: with (brackets) and ): inside"
    assert auth_log.split_ask(ASKED.format(0, 1, long)) == (long, 0, 1)
    assert auth_log.split_ask("Kartik switched Anuja off") == (None, None, None)
    assert auth_log.split_ask(None) == (None, None, None)


# ─────────────────────────────── on the throwaway databases ───────────────────────────────


async def _lines(p):
    """A log with every kind of line, in two organisations, over 40 days. Returns the account ids."""
    kartik = await p.add_account("kartik@x.test", "Kartik", "super", (), "active", GOOD)
    anuja = await p.add_account(
        "anuja@x.test", "Anuja Sinkar", "admin", ["alpha"], "active", GOOD
    )
    zoya = await p.add_account(
        "zoya@x.test", "Zoya Khan", "admin", ["alpha", "beta"], "active", GOOD
    )
    rows = [
        # (days ago, hours ago, account, email, action, ok, org, detail, ip)
        (
            40,
            0,
            kartik,
            "kartik@x.test",
            "sign_in",
            True,
            None,
            "Signed in",
            "10.0.0.1",
        ),
        (
            20,
            0,
            anuja,
            "anuja@x.test",
            "sign_up",
            True,
            None,
            "Chose a password",
            "10.0.0.2",
        ),
        (
            10,
            0,
            None,
            "who@x.test",
            "sign_in_failed",
            False,
            None,
            "Unknown email",
            "9.9.9.9",
        ),
        (
            5,
            0,
            kartik,
            "kartik@x.test",
            "access_given",
            True,
            "alpha",
            "Kartik gave Anuja access to Alpha Co",
            "10.0.0.1",
        ),
        (
            3,
            0,
            anuja,
            "anuja@x.test",
            "ask",
            True,
            "alpha",
            ASKED.format(1, 1, "Please add Venkat as admin"),
            "10.0.0.2",
        ),
        (
            2,
            0,
            zoya,
            "zoya@x.test",
            "ask",
            True,
            "beta",
            ASKED.format(1, 1, "Change the role of Mira\nand tell me"),
            "10.0.0.3",
        ),
        (1, 0, anuja, "anuja@x.test", "sign_in", True, None, "Signed in", "10.0.0.2"),
        (
            0,
            5,
            anuja,
            "anuja@x.test",
            "sign_in_failed",
            False,
            None,
            "Wrong password",
            "10.0.0.2",
        ),
        (
            0,
            4,
            anuja,
            "anuja@x.test",
            "code_sent",
            True,
            None,
            "Reset code emailed",
            "10.0.0.2",
        ),
        (
            0,
            3,
            kartik,
            "kartik@x.test",
            "switched_off",
            True,
            None,
            "Kartik switched Zoya off",
            "10.0.0.1",
        ),
        (
            0,
            2,
            zoya,
            "zoya@x.test",
            "ask",
            False,
            "alpha",
            ASKED.format(0, 1, "Nobody could be emailed"),
            "10.0.0.3",
        ),
        (0, 1, kartik, "kartik@x.test", "sign_in", True, None, "Signed in", "10.0.0.1"),
    ]
    for days, hours, acct, email, action, ok, org, detail, ip in rows:
        await p.sql(
            "INSERT INTO panel_audit (at, account_id, email, action, ok, source_key, detail, ip) "
            "VALUES (now() - make_interval(days => $1, hours => $2), $3::uuid, $4, $5, $6, $7, $8, $9)",
            days,
            hours,
            acct,
            email,
            action,
            ok,
            org,
            detail,
            ip,
        )
    return kartik, anuja, zoya


async def _read(c, **query):
    r = await c.get("/admin/_auth/activity", params=query)
    assert r.status_code == 200, r.text
    return r.json()


def _ids(body):
    return [(x["action"], x["who"]) for x in body["rows"]]


@needs_pg
def test_the_buttons_search_organisation_and_range_narrow_the_log(world, monkeypatch):
    async def scenario(p):
        await _lines(p)
        async with p.client() as c:
            await p.sign_in(c, "kartik@x.test")
            # signing in wrote a line of its own: leave only the twelve seeded ones to count
            await p.sql(
                "DELETE FROM panel_audit WHERE at > now() - interval '1 minute'"
            )
            everything = await _read(c)
            assert everything["total"] == 12 and len(everything["rows"]) == 12
            assert everything["counts"] == {
                "all": 12,
                "problems": 3,
                "messages": 3,
                "sign_in": 5,
                "sign_up": 2,
                "access": 2,
            }
            # newest first
            assert everything["rows"][0]["action"] == "sign_in"
            assert everything["rows"][0]["who"] == "Kartik"
            assert everything["rows"][-1]["at"] < everything["rows"][0]["at"]
            assert everything["orgs"] == [
                {"key": "alpha", "name": "Alpha Co"},
                {"key": "beta", "name": "Beta Co"},
            ]

            # the buttons
            msgs = await _read(c, view="messages")
            assert msgs["total"] == 3 and {x["action"] for x in msgs["rows"]} == {"ask"}
            problems = await _read(c, view="problems")
            assert problems["total"] == 3
            assert {x["action"] for x in problems["rows"]} == {"sign_in_failed", "ask"}
            assert not any(x["ok"] for x in problems["rows"])
            assert (await _read(c, view="sign_in"))["total"] == 5
            assert (await _read(c, view="sign_up"))["total"] == 2
            assert (await _read(c, view="access"))["total"] == 2

            # a message shows its own words, not the whole sentence of the log
            by_who = {x["who"]: x for x in msgs["rows"] if x["ok"]}
            anuja = by_who["Anuja Sinkar"]
            assert anuja["message"] == "Please add Venkat as admin"
            assert (anuja["emails_sent"], anuja["emails_tried"]) == (1, 1)
            assert (
                by_who["Zoya Khan"]["message"] == "Change the role of Mira\nand tell me"
            )
            failed = next(x for x in msgs["rows"] if not x["ok"])
            assert (failed["emails_sent"], failed["emails_tried"]) == (0, 1)
            # other lines carry no message
            assert all(
                x["message"] is None for x in everything["rows"] if x["action"] != "ask"
            )

            # search: a name, an email, words of a message, the words of the action, an address
            # her own five lines, and the one line that names her ("Kartik gave Anuja access")
            assert (await _read(c, q="anuja"))["total"] == 6
            assert (await _read(c, q="ZOYA"))["total"] == 3  # not case sensitive
            assert (await _read(c, q="venkat"))["total"] == 1
            assert (await _read(c, q="wrong password"))["total"] == 1
            assert (await _read(c, q="sign in failed"))[
                "total"
            ] == 2  # the action's words
            assert (await _read(c, q="9.9.9.9"))["total"] == 1
            assert (await _read(c, q="anuja ask"))[
                "total"
            ] == 1  # every word must be found
            assert (await _read(c, q="anuja nonsense"))["total"] == 0
            # what is typed is only text: no wildcard, no quote trouble
            for odd in ("%", "_", "100%", "a'b", '"; DROP TABLE panel_audit; --', "\\"):
                assert (await _read(c, q=odd))["total"] == 0, odd
            assert (await _read(c, q="   "))["total"] == 12  # blanks mean no search
            # the numbers on the buttons follow the search
            narrowed = await _read(c, q="anuja")
            assert narrowed["counts"] == {
                "all": 6,
                "problems": 1,
                "messages": 1,
                "sign_in": 2,
                "sign_up": 2,
                "access": 1,
            }

            # organisation: lines about it, and lines by someone who is its admin
            alpha = await _read(c, org="alpha")
            assert {x["who"] for x in alpha["rows"]} == {
                "Kartik",
                "Anuja Sinkar",
                "Zoya Khan",
            }
            # Anuja's 5 lines + Zoya's 2 (both are admins of alpha) + the line Kartik wrote about alpha
            assert alpha["total"] == 8
            beta = await _read(c, org="beta")
            assert beta["total"] == 2 and {x["who"] for x in beta["rows"]} == {
                "Zoya Khan"
            }
            assert (await _read(c, org="nowhere"))["total"] == 0
            both = await _read(c, org="alpha", view="messages")
            assert both["total"] == 3

            # range
            assert (await _read(c, range="all"))["total"] == 12
            assert (await _read(c, range="30d"))[
                "total"
            ] == 11  # all but the one 40 days old
            assert (await _read(c, range="7d"))["total"] == 9
            # "today" starts at midnight in India
            ist = timezone(timedelta(hours=5, minutes=30))
            midnight = datetime.now(ist).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            expected = sum(
                1
                for x in everything["rows"]
                if datetime.fromisoformat(x["at"]) >= midnight
            )
            assert (await _read(c, range="today"))["total"] == expected
            # the filters work together
            mixed = await _read(c, view="messages", org="beta", range="7d", q="mira")
            assert mixed["total"] == 1 and mixed["rows"][0]["who"] == "Zoya Khan"

            # pages keep the filters
            first = await _read(c, view="sign_in", page_size=2, page=1)
            second = await _read(c, view="sign_in", page_size=2, page=2)
            third = await _read(c, view="sign_in", page_size=2, page=3)
            assert first["total"] == second["total"] == 5
            ids = [x["id"] for x in first["rows"] + second["rows"] + third["rows"]]
            assert (
                len(ids) == 5
                and len(set(ids)) == 5
                and ids == sorted(ids, reverse=True)
            )
            assert (await _read(c, view="sign_in", page=9))["rows"] == []

    run(world, monkeypatch, scenario)


@needs_pg
def test_each_line_says_which_organisation_it_belongs_to(world, monkeypatch):
    async def scenario(p):
        await _lines(p)
        async with p.client() as c:
            await p.sign_in(c, "kartik@x.test")
            rows = (await _read(c, page_size=100))["rows"]
            by = {}
            for x in rows:
                by.setdefault((x["who"], x["action"]), x["orgs"])
            assert by[("Kartik", "access_given")] == ["alpha"]  # the line names it
            assert by[("Anuja Sinkar", "sign_up")] == ["alpha"]  # an admin: hers
            assert by[("Zoya Khan", "ask")] in (["alpha"], ["beta"])
            assert by[("Kartik", "sign_in")] == []  # a super admin belongs to none
            assert by[("who@x.test", "sign_in_failed")] == []  # nobody we know

    run(world, monkeypatch, scenario)


@needs_pg
def test_only_a_super_admin_can_read_the_log_and_the_made_up_answers_are_refused(
    world, monkeypatch
):
    async def scenario(p):
        await _lines(p)
        async with p.client() as anon:
            assert (await anon.get("/admin/_auth/activity")).status_code == 401
        async with p.client() as a:
            await p.sign_in(a, "anuja@x.test")
            assert (await a.get("/admin/_auth/activity")).status_code == 403
            assert (
                await a.get("/admin/_auth/activity?view=messages")
            ).status_code == 403
        async with p.client() as s:
            await p.sign_in(s, "kartik@x.test")
            for bad in (
                {"view": "everything"},
                {"range": "yesterday"},
                {"page": 0},
                {"page_size": 101},
                {"q": "x" * 101},
                {"org": "x" * 101},
            ):
                r = await s.get("/admin/_auth/activity", params=bad)
                assert r.status_code == 422, bad

    run(world, monkeypatch, scenario)


@needs_pg
def test_an_admins_message_is_kept_whole_in_the_log(world, monkeypatch):
    async def scenario(p):
        await p.add_account(
            "anuja@x.test", "Anuja Sinkar", "admin", ["alpha"], "active", GOOD
        )
        await p.add_account("kartik@x.test", "Kartik", "super", (), "active", GOOD)
        text = "Please add Mr Venkateshwarlu as an admin. " * 12  # over 200 letters
        async with p.client() as a, p.client() as s:
            await p.sign_in(a, "anuja@x.test")
            r = await a.post("/admin/alpha/api/v2/ask", json={"text": text})
            assert r.status_code == 200
            await p.sign_in(s, "kartik@x.test")
            body = await _read(s, view="messages")
            assert body["total"] == 1
            line = body["rows"][0]
            assert line["message"] == text.strip() and len(line["message"]) > 400
            assert line["who"] == "Anuja Sinkar" and line["orgs"] == ["alpha"]
            assert (line["emails_sent"], line["emails_tried"]) == (1, 1)

    run(world, monkeypatch, scenario)
