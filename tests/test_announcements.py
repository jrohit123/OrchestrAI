"""Announcements: who a set of ticks reaches (relation, primary member, lives here, wing, role), how each person is
reached (WhatsApp now, WhatsApp kept until they open it, Telegram, email, nobody), that nobody gets one twice, and that
WhatsApp's reports (delivered, read, a tap on Got it, a late delivery) move a person forward and never back. Nothing is
sent anywhere: the senders are replaced. The tests need a throwaway database on this computer (MIGRATE_TEST_PG)."""

import json

import pytest
from fastapi import HTTPException

from app.admin_panel import announcements as panel
from app.services import announcements as ann
from tests.test_migrate import needs_pg
from tests.test_panel_roles import ORG, SCHEMA, ctx, run
from tests.test_people_import import MIGRATION, RESIDENTS

MIGRATION_17 = MIGRATION.with_name("housing-0017_announcements.sql")
ALL = ["owner", "co_owner", "owner_family", "tenant", "tenant_family"]


def test_ticks_are_checked_in_words():
    with pytest.raises(ValueError, match="Lives here"):
        ann.clean_filters({"lives": [], "relations": ALL})
    with pytest.raises(ValueError, match="relation"):
        ann.clean_filters({"lives": ["here"], "relations": []})
    with pytest.raises(ValueError, match="role"):
        ann.clean_filters({"by_flat": False, "roles": []})
    f = ann.clean_filters(
        {
            "lives": ["here", "nonsense"],
            "relations": ["tenant"],
            "primary": "odd",
            "wings": [" b ", "a"],
        }
    )
    assert f == {
        "by_flat": True,
        "lives": ["here"],
        "relations": ["tenant"],
        "primary": "any",
        "wings": ["A", "B"],
        "roles": [],
    }


def test_how_a_person_is_reached():
    assert ann.channel_of("tg:123", None) == "telegram"
    assert ann.channel_of("+919000000001", "a@b.c") == "whatsapp"
    assert ann.channel_of(None, "a@b.c") == "email"
    assert ann.channel_of(None, "") == "none"


class FakeRedis:
    def __init__(self):
        self.data = {}

    async def get(self, k):
        return self.data.get(k)

    async def set(self, k, v, ex=None, nx=False):
        self.data[k] = v
        return True

    async def mget(self, keys):
        return [self.data.get(k) for k in keys]


async def _world(conn):
    await conn.execute(SCHEMA)
    await conn.execute(
        RESIDENTS.replace(
            "CREATE TABLE IF NOT EXISTS orgs (id uuid PRIMARY KEY, settings jsonb);",
            "CREATE TABLE IF NOT EXISTS orgs (id uuid PRIMARY KEY, name text, settings jsonb);",
        )
    )
    await conn.execute(
        "INSERT INTO orgs (id, name, settings) VALUES ($1, 'Test Society', '{}'::jsonb)",
        ORG,
    )
    await conn.execute(MIGRATION.read_text(encoding="utf-8"))
    await conn.execute(MIGRATION_17.read_text(encoding="utf-8"))
    roles = {
        n: await conn.fetchval(
            "INSERT INTO roles (org_id, name) VALUES ($1, $2) RETURNING id", ORG, n
        )
        for n in ("owner", "tenant", "committee")
    }
    ids = {}
    for name, phone, email, role, active in (
        (
            "Anil",
            "+919000000001",
            "anil@example.test",
            "committee",
            True,
        ),  # owner A-1 (primary, lives here) and B-1 (primary, away)
        ("Lata", "+919000000002", None, "owner", True),  # co-owner A-1, lives here
        ("Farah", "tg:555", None, "tenant", True),  # tenant B-1, lives here
        (
            "Meena",
            None,
            "meena@example.test",
            "owner",
            True,
        ),  # owner C-1, primary, abroad
        ("Ghost", None, None, "tenant", True),  # tenant C-1, no way to reach
        ("Gone", "+919000000009", None, "owner", False),  # switched off
    ):
        ids[name] = await conn.fetchval(
            "INSERT INTO users (org_id, role_id, name, phone, email, is_active) VALUES ($1, $2, $3, $4, $5, $6) RETURNING id",
            ORG, roles[role], name, phone, email, active,
        )  # fmt: skip
    for who, wing, flat, rel, prim, lives in (
        ("Anil", "A", "1", "owner", True, True),
        ("Anil", "B", "1", "owner", True, False),
        ("Lata", "A", "1", "co_owner", False, True),
        ("Farah", "B", "1", "tenant", False, True),
        ("Meena", "C", "1", "owner", True, False),
        ("Ghost", "C", "1", "tenant", False, True),
        ("Gone", "A", "2", "owner", True, True),
    ):
        await conn.execute(
            "INSERT INTO residents (org_id, user_id, wing, flat_no, relation, is_primary, lives_here) VALUES ($1, $2, $3, $4, $5, $6, $7)",
            ORG, ids[who], wing, flat, rel, prim, lives,
        )  # fmt: skip
    return roles, ids


def _ctx():
    c = ctx()
    c.caps.update({"residents": True, "flat_people": True, "announcements": True})
    c.settings = {"labels": {"co_owner": "Co-owner"}}
    return c


async def _names(filters):
    return [p["name"] for p in await ann.audience("alpha", ORG, filters)]


@needs_pg
def test_the_ticks_reach_the_right_people(world):
    async def work(conn):
        roles, _ = await _world(conn)
        f = lambda **kw: {
            "lives": ["here"],
            "relations": ALL,
            "primary": "any",
            "wings": [],
            "roles": [],
            **kw,
        }
        assert await _names(f()) == [
            "Anil",
            "Farah",
            "Ghost",
            "Lata",
        ]  # Gone is switched off
        assert await _names(f(lives=["here", "away"], primary="only")) == [
            "Anil",
            "Meena",
        ]  # the AGM minutes
        assert await _names(f(relations=["tenant"])) == ["Farah", "Ghost"]
        assert await _names(
            f(relations=["owner", "co_owner", "owner_family"], primary="not")
        ) == ["Lata"]
        assert await _names(f(wings=["B"])) == [
            "Farah"
        ]  # Anil lives in A-1, not in B-1
        assert await _names(f(roles=[str(roles["committee"])])) == ["Anil"]
        assert await _names({"by_flat": False, "roles": [str(roles["tenant"])]}) == [
            "Farah",
            "Ghost",
        ]
        everyone = await ann.audience("alpha", ORG, f(lives=["here", "away"]))
        assert [p["flats"] for p in everyone if p["name"] == "Anil"] == [
            "A-1, B-1"
        ]  # two flats, once
        await conn.execute(
            "UPDATE residents SET status = 'suspended' WHERE flat_no = '1' AND wing = 'C' AND relation = 'tenant'"
        )
        assert "Ghost" not in await _names(f())
        out = await panel.preview(
            _ctx(), panel.PreviewBody(filters=f(relations=["tenant"]))
        )
        assert out["words"] == "People who live here, who are Tenant, in all wings."
        assert {x["name"]: x["why"] for x in out["left_out"]} == {
            "Anil": "relation not ticked",
            "Lata": "relation not ticked",
            "Meena": "lives elsewhere",
        }
        assert out["counts"] == {"telegram": 1}
        with pytest.raises(HTTPException):
            await panel.preview(_ctx(), panel.PreviewBody(filters=f(lives=[])))

    run(world, work)


@needs_pg
def test_sending_reaches_each_person_their_own_way_and_only_once(world, monkeypatch):
    sent, mails, kept = [], [], []

    async def deliver_text(to, text, **kw):
        if to == "+919000000002":  # Lata has not written in 24 hours
            kept.append((to, kw.get("track")))
            return {"status": "held", "emailed": False, "note": None}
        sent.append((to, text))
        return {"status": "sent", "answer": {"messages": [{"id": "wamid.A"}]}}

    async def door_open(*a, **k):
        return True

    async def send_text(to, text):
        sent.append((to, text))
        return {}

    async def send_email(to, name, subject, text, html=None):
        mails.append((to, subject, text))
        return True

    async def settings(*a):
        return {}

    redis = FakeRedis()
    monkeypatch.setattr(ann.reach, "deliver_text", deliver_text)
    monkeypatch.setattr(ann.reach, "door_open", door_open)
    monkeypatch.setattr(ann.messaging, "send_text", send_text)
    monkeypatch.setattr(ann.mailer, "send_email", send_email)
    monkeypatch.setattr(ann.config_store, "org_settings", settings)
    monkeypatch.setattr(ann, "get_redis", lambda: redis)
    monkeypatch.setattr(ann, "start_now", lambda *a: None)
    monkeypatch.setattr(ann, "get_all_source_keys", _keys)

    async def work(conn):
        await _world(conn)
        c = _ctx()
        r = await panel.create(c, panel.NewAnnouncement(
            title="Flag hoisting", body="Starts in *15 minutes* at the lawn.",
            filters={"lives": ["here", "away"], "relations": ALL, "primary": "any", "wings": [], "roles": []},
        ))  # fmt: skip
        assert r["people"] == 5
        assert await ann.run_due() == 5
        assert await ann.run_due() == 0  # nobody twice
        rows = {
            x["name"]: dict(x)
            for x in await conn.fetch("SELECT * FROM announcement_recipients")
        }
        assert {n: (x["channel"], x["status"]) for n, x in rows.items()} == {
            "Anil": ("whatsapp", "sent"),
            "Lata": ("whatsapp", "kept"),
            "Farah": ("telegram", "sent"),
            "Meena": ("email", "emailed"),
            "Ghost": ("none", "failed"),
        }
        assert rows["Anil"]["wamid"] == "wamid.A"
        assert await conn.fetchval("SELECT status FROM announcements") == "sent"
        text = dict(sent)["tg:555"]
        assert text.startswith(
            "Dear Farah,\n\n*Flag hoisting*\n\nStarts in *15 minutes* at the lawn."
        )
        assert text.endswith("— Test Society committee")
        assert (
            mails[0][0] == "meena@example.test"
            and mails[0][1] == "📢 Flag hoisting · Test Society"
        )
        # what WhatsApp says afterwards moves Anil forward, never back
        report = lambda s: {
            "entry": [
                {"changes": [{"value": {"statuses": [{"id": "wamid.A", "status": s}]}}]}
            ]
        }
        await ann.on_reports(report("read"))
        await ann.on_reports(report("delivered"))
        assert (
            await conn.fetchval(
                "SELECT status FROM announcement_recipients WHERE name = 'Anil'"
            )
            == "read"
        )
        await ann.on_got_it("wamid.A")
        assert (
            await conn.fetchval(
                "SELECT status FROM announcement_recipients WHERE name = 'Anil'"
            )
            == "got_it"
        )
        # Lata opens her WhatsApp: what was kept is sent
        await ann.delivered_later(kept[0][1], {"messages": [{"id": "wamid.L"}]})
        lata = await conn.fetchrow(
            "SELECT status, wamid FROM announcement_recipients WHERE name = 'Lata'"
        )
        assert (lata["status"], lata["wamid"]) == ("sent", "wamid.L")
        assert json.loads(redis.data["ann:wamid.L"])["r"] == str(rows["Lata"]["id"])
        d = await panel.one(c, r["id"])
        assert d["counts"]["got_it"] == 1 and d["counts"]["failed"] == 1

    run(world, work)


async def _keys():
    return ["alpha"]


@needs_pg
def test_a_planned_announcement_waits_and_can_be_cancelled_or_sent_now(
    world, monkeypatch
):
    import datetime as dt

    monkeypatch.setattr(ann, "start_now", lambda *a: None)
    monkeypatch.setattr(ann, "get_all_source_keys", _keys)

    async def work(conn):
        await _world(conn)
        c = _ctx()
        later = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=2)
        f = {
            "lives": ["here"],
            "relations": ["tenant"],
            "primary": "any",
            "wings": [],
            "roles": [],
        }
        r = await panel.create(
            c,
            panel.NewAnnouncement(body="Water cut tomorrow", filters=f, send_at=later),
        )
        assert await ann.run_due() == 0
        assert (
            await conn.fetchval("SELECT count(*) FROM announcement_recipients") == 0
        )  # worked out when it goes
        await panel.cancel(c, r["id"])
        with pytest.raises(HTTPException):
            await panel.send_now(c, r["id"])
        with pytest.raises(HTTPException, match="already passed"):
            await panel.create(
                c,
                panel.NewAnnouncement(
                    body="x", filters=f, send_at=later - dt.timedelta(days=1)
                ),
            )
        with pytest.raises(HTTPException, match="Nobody matches"):
            await panel.create(
                c, panel.NewAnnouncement(body="x", filters={**f, "wings": ["Z"]})
            )
        listed = await panel.list_announcements(c)
        assert listed["rows"][0]["status"] == "cancelled"
        # ready choices are data: five come with the migration, more can be kept and removed
        setup = await panel.setup(c)
        assert [a["name"] for a in setup["audiences"]][:2] == [
            "Everyone who lives here",
            "AGM: primary members",
        ]
        new = await panel.add_audience(
            c, panel.AudienceNew(name="Tenants of B", filters={**f, "wings": ["B"]})
        )
        with pytest.raises(HTTPException):
            await panel.add_audience(
                c, panel.AudienceNew(name="tenants of b", filters=f)
            )
        await panel.remove_audience(c, new["id"])
        assert len((await panel.setup(c))["audiences"]) == 5

    run(world, work)
