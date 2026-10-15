"""The Message templates screen (app/admin_panel/whatsapp_templates.py) and its Meta client (app/services/template_admin.py).

Meta is never reached: every test replaces the one thin function the templates client talks through (`template_admin.call`), and
`flow_admin._call` (what that function forwards to) is made to fail the test if anything gets past. The endpoint tests run on a
throwaway copy of the Godrej schema with core-0025 applied."""

import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.admin_panel import access_rules, common, whatsapp_templates
from app.admin_panel.common import Ctx
from app.services import flow_admin, reach, template_admin
from app.services.template_admin import TemplateError
from tests.qa.harness import needs_qa, qa_run

MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "core"
    / "core-0025_whatsapp_template_drafts.sql"
)
ACCOUNT = "1234567890123"
SpecBody = whatsapp_templates.SpecBody


class FakeMeta:
    """A tiny stand-in for Meta's message-template list. Records every call."""

    def __init__(self, monkeypatch):
        self.calls: list[tuple] = []
        self.items: list[dict] = []
        monkeypatch.setattr(template_admin, "call", self.call)

        async def never(*a, **k):
            raise AssertionError("a real call to Meta was attempted")

        monkeypatch.setattr(flow_admin, "_call", never)

    async def call(self, method, path, **kw):
        self.calls.append((method, path, kw))
        if method == "GET":
            return {"data": list(self.items)}
        if method == "POST":
            payload = kw["json"]
            self.items.append(
                {
                    "id": str(200000 + len(self.items)),
                    "status": "PENDING",
                    "rejected_reason": "NONE",
                    **payload,
                }
            )
            return {
                "id": self.items[-1]["id"],
                "status": "PENDING",
                "category": payload["category"],
            }
        if method == "DELETE":
            name = kw["params"]["name"]
            self.items = [t for t in self.items if t["name"] != name]
            return {"success": True}
        raise AssertionError(method)


def approved(name, body, *, language="en", status="APPROVED", **more):
    return {
        "id": "99" + str(sum(map(ord, name))),
        "name": name,
        "language": language,
        "status": status,
        "category": "UTILITY",
        "rejected_reason": "NONE",
        "components": [{"type": "BODY", "text": body}],
        **more,
    }


GOOD = {
    "name": "Ticket update",
    "language": "en",
    "category": "UTILITY",
    "header": {"text": "Update on {{1}}", "example": "CS-12"},
    "body": "Hello {{1}}, your ticket {{2}} is now {{3}}. Reply if you need help.",
    "examples": ["Asha", "CS-12", "closed"],
    "labels": ["customer name", "ticket", "status"],
    "footer": "Thank you",
    "buttons": [
        {
            "kind": "url",
            "text": "Track it",
            "url": "https://x.example/t/{{1}}",
            "example": "CS-12",
        },
        {"kind": "quick_reply", "text": "Got it"},
    ],
}


# ─────────────────────────── the Meta client, no database ───────────────────────────


def test_a_good_template_becomes_the_payload_meta_expects():
    p = template_admin.build_payload(GOOD)
    assert p["name"] == "ticket_update"
    assert p["language"] == "en" and p["category"] == "UTILITY"
    assert [c["type"] for c in p["components"]] == [
        "HEADER",
        "BODY",
        "FOOTER",
        "BUTTONS",
    ]
    assert p["components"][0] == {
        "type": "HEADER",
        "format": "TEXT",
        "text": "Update on {{1}}",
        "example": {"header_text": ["CS-12"]},
    }
    assert p["components"][1]["example"] == {"body_text": [["Asha", "CS-12", "closed"]]}
    assert p["components"][3]["buttons"] == [
        {
            "type": "URL",
            "text": "Track it",
            "url": "https://x.example/t/{{1}}",
            "example": ["https://x.example/t/CS-12"],
        },
        {"type": "QUICK_REPLY", "text": "Got it"},
    ]


def test_slug_makes_a_name_meta_accepts():
    assert template_admin.slug("  24-hour Reminder! ") == "24_hour_reminder"
    assert template_admin.slug("Ticket update") == "ticket_update"


@pytest.mark.parametrize(
    ("change", "words"),
    [
        ({"name": "  "}, "name"),
        ({"language": "english"}, "language"),
        ({"category": "SPAM"}, "kind"),
        ({"body": ""}, "body"),
        ({"body": "x" * 1025, "examples": []}, "1024"),
        ({"body": "{{1}} is here", "examples": ["a"]}, "start or end"),
        ({"body": "Your {{2}} is here today", "examples": ["a"]}, "numbered"),
        ({"examples": ["Asha", "", "closed"]}, "example"),
        ({"footer": "Hi {{1}}"}, "small print"),
        ({"header": {"text": "A {{1}} and {{2}}", "example": "x"}}, "one blank"),
        ({"buttons": [{"kind": "url", "text": "Go", "url": "ftp://x"}]}, "https"),
        (
            {"buttons": [{"kind": "phone", "text": "Call", "phone": "12"}]},
            "country code",
        ),
        ({"buttons": [{"kind": "quick_reply", "text": "y" * 26}]}, "25"),
        (
            {"buttons": [{"kind": "url", "text": "a", "url": "https://a.example"}] * 3},
            "2 link",
        ),
        (
            {
                "buttons": [
                    {"kind": "quick_reply", "text": "a"},
                    {"kind": "url", "text": "b", "url": "https://b.example"},
                    {"kind": "quick_reply", "text": "c"},
                ]
            },
            "together",
        ),
    ],
)
def test_a_template_that_meta_would_refuse_is_stopped_here_in_plain_words(
    change, words
):
    with pytest.raises(TemplateError) as e:
        template_admin.build_payload({**GOOD, **change})
    assert words.lower() in str(e.value).lower()


def test_an_authentication_template_sends_only_what_meta_lets_us_write():
    p = template_admin.build_payload(
        {"name": "login code", "category": "AUTHENTICATION", "body": "ignored"}
    )
    assert p["components"] == [
        {"type": "BODY", "add_security_recommendation": True},
        {
            "type": "BUTTONS",
            "buttons": [{"type": "OTP", "otp_type": "COPY_CODE", "text": "Copy code"}],
        },
    ]


def test_meta_s_answer_is_turned_back_into_the_plain_form_and_odd_parts_are_named():
    spec = template_admin.to_spec(
        {
            "id": "55",
            "name": "promo",
            "language": "en_US",
            "status": "REJECTED",
            "category": "MARKETING",
            "rejected_reason": "INVALID_FORMAT",
            "components": [
                {"type": "HEADER", "format": "IMAGE"},
                {
                    "type": "BODY",
                    "text": "Hi {{1}}",
                    "example": {"body_text": [["Asha"]]},
                },
                {
                    "type": "BUTTONS",
                    "buttons": [
                        {
                            "type": "URL",
                            "text": "Open",
                            "url": "https://x.example/{{1}}",
                            "example": ["https://x.example/abc"],
                        },
                        {"type": "COPY_CODE", "text": "Copy"},
                    ],
                },
            ],
        }
    )
    assert spec["reason"] == "INVALID_FORMAT" and spec["status"] == "REJECTED"
    assert spec["examples"] == ["Asha"] and spec["header"] is None
    assert spec["buttons"] == [
        {
            "kind": "url",
            "text": "Open",
            "url": "https://x.example/{{1}}",
            "example": "abc",
        }
    ]
    assert spec["extras"] == ["a image headline", "a “Copy” button"]


def test_a_rejected_reason_of_none_is_no_reason():
    assert (
        template_admin.to_spec({"name": "a", "rejected_reason": "NONE"})["reason"] == ""
    )


def test_listing_and_deleting_use_the_one_door_to_meta(monkeypatch):
    import asyncio

    meta = FakeMeta(monkeypatch)
    meta.items = [approved("hello", "Hi there")]
    got = asyncio.run(template_admin.list_templates(ACCOUNT))
    assert [t["name"] for t in got] == ["hello"]
    asyncio.run(template_admin.remove(ACCOUNT, "hello", "77"))
    assert meta.calls[0][:2] == ("GET", f"{ACCOUNT}/message_templates")
    assert meta.calls[1] == (
        "DELETE",
        f"{ACCOUNT}/message_templates",
        {"params": {"name": "hello", "hsm_id": "77"}},
    )


def test_the_real_meta_function_is_never_reached_in_these_tests(monkeypatch):
    import asyncio

    FakeMeta(monkeypatch)
    with pytest.raises(AssertionError, match="real call"):
        asyncio.run(flow_admin._call("GET", "x"))


def test_calls_and_rules_are_super_admin_only():
    new = {
        ("GET", "/whatsapp-templates"),
        ("POST", "/whatsapp-templates"),
        ("DELETE", "/whatsapp-templates/{name}"),
        ("POST", "/whatsapp-templates/drafts"),
        ("DELETE", "/whatsapp-templates/drafts/{draft_id}"),
        ("PUT", "/whatsapp-templates/reminder"),
    }
    assert new <= access_rules.SUPER_CALLS and not (new & access_rules.ADMIN_CALLS)
    paths = {
        (m, r.path[len(access_rules.PREFIX) :])
        for r in whatsapp_templates.router.routes
        for m in r.methods
    }
    assert paths == new


# ─────────────────────────── the screen, on a throwaway database ───────────────────────────


async def start(w) -> Ctx:
    await w.pools["housing"].execute(MIGRATION.read_text(encoding="utf-8"))
    await w.pools["housing"].execute(
        MIGRATION.read_text(encoding="utf-8")
    )  # safe to run twice
    await set_account(w)
    common._caps_cache.clear()
    return await fresh(w)


async def set_account(w):
    await w.run(
        "UPDATE orgs SET settings = COALESCE(settings, '{}'::jsonb) || $2::jsonb WHERE id = $1",
        w.ids.org_id,
        json.dumps({"whatsapp_flows": {"waba_id": ACCOUNT}}),
    )


async def fresh(w) -> Ctx:
    row = await w.one("SELECT settings FROM orgs WHERE id = $1", w.ids.org_id)
    return Ctx(
        source_key=w.key,
        org_id=w.ids.org_id,
        org_name=w.ids.org_name,
        caps=await common.get_caps(w.key),
        actor="test",
        closed_values=["closed"],
        settings=json.loads(row["settings"]),
    )


async def refused(coro) -> HTTPException:
    try:
        await coro
    except HTTPException as e:
        return e
    raise AssertionError("expected the request to be refused")


@needs_qa
def test_write_send_wait_get_approved_then_use_for_the_24_hour_reminder(monkeypatch):
    meta = FakeMeta(monkeypatch)
    use = whatsapp_templates.use_for_reminder
    Reminder = whatsapp_templates.ReminderBody

    async def scenario(w):
        ctx = await start(w)
        assert ctx.caps["template_drafts"]
        empty = await whatsapp_templates.list_templates(ctx)
        assert empty["account_known"] and empty["templates"] == []
        assert empty["reminder"] is None

        # a half-written template is kept as a draft
        await whatsapp_templates.save_draft(ctx, SpecBody(**{**GOOD, "body": ""}))
        [draft] = (await whatsapp_templates.list_templates(ctx))["templates"]
        assert draft["status"] == "DRAFT" and draft["source"] == "draft"
        assert draft["name"] == "ticket_update"

        # a wrong template never reaches Meta
        e = await refused(
            whatsapp_templates.send_for_approval(ctx, SpecBody(**{**GOOD, "body": ""}))
        )
        assert e.status_code == 400 and "body" in e.detail
        assert not [c for c in meta.calls if c[0] != "GET"]

        # sending it
        sent = await whatsapp_templates.send_for_approval(ctx, SpecBody(**GOOD))
        assert sent["status"] == "PENDING" and sent["name"] == "ticket_update"
        [post] = [c for c in meta.calls if c[0] == "POST"]
        assert post[1] == f"{ACCOUNT}/message_templates"
        assert post[2]["json"]["name"] == "ticket_update"

        # listed once, from Meta's side, with the labels we kept
        [one] = (await whatsapp_templates.list_templates(ctx))["templates"]
        assert one["source"] == "meta" and one["status"] == "PENDING"
        assert one["labels"] == ["customer name", "ticket", "status"]
        assert not one["can_remind"]

        # Meta approves it: it has blanks, so it cannot be the 24-hour reminder
        meta.items[0]["status"] = "APPROVED"
        e = await refused(use(ctx, Reminder(name="ticket_update")))
        assert "blanks" in e.detail

        # a template without blanks can
        meta.items.append(approved("session_active", "Tap to open the chat again."))
        got = await whatsapp_templates.list_templates(ctx)
        by = {t["name"]: t for t in got["templates"]}
        assert by["session_active"]["can_remind"]
        assert not by["ticket_update"]["can_remind"]
        await use(ctx, Reminder(name="session_active"))
        ctx = await fresh(w)
        assert reach.template_of(ctx.settings) == ("session_active", "en")
        assert (
            ctx.settings["whatsapp_flows"]["waba_id"] == ACCOUNT
        )  # nothing else changed
        got = await whatsapp_templates.list_templates(ctx)
        assert {t["name"]: t["reminder"] for t in got["templates"]} == {
            "ticket_update": False,
            "session_active": True,
        }

        # the one in use cannot be deleted; others can, and their rows go
        e = await refused(whatsapp_templates.delete_template(ctx, "session_active"))
        assert "24-hour" in e.detail
        await whatsapp_templates.delete_template(
            ctx, "ticket_update", template_id="200000"
        )
        assert [t["name"] for t in meta.items] == ["session_active"]
        n = await w.one("SELECT count(*) AS n FROM whatsapp_template_drafts")
        assert n["n"] == 0

        await use(ctx, Reminder(name=None))
        assert reach.template_of((await fresh(w)).settings) is None

    qa_run(scenario)


@needs_qa
def test_only_an_approved_template_can_be_the_reminder_and_drafts_can_be_dropped(
    monkeypatch,
):
    meta = FakeMeta(monkeypatch)
    use = whatsapp_templates.use_for_reminder

    async def scenario(w):
        ctx = await start(w)
        meta.items = [
            approved("waiting", "Hi", status="PENDING"),
            approved("nobody", "Hi"),
        ]
        e = await refused(use(ctx, whatsapp_templates.ReminderBody(name="waiting")))
        assert "approved" in e.detail
        e = await refused(use(ctx, whatsapp_templates.ReminderBody(name="missing")))
        assert "no template" in e.detail
        await whatsapp_templates.save_draft(ctx, SpecBody(name="Later", body="x"))
        listed = (await whatsapp_templates.list_templates(ctx))["templates"]
        [d] = [t for t in listed if t["source"] == "draft"]
        await whatsapp_templates.delete_draft(ctx, d["draft_id"])
        listed = (await whatsapp_templates.list_templates(ctx))["templates"]
        assert all(t["source"] == "meta" for t in listed)
        e = await refused(whatsapp_templates.delete_draft(ctx, "nope"))
        assert e.status_code == 400
        assert not any(c[0] in ("POST", "DELETE") for c in meta.calls)

    qa_run(scenario)


@needs_qa
def test_without_the_drafts_table_the_screen_still_lists_and_sends(monkeypatch):
    meta = FakeMeta(monkeypatch)

    async def scenario(w):
        await set_account(w)
        common._caps_cache.clear()
        ctx = await fresh(w)
        assert not ctx.caps["template_drafts"]
        got = await whatsapp_templates.list_templates(ctx)
        assert got["drafts_available"] is False
        await whatsapp_templates.send_for_approval(ctx, SpecBody(**GOOD))
        assert len(meta.items) == 1
        e = await refused(whatsapp_templates.save_draft(ctx, SpecBody(**GOOD)))
        assert e.status_code == 409 and "core-0025" in e.detail

    qa_run(scenario)


@needs_qa
def test_an_organisation_with_no_business_account_number_is_asked_for_it(monkeypatch):
    FakeMeta(monkeypatch)
    monkeypatch.delenv("WHATSAPP_WABA_ID", raising=False)
    monkeypatch.setattr(flow_admin.whatsapp, "WHATSAPP_PHONE_ID", "")

    async def scenario(w):
        common._caps_cache.clear()
        ctx = await fresh(w)
        got = await whatsapp_templates.list_templates(ctx)
        assert got["account_known"] is False and got["templates"] == []
        e = await refused(whatsapp_templates.send_for_approval(ctx, SpecBody(**GOOD)))
        assert "business account" in e.detail

    qa_run(scenario)
