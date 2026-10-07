"""The dashboard sign-in, end to end: sign up, sign in, codes, locks, sessions, the organisation
lock, what an admin may do, and giving or taking access.

The app is called in-process (no network) with real pools on the throwaway databases of
test_migrate.py (MIGRATE_TEST_PG): `control` is the routing database, `alpha` and `beta` are clients.
No email leaves the computer: the sender is replaced by one that keeps what it was asked to send.
"""

import asyncio
import re
from contextlib import asynccontextmanager
from pathlib import Path

import asyncpg
import httpx
import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute

from app import db
from app.admin_panel import (
    access_rules,
    auth,
    auth_accounts,
    auth_mail,
    auth_routes,
    common,
)
from app.admin_panel import router as panel_router
from tests.test_migrate import needs_pg

ROOT = Path(__file__).resolve().parent.parent
CONTROL_SQL = (
    ROOT / "migrations" / "control" / "control-0001_panel_login.sql"
).read_text(encoding="utf-8")

CLIENT_SQL = """
CREATE TABLE orgs (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), name text NOT NULL, industry text,
    logo_url text, settings jsonb NOT NULL DEFAULT '{}', is_active boolean NOT NULL DEFAULT true);
CREATE TABLE roles (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), org_id uuid NOT NULL, name text NOT NULL,
    permissions text[] DEFAULT '{}', readable_tables text[] NOT NULL DEFAULT '{}',
    readable_entity_types text[] NOT NULL DEFAULT '{}', is_approver boolean NOT NULL DEFAULT false,
    approval_max_amount numeric(12,2), UNIQUE (org_id, name));
CREATE TABLE users (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), org_id uuid NOT NULL,
    role_id uuid REFERENCES roles(id), name text NOT NULL, phone text, email text NOT NULL,
    channel text DEFAULT 'telegram', is_active boolean DEFAULT true, created_at timestamptz DEFAULT now(),
    UNIQUE (org_id, email));
CREATE TABLE workflows (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), org_id uuid NOT NULL,
    intent_key text NOT NULL, name text NOT NULL, description text, steps jsonb DEFAULT '[]',
    entity_schema jsonb NOT NULL DEFAULT '{}', gates jsonb NOT NULL DEFAULT '[]',
    is_active boolean DEFAULT true, kind text NOT NULL DEFAULT 'workflow', UNIQUE (org_id, intent_key));
CREATE TABLE cases (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), org_id uuid NOT NULL, case_number text,
    title text, description text, status text NOT NULL DEFAULT 'reported', priority text, location text,
    created_at timestamptz NOT NULL DEFAULT now(), closed_at timestamptz, due_date timestamptz,
    custom_fields jsonb NOT NULL DEFAULT '{}', complainant_id uuid, assigned_to_id uuid);
CREATE TABLE admin_events (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), org_id uuid NOT NULL,
    actor_user_id uuid, actor_label text, area text NOT NULL, action text NOT NULL, target_type text,
    target_id text, summary text NOT NULL, before_state jsonb, after_state jsonb,
    created_at timestamptz NOT NULL DEFAULT now());
"""

NAMES = {"alpha": "Alpha Co", "beta": "Beta Co"}
GOOD = "a fine long password"
OTHER = "another fine password"


class Panel:
    """The dashboard wired to the throwaway databases, with the mail caught."""

    def __init__(self, app, control, pools):
        self.app, self.control, self.pools = app, control, pools
        self.mails: list[dict] = []

    def client(self, headers=None) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app),
            base_url="https://testserver",
            headers={"X-Panel": "1", **(headers or {})},
        )

    async def sql(self, query, *args, db_name="control"):
        pool = self.control if db_name == "control" else self.pools[db_name]
        return await pool.fetch(query, *args)

    async def add_account(
        self, email, name, level, orgs=(), status="invited", password=None
    ):
        hashed = await auth.hash_password(password) if password else None
        return str(
            (
                await self.sql(
                    "INSERT INTO panel_accounts (email, name, level, source_keys, status, password_hash) "
                    "VALUES ($1, $2, $3, $4, $5, $6) RETURNING id",
                    email,
                    name,
                    level,
                    list(orgs),
                    status,
                    hashed,
                )
            )[0]["id"]
        )

    def last_code(self, email):
        for mail in reversed(self.mails):
            if mail["to"] == email:
                found = re.search(r"Your code is (\d{6})", mail["text"])
                if found:
                    return found.group(1)
        return None

    def mails_to(self, email):
        return [m for m in self.mails if m["to"] == email]

    async def age_codes(self, minutes=5):
        """Make every code older, as if time had passed (the wait between two codes, the expiry)."""
        await self.sql(
            "UPDATE panel_keys SET created_at = created_at - make_interval(mins => $1), "
            "expires_at = expires_at - make_interval(mins => $1) WHERE kind <> 'session'",
            minutes,
        )

    async def sign_up(self, c, email, password=GOOD):
        r = await c.post("/admin/_auth/sign-up/code", json={"email": email})
        assert r.status_code == 200, r.text
        r = await c.post(
            "/admin/_auth/sign-up",
            json={"email": email, "code": self.last_code(email), "password": password},
        )
        assert r.status_code == 200, r.text
        return r

    async def sign_in(self, c, email, password=GOOD, code=None):
        body = {"email": email, "password": password}
        if code:
            body["code"] = code
        return await c.post("/admin/_auth/sign-in", json=body)


@asynccontextmanager
async def panel(world, monkeypatch):
    control = await asyncpg.create_pool(
        world.dsn["control"], min_size=1, max_size=4, statement_cache_size=0
    )
    async with control.acquire() as conn:
        await conn.execute(CONTROL_SQL)
    pools = {}
    for key in ("alpha", "beta"):
        pool = await asyncpg.create_pool(
            world.dsn[key], min_size=1, max_size=4, statement_cache_size=0
        )
        async with pool.acquire() as conn:
            await conn.execute(CLIENT_SQL)
            await conn.execute("INSERT INTO orgs (name) VALUES ($1)", NAMES[key])
        pools[key] = pool
        db._pools[key] = pool
    db._routing_pool = control
    app = FastAPI()
    app.include_router(panel_router)
    p = Panel(app, control, pools)

    async def fake_send(to_email, to_name, subject, text, html=None):
        p.mails.append(
            {"to": to_email, "name": to_name, "subject": subject, "text": text}
        )
        return True

    monkeypatch.setattr(auth_mail, "send_email", fake_send)
    auth.reset_limits()
    auth_routes._names.clear()
    common._caps_cache.clear()
    common._channel_cache.clear()
    try:
        yield p
    finally:
        db._routing_pool = None
        for key, pool in pools.items():
            db._pools.pop(key, None)
            await pool.close()
        await control.close()


def run(world, monkeypatch, scenario):
    async def go():
        async with panel(world, monkeypatch) as p:
            return await scenario(p)

    return asyncio.run(go())


# ─────────────────────────────── no database needed ───────────────────────────────


def test_every_panel_call_has_exactly_one_rule():
    app = FastAPI()
    app.include_router(panel_router)
    seen = set()
    for r in app.routes:
        if isinstance(r, APIRoute) and r.path.startswith(access_rules.PREFIX):
            deps = [d.call for d in r.dependant.dependencies]
            for m in r.methods - {"HEAD", "OPTIONS"}:
                key = (m, r.path[len(access_rules.PREFIX) :])
                seen.add(key)
                assert common.get_ctx in deps, f"{key} is not behind get_ctx"
    admin, sup = access_rules.ADMIN_CALLS, access_rules.SUPER_CALLS
    assert not (admin & sup), "a call is listed twice"
    assert seen - (admin | sup) == set(), "calls with no rule"
    assert (admin | sup) - seen == set(), "rules for calls that do not exist"


def test_the_sign_in_routes_are_open_only_where_they_must_be():
    app = FastAPI()
    app.include_router(panel_router)
    open_calls = {
        ("GET", "/org/{org_slug}"),
        ("POST", "/sign-in"),
        ("POST", "/sign-out"),
        ("POST", "/sign-up/code"),
        ("POST", "/sign-up"),
        ("POST", "/forgot/code"),
        ("POST", "/forgot"),
    }
    seen_open = set()
    for r in app.routes:
        if isinstance(r, APIRoute) and r.path.startswith("/admin/_auth"):
            deps = [d.call for d in r.dependant.dependencies]
            for m in r.methods - {"HEAD", "OPTIONS"}:
                key = (m, r.path[len("/admin/_auth") :])
                if key in open_calls:
                    seen_open.add(key)
                    assert auth.require_account not in deps
                else:
                    assert auth.require_account in deps or auth.require_super in deps, (
                        f"{key} can be called without signing in"
                    )
    assert seen_open == open_calls


def test_the_page_routes_are_the_known_ones():
    app = FastAPI()
    app.include_router(panel_router)
    pages = {
        r.path
        for r in app.routes
        if isinstance(r, APIRoute)
        and r.path.startswith("/admin")
        and "api/v2" not in r.path
        and "_auth" not in r.path
    }
    assert pages == {
        "/admin",
        "/admin/{org_slug}",
        "/admin-assets/panel.css",
        "/admin-assets/panel.js",
    }


def test_passwords_are_hashed_slowly_and_checked_in_constant_form():
    first, second = (
        auth.hash_password_sync(GOOD),
        auth.hash_password_sync(GOOD),
    )
    assert first != second  # a new salt every time
    assert first.startswith("scrypt$15$8$1$") and GOOD not in first
    assert auth.verify_password_sync(first, GOOD)
    assert not auth.verify_password_sync(first, GOOD + "x")
    assert not auth.verify_password_sync(None, GOOD)  # nobody stored: still no
    assert not auth.verify_password_sync("scrypt$bad", GOOD)
    assert not auth.verify_password_sync("md5$1$2$3$4$5", GOOD)


@pytest.mark.parametrize(
    "password, email, name, fragment",
    [
        ("short", "a@x.test", "A", "at least 10"),
        ("x" * 201, "a@x.test", "A", "at most 200"),
        ("password123", "a@x.test", "A", "too easy"),
        ("anuja.sinkar", "anuja.sinkar@x.test", "Anuja", "too easy"),
        ("anuja.sinkar@x.test", "anuja.sinkar@x.test", "Anuja", "too easy"),
        ("Anuja Sinkar", "a@x.test", "Anuja Sinkar", "too easy"),
        ("aaaaaaaaaaaa", "a@x.test", "A", "too easy"),
        (GOOD, "a@x.test", "A", None),
    ],
)
def test_password_rules(password, email, name, fragment):
    message = auth.check_password(password, email, name)
    if fragment is None:
        assert message is None
    else:
        assert fragment in message


def test_small_helpers():
    assert auth.clean_email("  Anuja@Godrej.Test ") == "anuja@godrej.test"
    for bad in ("", "no-at-sign", "a@b", "a b@c.d", None, "x" * 300 + "@y.zz"):
        assert auth.clean_email(bad) is None
    assert auth.clean_code(" 123 456 ") == "123456"
    assert auth.clean_code("12345") is None
    assert auth.clean_code("1234567") is None
    assert auth.clean_code(None) is None
    codes = {auth.new_code() for _ in range(200)}
    assert all(len(c) == 6 and c.isdigit() for c in codes) and len(codes) > 150


def test_the_callers_address_is_the_last_forwarded_one():
    from starlette.requests import Request

    def request(headers, client=("10.0.0.1", 1)):
        return Request(
            {
                "type": "http",
                "headers": [
                    (k.lower().encode(), v.encode()) for k, v in headers.items()
                ],
                "client": client,
                "method": "GET",
                "path": "/",
                "query_string": b"",
            }
        )

    ip, agent = auth.client_info(
        request({"X-Forwarded-For": "6.6.6.6, 203.0.113.9", "User-Agent": "Test/1"})
    )
    assert (ip, agent) == ("203.0.113.9", "Test/1")  # what the proxy itself saw
    assert auth.client_info(request({}))[0] == "10.0.0.1"
    assert auth.client_info(request({}, client=None))[0] == ""


def test_the_window_lets_a_few_through_then_stops():
    window = auth._Window(3, 600)
    assert [window.allow("a") for _ in range(4)] == [True, True, True, False]
    assert window.allow("b")  # someone else is not affected


# ─────────────────────────────── with the databases ───────────────────────────────


@needs_pg
def test_an_invited_admin_signs_up_signs_out_and_signs_in(world, monkeypatch):
    async def scenario(p):
        await p.add_account("anuja@x.test", "Anuja Sinkar", "admin", ["alpha"])
        async with p.client() as c:
            r = await c.post(
                "/admin/_auth/sign-up/code", json={"email": " ANUJA@x.test "}
            )
            assert r.status_code == 200 and r.json()["ok"]
            code = p.last_code("anuja@x.test")
            assert code
            body = {"email": "anuja@x.test", "code": code}
            # the password rules are shown only to someone who holds the code
            r = await c.post("/admin/_auth/sign-up", json={**body, "password": "short"})
            assert r.status_code == 400 and "at least 10" in r.json()["detail"]
            wrong = "000000" if code != "000000" else "111111"
            r = await c.post(
                "/admin/_auth/sign-up",
                json={"email": body["email"], "code": wrong, "password": GOOD},
            )
            assert (
                r.status_code == 400 and r.json()["detail"] == auth_routes.GENERIC_CODE
            )
            r = await c.post("/admin/_auth/sign-up", json={**body, "password": GOOD})
            assert r.status_code == 200, r.text
            assert r.json()["account"]["orgs"] == [{"key": "alpha", "name": "Alpha Co"}]
            cookie = r.headers["set-cookie"]
            assert "HttpOnly" in cookie and "Secure" in cookie
            assert "SameSite=lax" in cookie and "Path=/admin" in cookie
            me = (await c.get("/admin/_auth/me")).json()["account"]
            assert me["email"] == "anuja@x.test" and me["level"] == "admin"
            # the code is used up and the account is no longer "invited"
            r = await c.post("/admin/_auth/sign-up", json={**body, "password": OTHER})
            assert r.status_code == 400
            await c.post("/admin/_auth/sign-out", json={})
            assert (await c.get("/admin/_auth/me")).status_code == 401
            r = await p.sign_in(c, "anuja@x.test", "no no no no no")
            assert r.status_code == 401 and r.json()["detail"] == auth.WRONG
            r = await p.sign_in(c, "ANUJA@x.test")
            assert r.status_code == 200
            assert (await c.get("/admin/_auth/me")).status_code == 200
        row = (await p.sql("SELECT status, last_sign_in FROM panel_accounts"))[0]
        assert row["status"] == "active" and row["last_sign_in"] is not None
        log = [
            r["action"]
            for r in await p.sql("SELECT action FROM panel_audit ORDER BY id")
        ]
        for wanted in ("code_sent", "sign_up", "sign_out", "sign_in_failed", "sign_in"):
            assert wanted in log

    run(world, monkeypatch, scenario)


@needs_pg
def test_a_stranger_learns_nothing_from_the_sign_up_and_reset_pages(world, monkeypatch):
    async def scenario(p):
        await p.add_account("invited@x.test", "Invited", "admin", ["alpha"])
        await p.add_account("off@x.test", "Off", "admin", ["alpha"], status="off")
        await p.add_account("on@x.test", "On", "admin", ["alpha"], "active", GOOD)
        async with p.client() as c:
            answers = []
            for email in (
                "invited@x.test",
                "off@x.test",
                "on@x.test",
                "nobody@x.test",
                "not an email",
            ):
                r = await c.post("/admin/_auth/sign-up/code", json={"email": email})
                assert r.status_code == 200
                answers.append(r.json())
            assert all(a == answers[0] for a in answers)  # the same words every time
            assert [m["to"] for m in p.mails] == ["invited@x.test", "on@x.test"]
            assert "already have an account" in p.mails[1]["subject"]
            # the reset page: same
            p.mails.clear()
            await p.age_codes()
            answers = []
            for email in ("invited@x.test", "off@x.test", "on@x.test", "nobody@x.test"):
                r = await c.post("/admin/_auth/forgot/code", json={"email": email})
                assert r.status_code == 200
                answers.append(r.json())
            assert all(a == answers[0] for a in answers)
            assert [m["to"] for m in p.mails] == ["on@x.test"]
            # finishing with a wrong code, a wrong address or an uninvited address: one answer
            seen = set()
            for email, code in (
                ("invited@x.test", "123456"),
                ("nobody@x.test", "123456"),
                ("off@x.test", "123456"),
            ):
                r = await c.post(
                    "/admin/_auth/sign-up",
                    json={"email": email, "code": code, "password": GOOD},
                )
                assert r.status_code == 400
                seen.add(r.json()["detail"])
            assert seen == {auth_routes.GENERIC_CODE}

    run(world, monkeypatch, scenario)


@needs_pg
def test_a_super_admin_signs_in_with_email_and_password_like_everyone_else(
    world, monkeypatch
):
    async def scenario(p):
        await p.add_account("kartik@x.test", "Kartik", "super")
        async with p.client() as c:
            await p.sign_up(
                c, "kartik@x.test"
            )  # the emailed code is asked once, at sign-up: signed in
            assert (await c.get("/admin/_auth/me")).json()["account"][
                "level"
            ] == "super"
            await c.post("/admin/_auth/sign-out", json={})
            assert (await c.get("/admin/_auth/me")).status_code == 401
            sent = len(p.mails_to("kartik@x.test"))
            # a later sign-in is the password and nothing else: in at once, no email sent
            r = await p.sign_in(c, "kartik@x.test")
            assert r.status_code == 200 and r.json()["account"]["level"] == "super"
            assert "step" not in r.json()
            assert (await c.get("/admin/_auth/me")).status_code == 200
            assert len(p.mails_to("kartik@x.test")) == sent
            await c.post("/admin/_auth/sign-out", json={})
            # a wrong password is still refused, and a code field sent by an old page changes nothing
            r = await p.sign_in(c, "kartik@x.test", GOOD + "x", code="123456")
            assert r.status_code == 401
            assert (await c.get("/admin/_auth/me")).status_code == 401
            r = await p.sign_in(c, "kartik@x.test", code="123456")
            assert r.status_code == 200
        actions = [r["action"] for r in await p.sql("SELECT action FROM panel_audit")]
        assert actions.count("code_sent") == 1  # the sign-up code, and no other
        assert actions.count("sign_in") == 2

    run(world, monkeypatch, scenario)


@needs_pg
def test_five_wrong_passwords_lock_the_account_for_a_while(world, monkeypatch):
    async def scenario(p):
        await p.add_account("anuja@x.test", "Anuja", "admin", ["alpha"], "active", GOOD)
        async with p.client() as c:
            for _ in range(4):
                r = await p.sign_in(c, "anuja@x.test", "wrong wrong wrong")
                assert r.status_code == 401
            r = await p.sign_in(c, "anuja@x.test", "wrong wrong wrong")
            assert r.status_code == 429 and "locked" in r.json()["detail"]
            # even the right password is refused while locked
            r = await p.sign_in(c, "anuja@x.test")
            assert r.status_code == 429 and "15 more minute" in r.json()["detail"]
            # time passes
            await p.sql(
                "UPDATE panel_accounts SET locked_until = now() - interval '1 minute'"
            )
            r = await p.sign_in(c, "anuja@x.test")
            assert r.status_code == 200
        row = (await p.sql("SELECT wrong_tries, locked_until FROM panel_accounts"))[0]
        assert row["wrong_tries"] == 0 and row["locked_until"] is None
        actions = [r["action"] for r in await p.sql("SELECT action FROM panel_audit")]
        assert "locked_out" in actions

    run(world, monkeypatch, scenario)


@needs_pg
def test_nobody_can_open_what_they_may_not(world, monkeypatch):
    async def scenario(p):
        await p.add_account("anuja@x.test", "Anuja", "admin", ["alpha"], "active", GOOD)
        lookups = "/admin/{}/api/v2/lookups"
        async with p.client() as anon:
            assert (await anon.get(lookups.format("alpha"))).status_code == 401
            assert (await anon.get(lookups.format("nope"))).status_code == 401
            r = await anon.get("/admin/_auth/orgs")
            assert r.status_code == 401
        async with p.client() as c:
            await p.sign_in(c, "anuja@x.test")
            assert (await c.get(lookups.format("alpha"))).status_code == 200
            r = await c.get(lookups.format("beta"))
            assert r.status_code == 403 and "cannot open" in r.json()["detail"]
            assert (await c.get(lookups.format("nope"))).status_code == 404
            # a change must carry the header only our own page sends
            r = await c.post(
                "/admin/alpha/api/v2/ask",
                json={"text": "hello there"},
                headers={"X-Panel": ""},
            )
            assert (
                r.status_code == 403
                and "did not come from the dashboard" in r.json()["detail"]
            )
        # a made-up cookie is nobody
        async with p.client() as forged:
            forged.cookies.set(
                "panel_session", "forged-value", domain="testserver", path="/admin"
            )
            assert (await forged.get(lookups.format("alpha"))).status_code == 401

    run(world, monkeypatch, scenario)


@needs_pg
def test_an_admin_gets_home_cases_and_people_and_a_super_admin_gets_everything(
    world, monkeypatch
):
    async def scenario(p):
        await p.add_account("anuja@x.test", "Anuja", "admin", ["alpha"], "active", GOOD)
        await p.add_account("kartik@x.test", "Kartik", "super", (), "active", GOOD)
        base = "/admin/alpha/api/v2"
        async with p.client() as a, p.client() as s:
            await p.sign_in(a, "anuja@x.test")
            boot = (await a.get(base + "/bootstrap")).json()
            assert {x["key"] for x in boot["sections"]} <= {
                "overview",
                "cases",
                "people",
            }
            assert boot["me"] == {
                "name": "Anuja",
                "email": "anuja@x.test",
                "level": "admin",
            }
            for path in (
                "/status",
                "/roles",
                "/workflows",
                "/messages",
                "/instructions",
                "/events",
            ):
                r = await a.get(base + path)
                assert r.status_code == 403, path
                assert r.json()["detail"] == "Only a super admin can do that."
            assert (await a.post(base + "/people", json={})).status_code == 403
            assert (await a.get(base + "/lookups")).status_code == 200
            # a super admin: the whole menu and the same calls
            r = await p.sign_in(s, "kartik@x.test")
            assert r.status_code == 200
            boot = (await s.get(base + "/bootstrap")).json()
            keys = {x["key"] for x in boot["sections"]}
            assert {"workflows", "access", "settings", "people", "cases"} <= keys
            assert boot["me"]["level"] == "super"
            assert (await s.get(base + "/status")).status_code == 200
            # the change log names who did it
            org = (await p.sql("SELECT id FROM orgs", db_name="alpha"))[0]["id"]
            role = (
                await p.sql(
                    "INSERT INTO roles (org_id, name) VALUES ($1, 'staff') RETURNING id",
                    org,
                    db_name="alpha",
                )
            )[0]["id"]
            r = await s.post(
                base + "/people",
                json={
                    "name": "New Person",
                    "email": "new@x.test",
                    "role_id": str(role),
                },
            )
            assert r.status_code == 200, r.text
        events = await p.sql("SELECT actor_label FROM admin_events", db_name="alpha")
        assert [e["actor_label"] for e in events] == [
            "dashboard · Kartik (super admin)"
        ]

    run(world, monkeypatch, scenario)


async def _sign_in_super(p, c, email="kartik@x.test"):
    r = await p.sign_in(c, email)
    assert r.status_code == 200, r.text


@needs_pg
def test_switching_someone_off_ends_their_session_at_once(world, monkeypatch):
    async def scenario(p):
        admin_id = await p.add_account(
            "anuja@x.test", "Anuja", "admin", ["alpha"], "active", GOOD
        )
        await p.add_account("kartik@x.test", "Kartik", "super", (), "active", GOOD)
        url = "/admin/alpha/api/v2/lookups"
        async with p.client() as a, p.client() as s:
            await p.sign_in(a, "anuja@x.test")
            await _sign_in_super(p, s)
            assert (await a.get(url)).status_code == 200
            r = await s.post(
                f"/admin/_auth/accounts/{admin_id}/switch", json={"on": False}
            )
            assert r.status_code == 200 and r.json()["account"]["status"] == "off"
            assert (await a.get(url)).status_code == 401  # on her very next click
            r = await p.sign_in(a, "anuja@x.test")
            assert r.status_code == 403 and "switched off" in r.json()["detail"]
            r = await s.post(
                f"/admin/_auth/accounts/{admin_id}/switch", json={"on": True}
            )
            assert r.json()["account"]["status"] == "active"
            assert (await p.sign_in(a, "anuja@x.test")).status_code == 200
            # sign someone out everywhere
            r = await s.post(f"/admin/_auth/accounts/{admin_id}/sign-out", json={})
            assert r.status_code == 200
            assert (await a.get(url)).status_code == 401

    run(world, monkeypatch, scenario)


@needs_pg
def test_taking_an_organisation_away_works_on_the_next_click(world, monkeypatch):
    async def scenario(p):
        admin_id = await p.add_account(
            "anuja@x.test", "Anuja", "admin", ["alpha", "beta"], "active", GOOD
        )
        await p.add_account("kartik@x.test", "Kartik", "super", (), "active", GOOD)
        async with p.client() as a, p.client() as s:
            await p.sign_in(a, "anuja@x.test")
            await _sign_in_super(p, s)
            assert (await a.get("/admin/_auth/me")).json()["account"]["orgs"] == [
                {"key": "alpha", "name": "Alpha Co"},
                {"key": "beta", "name": "Beta Co"},
            ]
            r = await s.post(
                f"/admin/_auth/accounts/{admin_id}/take-access",
                json={"source_key": "alpha"},
            )
            assert (
                r.json()["account"]["orgs"] == ["beta"]
                and r.json()["account"]["status"] == "active"
            )
            assert (await a.get("/admin/alpha/api/v2/lookups")).status_code == 403
            assert (await a.get("/admin/beta/api/v2/lookups")).status_code == 200
            r = await s.post(
                f"/admin/_auth/accounts/{admin_id}/take-access",
                json={"source_key": "alpha"},
            )
            assert r.status_code == 409  # nothing to take
            r = await s.post(
                f"/admin/_auth/accounts/{admin_id}/take-access",
                json={"source_key": "beta"},
            )
            assert r.json()["account"]["status"] == "off"  # no organisation left
            assert (await a.get("/admin/beta/api/v2/lookups")).status_code == 401
            # switching on without an organisation is refused until one is given
            r = await s.post(
                f"/admin/_auth/accounts/{admin_id}/switch", json={"on": True}
            )
            assert r.status_code == 409 and "organisation first" in r.json()["detail"]

    run(world, monkeypatch, scenario)


@needs_pg
def test_giving_access_invites_the_person_and_shows_on_the_people_list(
    world, monkeypatch
):
    async def scenario(p):
        await p.add_account("kartik@x.test", "Kartik", "super", (), "active", GOOD)
        org = (await p.sql("SELECT id FROM orgs", db_name="alpha"))[0]["id"]
        role = (
            await p.sql(
                "INSERT INTO roles (org_id, name) VALUES ($1, 'staff') RETURNING id",
                org,
                db_name="alpha",
            )
        )[0]
        people = {}
        for name, email, active in (
            ("Tina Rao", "tina@x.test", True),
            ("No Email", "", True),
            ("Gone Away", "gone@x.test", False),
            ("Kartik In Alpha", "kartik@x.test", True),
        ):
            people[name] = str(
                (
                    await p.sql(
                        "INSERT INTO users (org_id, role_id, name, email, is_active, phone) "
                        "VALUES ($1, $2, $3, $4, $5, 'tg:1') RETURNING id",
                        org,
                        role["id"],
                        name,
                        email or "none@x.test",
                        active,
                        db_name="alpha",
                    )
                )[0]["id"]
            )
        await p.sql(
            "UPDATE users SET email = '' WHERE name = 'No Email'", db_name="alpha"
        )
        async with p.client() as s:
            await _sign_in_super(p, s)
            give = "/admin/_auth/accounts/give-access"
            r = await s.post(
                give, json={"source_key": "alpha", "user_id": people["Tina Rao"]}
            )
            assert r.status_code == 200, r.text
            assert r.json()["created"] and r.json()["emailed"]
            assert r.json()["account"]["status"] == "invited" and r.json()["account"][
                "orgs"
            ] == ["alpha"]
            invite = p.mails_to("tina@x.test")[0]
            assert (
                "Alpha Co" in invite["subject"]
                and "https://testserver/admin/alpha" in invite["text"]
            )
            r = await s.post(
                give, json={"source_key": "alpha", "user_id": people["Tina Rao"]}
            )
            assert r.status_code == 409 and "already" in r.json()["detail"]
            r = await s.post(
                give, json={"source_key": "alpha", "user_id": people["No Email"]}
            )
            assert r.status_code == 400 and "no email" in r.json()["detail"]
            r = await s.post(
                give, json={"source_key": "alpha", "user_id": people["Gone Away"]}
            )
            assert r.status_code == 409
            r = await s.post(
                give, json={"source_key": "alpha", "user_id": people["Kartik In Alpha"]}
            )
            assert r.status_code == 409 and "super admin already" in r.json()["detail"]
            r = await s.post(
                give, json={"source_key": "nope", "user_id": people["Tina Rao"]}
            )
            assert r.status_code == 404
            # the people list tells who can sign in
            rows = (await s.get("/admin/alpha/api/v2/people")).json()["rows"]
            by_name = {x["name"]: x["dashboard"] for x in rows}
            assert (
                by_name["Tina Rao"]["level"] == "admin"
                and by_name["Tina Rao"]["status"] == "invited"
            )
            assert "account_id" in by_name["Tina Rao"]
            assert by_name["Kartik In Alpha"]["level"] == "super"
            assert by_name["Gone Away"] is None
            detail = (
                await s.get(f"/admin/alpha/api/v2/people/{people['Tina Rao']}")
            ).json()
            assert detail["person"]["dashboard"]["status"] == "invited"
        # the invited person signs up and, as an admin, sees the list without the account ids
        async with p.client() as t:
            await p.sign_up(t, "tina@x.test")
            rows = (await t.get("/admin/alpha/api/v2/people")).json()["rows"]
            tina = next(x for x in rows if x["name"] == "Tina Rao")
            assert tina["dashboard"] == {"level": "admin", "status": "active"}

    run(world, monkeypatch, scenario)


@needs_pg
def test_the_last_way_in_cannot_be_closed_and_you_cannot_switch_yourself_off(
    world, monkeypatch
):
    async def scenario(p):
        kartik = await p.add_account(
            "kartik@x.test", "Kartik", "super", (), "active", GOOD
        )
        rohit = await p.add_account("rohit@x.test", "Rohit", "super", (), "invited")
        async with p.client() as s:
            await _sign_in_super(p, s)
            r = await s.post(
                f"/admin/_auth/accounts/{kartik}/switch", json={"on": False}
            )
            assert r.status_code == 409 and "your own account" in r.json()["detail"]
            # an invited super admin has no password: switching on keeps them "invited"
            r = await s.post(
                f"/admin/_auth/accounts/{rohit}/switch", json={"on": False}
            )
            assert r.json()["account"]["status"] == "off"
            r = await s.post(f"/admin/_auth/accounts/{rohit}/switch", json={"on": True})
            assert r.json()["account"]["status"] == "invited"
        # nobody else active: refused even for a caller that is not in the table
        stranger = auth.Account(
            "00000000-0000-0000-0000-000000000001",
            "x@x.test",
            "X",
            "super",
            (),
            "active",
        )
        from starlette.requests import Request

        fake = Request(
            {
                "type": "http",
                "headers": [],
                "client": None,
                "method": "POST",
                "path": "/",
                "query_string": b"",
            }
        )
        with pytest.raises(Exception) as caught:
            await auth_accounts.switch(kartik, False, stranger, fake)
        assert "one super admin" in str(caught.value.detail)

    run(world, monkeypatch, scenario)


@needs_pg
def test_super_admins_can_add_super_admins_and_admins_cannot(world, monkeypatch):
    async def scenario(p):
        await p.add_account("kartik@x.test", "Kartik", "super", (), "active", GOOD)
        await p.add_account("anuja@x.test", "Anuja", "admin", ["alpha"], "active", GOOD)
        async with p.client() as s, p.client() as a:
            await _sign_in_super(p, s)
            await p.sign_in(a, "anuja@x.test")
            r = await a.post(
                "/admin/_auth/super-admins", json={"email": "x@x.test", "name": "X"}
            )
            assert r.status_code == 403
            assert (await a.get("/admin/_auth/accounts")).status_code == 403
            r = await s.post(
                "/admin/_auth/super-admins", json={"email": "bad", "name": "X"}
            )
            assert r.status_code == 400
            r = await s.post(
                "/admin/_auth/super-admins",
                json={"email": "Rohit@x.test", "name": "Rohit Jain"},
            )
            assert (
                r.status_code == 200
                and r.json()["account"]["level"] == "super"
                and r.json()["emailed"]
            )
            assert "https://testserver/admin" in p.mails_to("rohit@x.test")[0]["text"]
            r = await s.post(
                "/admin/_auth/super-admins",
                json={"email": "rohit@x.test", "name": "Rohit Jain"},
            )
            assert r.status_code == 409
            # an admin made a super admin opens every organisation and keeps no list
            r = await s.post(
                "/admin/_auth/super-admins",
                json={"email": "anuja@x.test", "name": "Anuja"},
            )
            assert r.json()["account"]["orgs"] == []
            listed = (await s.get("/admin/_auth/accounts")).json()["accounts"]
            assert [x["name"] for x in listed if x["level"] == "super"] == [
                "Anuja",
                "Kartik",
                "Rohit Jain",
            ]
            # he can invite again, but only while the person has not signed up
            rohit = next(x for x in listed if x["name"] == "Rohit Jain")["id"]
            r = await s.post(f"/admin/_auth/accounts/{rohit}/invite-again", json={})
            assert r.status_code == 200 and r.json()["emailed"]
            kartik = next(x for x in listed if x["name"] == "Kartik")["id"]
            r = await s.post(f"/admin/_auth/accounts/{kartik}/invite-again", json={})
            assert r.status_code == 409

    run(world, monkeypatch, scenario)


@needs_pg
def test_forgot_password_sets_a_new_one_and_signs_everyone_out(world, monkeypatch):
    async def scenario(p):
        await p.add_account("anuja@x.test", "Anuja", "admin", ["alpha"], "active", GOOD)
        async with p.client() as laptop, p.client() as phone:
            await p.sign_in(laptop, "anuja@x.test")
            await p.sign_in(phone, "anuja@x.test")
            url = "/admin/alpha/api/v2/lookups"
            assert (await laptop.get(url)).status_code == 200
            r = await phone.post(
                "/admin/_auth/forgot/code", json={"email": "anuja@x.test"}
            )
            assert r.status_code == 200
            code = p.last_code("anuja@x.test")
            body = {"email": "anuja@x.test", "code": code}
            r = await phone.post(
                "/admin/_auth/forgot", json={**body, "password": "short"}
            )
            assert r.status_code == 400 and "at least 10" in r.json()["detail"]
            r = await phone.post(
                "/admin/_auth/forgot", json={**body, "password": OTHER}
            )
            assert r.status_code == 200
            assert (
                await laptop.get(url)
            ).status_code == 401  # every browser signed out
            assert (await p.sign_in(laptop, "anuja@x.test", GOOD)).status_code == 401
            assert (await p.sign_in(laptop, "anuja@x.test", OTHER)).status_code == 200
            r = await phone.post("/admin/_auth/forgot", json={**body, "password": GOOD})
            assert r.status_code == 400  # the code is used up

    run(world, monkeypatch, scenario)


@needs_pg
def test_a_session_ends_when_it_is_not_used_and_a_code_after_ten_minutes(
    world, monkeypatch
):
    async def scenario(p):
        await p.add_account("anuja@x.test", "Anuja", "admin", ["alpha"], "active", GOOD)
        await p.add_account("kartik@x.test", "Kartik", "super", (), "active", GOOD)
        url = "/admin/_auth/me"
        async with p.client() as a, p.client() as s:
            await p.sign_in(a, "anuja@x.test")
            await _sign_in_super(p, s)
            await p.sql(
                "UPDATE panel_keys SET last_used = now() - interval '11 hours' WHERE kind = 'session'"
            )
            assert (await a.get(url)).status_code == 200  # admins: 12 hours
            assert (await s.get(url)).status_code == 401  # super admins: 4 hours
            await p.sql(
                "UPDATE panel_keys SET last_used = now() - interval '13 hours' WHERE kind = 'session'"
            )
            assert (await a.get(url)).status_code == 401
        # a code no longer works after ten minutes
        async with p.client() as c:
            await c.post("/admin/_auth/forgot/code", json={"email": "anuja@x.test"})
            code = p.last_code("anuja@x.test")
            await p.age_codes(11)
            r = await c.post(
                "/admin/_auth/forgot",
                json={"email": "anuja@x.test", "code": code, "password": OTHER},
            )
            assert r.status_code == 400

    run(world, monkeypatch, scenario)


@needs_pg
def test_codes_are_replaced_counted_and_cleaned_up(world, monkeypatch):
    async def scenario(p):
        account = await p.add_account(
            "anuja@x.test", "Anuja", "admin", ["alpha"], "active", GOOD
        )
        first, wait = await auth.issue_code(account, "reset")
        assert first and wait == 0
        again, wait = await auth.issue_code(account, "reset")
        assert again is None and 0 < wait <= 60  # not twice in a minute
        other, _ = await auth.issue_code(account, "signup")  # another kind is separate
        assert other
        await p.age_codes(2)
        second, wait = await auth.issue_code(account, "reset")
        assert second and wait == 0
        count = await p.sql("SELECT count(*) AS n FROM panel_keys WHERE kind = 'reset'")
        assert count[0]["n"] == 1  # the new code replaced the old one
        guess = "000000" if second != "000000" else "111111"
        # five wrong tries kill the code, even for the right one afterwards
        for _ in range(auth.CODE_TRIES):
            assert await auth.check_code(account, "reset", guess) == "wrong"
        assert await auth.check_code(account, "reset", second) == "too_many"
        # no code of that kind at all
        nobody = "00000000-0000-0000-0000-000000000000"
        assert await auth.check_code(nobody, "reset", "123456") == "none"
        # what can never be used again is removed; accounts and the log stay
        await p.sql("UPDATE panel_keys SET expires_at = now() - interval '2 days'")
        await p.sql("INSERT INTO panel_audit (action) VALUES ('x')")
        assert await auth.tidy_keys() == 2
        assert await p.sql("SELECT 1 FROM panel_keys") == []
        assert len(await p.sql("SELECT 1 FROM panel_accounts")) == 1
        assert len(await p.sql("SELECT 1 FROM panel_audit")) == 1

    run(world, monkeypatch, scenario)


@needs_pg
def test_the_sign_in_page_shows_only_the_organisations_name(world, monkeypatch):
    async def scenario(p):
        async with p.client() as c:
            r = await c.get("/admin/_auth/org/alpha")
            assert r.status_code == 200 and r.json() == {
                "key": "alpha",
                "name": "Alpha Co",
            }
            assert r.headers["cache-control"] == "no-store"
            assert (await c.get("/admin/_auth/org/nope")).status_code == 404
            page = await c.get("/admin")
            assert page.status_code == 200 and 'data-org=""' in page.text
            page = await c.get("/admin/beta")
            assert 'data-org="beta"' in page.text and "Beta Co" not in page.text

    run(world, monkeypatch, scenario)


@needs_pg
def test_an_admin_can_ask_the_super_admins(world, monkeypatch):
    async def scenario(p):
        await p.add_account(
            "anuja@x.test", "Anuja Sinkar", "admin", ["alpha"], "active", GOOD
        )
        async with p.client() as a:
            await p.sign_in(a, "anuja@x.test")
            r = await a.post(
                "/admin/alpha/api/v2/ask", json={"text": "Please add Zoya as committee"}
            )
            assert r.status_code == 409  # nobody to ask yet
            await p.add_account("kartik@x.test", "Kartik", "super", (), "active", GOOD)
            await p.add_account("rohit@x.test", "Rohit", "super", (), "off", GOOD)
            r = await a.post(
                "/admin/alpha/api/v2/ask",
                json={"text": "Please add Zoya <b>as</b> committee"},
            )
            assert r.status_code == 200 and r.json()["sent"] == 1
            mail = p.mails_to("kartik@x.test")[0]
            assert "Anuja Sinkar" in mail["subject"] and "Alpha Co" in mail["text"]
            assert p.mails_to("rohit@x.test") == []  # switched off: not asked
            assert (
                await a.post("/admin/alpha/api/v2/ask", json={"text": "x"})
            ).status_code == 422
        log = await p.sql(
            "SELECT action, source_key FROM panel_audit WHERE action = 'ask'"
        )
        assert [(r["action"], r["source_key"]) for r in log] == [("ask", "alpha")]

    run(world, monkeypatch, scenario)


async def _case_world(p, *, flow_on=True, with_setting=True, kind="workflow"):
    """Alpha with an admin, two people, a case, and a small 'pass on' flow the organisation chose."""
    org = (await p.sql("SELECT id FROM orgs", db_name="alpha"))[0]["id"]
    role = (
        await p.sql(
            "INSERT INTO roles (org_id, name) VALUES ($1, 'admin') RETURNING id",
            org,
            db_name="alpha",
        )
    )[0]["id"]
    ids = {}
    for name, email, phone in (
        ("Anuja Sinkar", "anuja@x.test", "tg:11"),
        ("Tina Rao", "tina@x.test", "tg:12"),
        ("Sleepy", "sleepy@x.test", "tg:13"),
    ):
        ids[name] = (
            await p.sql(
                "INSERT INTO users (org_id, role_id, name, email, phone, is_active) VALUES ($1, $2, $3, $4, $5, $6) RETURNING id",
                org,
                role,
                name,
                email,
                phone,
                name != "Sleepy",
                db_name="alpha",
            )
        )[0]["id"]
    case = (
        await p.sql(
            "INSERT INTO cases (org_id, case_number, title) VALUES ($1, 'CS-26-10-1', 'Leak') RETURNING id",
            org,
            db_name="alpha",
        )
    )[0]["id"]
    steps = (
        '[{"op": "resolve_entity", "params": {"table": "users", "into": "assignee", "name_from": "$fields.assignee_name", "match_column": "name"}},'
        ' {"op": "db.update_row", "params": {"table": "cases", "set": {"assigned_to_id": "$assignee.id"}, "where": {"case_number": "$fields.case_number"}}}]'
    )
    await p.sql(
        "INSERT INTO workflows (org_id, intent_key, name, kind, is_active, steps, entity_schema) "
        "VALUES ($1, 'case_pass_on', 'Pass to someone', $4, $2, $3::jsonb, '{}'::jsonb)",
        org,
        flow_on,
        steps,
        kind,
        db_name="alpha",
    )
    if with_setting:
        await p.sql(
            'UPDATE orgs SET settings = \'{"case_buttons": {"assign": "case_pass_on"}}\'::jsonb',
            db_name="alpha",
        )
    return ids, str(case)


@needs_pg
def test_assigning_runs_the_organisations_own_flow_as_the_signed_in_person(
    world, monkeypatch
):
    sent = []

    async def fake_text(to, text):
        sent.append((to, text))

    monkeypatch.setattr("app.services.messaging.send_text", fake_text)

    async def scenario(p):
        ids, case = await _case_world(p)
        await p.add_account(
            "anuja@x.test", "Anuja Sinkar", "admin", ["alpha"], "active", GOOD
        )
        await p.add_account("rohit@x.test", "Rohit", "super", (), "active", GOOD)
        base = "/admin/alpha/api/v2"
        async with p.client() as a:
            await p.sign_in(a, "anuja@x.test")
            boot = (await a.get(base + "/bootstrap")).json()
            assert boot["buttons"]["assign"] == {"name": "Pass to someone", "on": True}
            r = await a.post(
                f"{base}/cases/{case}/assign", json={"user_id": str(ids["Tina Rao"])}
            )
            assert r.status_code == 200, r.text
            assert r.json()["assignee_name"] == "Tina Rao"
            row = (await p.sql("SELECT assigned_to_id FROM cases", db_name="alpha"))[0]
            assert row["assigned_to_id"] == ids["Tina Rao"]  # the flow really ran
            event = (
                await p.sql(
                    "SELECT summary, actor_label FROM admin_events", db_name="alpha"
                )
            )[0]
            assert event["summary"] == "Gave CS-26-10-1 to Tina Rao"
            assert event["actor_label"] == "dashboard · Anuja Sinkar"
            # already there, switched off, unknown, someone else's case id
            r = await a.post(
                f"{base}/cases/{case}/assign", json={"user_id": str(ids["Tina Rao"])}
            )
            assert r.status_code == 409 and "already" in r.json()["detail"]
            r = await a.post(
                f"{base}/cases/{case}/assign", json={"user_id": str(ids["Sleepy"])}
            )
            assert r.status_code == 409 and "switched off" in r.json()["detail"]
            r = await a.post(
                f"{base}/cases/{case}/assign",
                json={"user_id": "00000000-0000-0000-0000-000000000009"},
            )
            assert r.status_code == 404
            r = await a.post(
                f"{base}/cases/00000000-0000-0000-0000-000000000009/assign",
                json={"user_id": str(ids["Tina Rao"])},
            )
            assert r.status_code == 404
        # a super admin with no person record here cannot act as one
        async with p.client() as s:
            await p.sign_in(s, "rohit@x.test")
            await s.post(
                "/admin/_auth/sign-in",
                json={
                    "email": "rohit@x.test",
                    "password": GOOD,
                    "code": p.last_code("rohit@x.test"),
                },
            )
            r = await s.post(
                f"{base}/cases/{case}/assign",
                json={"user_id": str(ids["Anuja Sinkar"])},
            )
            assert (
                r.status_code == 409
                and "must also belong to a person" in r.json()["detail"]
            )
        # an admin of the other organisation cannot reach it at all
        await p.add_account(
            "beta@x.test", "Beta Admin", "admin", ["beta"], "active", GOOD
        )
        async with p.client() as b:
            await p.sign_in(b, "beta@x.test")
            r = await b.post(
                f"{base}/cases/{case}/assign", json={"user_id": str(ids["Tina Rao"])}
            )
            assert r.status_code == 403

    run(world, monkeypatch, scenario)


@needs_pg
@pytest.mark.parametrize("kind", ["workflow", "case_action"])
def test_the_assign_flow_may_be_a_normal_flow_or_a_case_action(
    world, monkeypatch, kind
):
    async def scenario(p):
        ids, case = await _case_world(p, kind=kind)
        await p.add_account(
            "anuja@x.test", "Anuja Sinkar", "admin", ["alpha"], "active", GOOD
        )
        async with p.client() as a:
            await p.sign_in(a, "anuja@x.test")
            boot = (await a.get("/admin/alpha/api/v2/bootstrap")).json()
            assert boot["buttons"]["assign"] == {"name": "Pass to someone", "on": True}
            r = await a.post(
                f"/admin/alpha/api/v2/cases/{case}/assign",
                json={"user_id": str(ids["Tina Rao"])},
            )
            assert r.status_code == 200, r.text

    run(world, monkeypatch, scenario)


@needs_pg
def test_a_building_block_is_never_run_as_the_assign_button(world, monkeypatch):
    async def scenario(p):
        await _case_world(p, kind="block")
        await p.add_account(
            "anuja@x.test", "Anuja Sinkar", "admin", ["alpha"], "active", GOOD
        )
        async with p.client() as a:
            await p.sign_in(a, "anuja@x.test")
            boot = (await a.get("/admin/alpha/api/v2/bootstrap")).json()
            assert boot["buttons"]["assign"] is None

    run(world, monkeypatch, scenario)


@needs_pg
def test_the_assign_button_follows_the_flow(world, monkeypatch):
    async def scenario(p):
        ids, case = await _case_world(p, flow_on=False)
        await p.add_account(
            "anuja@x.test", "Anuja Sinkar", "admin", ["alpha"], "active", GOOD
        )
        base = "/admin/alpha/api/v2"
        async with p.client() as a:
            await p.sign_in(a, "anuja@x.test")
            assert (await a.get(base + "/bootstrap")).json()["buttons"]["assign"] == {
                "name": "Pass to someone",
                "on": False,
            }
            r = await a.post(
                f"{base}/cases/{case}/assign", json={"user_id": str(ids["Tina Rao"])}
            )
            assert r.status_code == 409 and "switched off" in r.json()["detail"]
            assert (await p.sql("SELECT assigned_to_id FROM cases", db_name="alpha"))[
                0
            ]["assigned_to_id"] is None
            await p.sql("UPDATE orgs SET settings = '{}'::jsonb", db_name="alpha")
            assert (await a.get(base + "/bootstrap")).json()["buttons"][
                "assign"
            ] is None
            r = await a.post(
                f"{base}/cases/{case}/assign", json={"user_id": str(ids["Tina Rao"])}
            )
            assert r.status_code == 409 and "not set up" in r.json()["detail"]

    run(world, monkeypatch, scenario)


@needs_pg
def test_an_admin_changes_a_role_but_not_their_own_and_cannot_switch_people_off(
    world, monkeypatch
):
    async def scenario(p):
        ids, _ = await _case_world(p)
        await p.add_account(
            "anuja@x.test", "Anuja Sinkar", "admin", ["alpha"], "active", GOOD
        )
        org = (await p.sql("SELECT id FROM orgs", db_name="alpha"))[0]["id"]
        tenant = (
            await p.sql(
                "INSERT INTO roles (org_id, name) VALUES ($1, 'tenant') RETURNING id",
                org,
                db_name="alpha",
            )
        )[0]["id"]
        base = "/admin/alpha/api/v2"
        async with p.client() as a:
            await p.sign_in(a, "anuja@x.test")
            r = await a.patch(
                f"{base}/people/{ids['Tina Rao']}", json={"role_id": str(tenant)}
            )
            assert r.status_code == 200, r.text
            r = await a.patch(
                f"{base}/people/{ids['Tina Rao']}", json={"is_active": False}
            )
            assert (
                r.status_code == 403
                and "switch a person on or off" in r.json()["detail"]
            )
            r = await a.patch(
                f"{base}/people/{ids['Anuja Sinkar']}", json={"role_id": str(tenant)}
            )
            assert r.status_code == 403 and "your own role" in r.json()["detail"]
        events = await p.sql(
            "SELECT actor_label, summary FROM admin_events", db_name="alpha"
        )
        assert [(e["actor_label"], e["summary"]) for e in events] == [
            ("dashboard · Anuja Sinkar", "Tina Rao: role admin → tenant")
        ]

    run(world, monkeypatch, scenario)
