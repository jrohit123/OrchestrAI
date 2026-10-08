"""Catalogue groups A (Telegram part), B (identity and onboarding), and G19. End to end on throwaway databases.

A case that fails today is `xfail(strict=True)` tagged with its bug ID; each has a control test beside it.
"""

import asyncio
import json
import logging
import random
import re
from types import SimpleNamespace

import asyncpg
import httpx
import pytest
from fastapi import HTTPException
from hypothesis import given, settings
from hypothesis import strategies as st

from app.services import otp_service
from tests.qa.harness import _patch, needs_qa, qa_run
from tests.qa.qa_helpers import phone_of

# captured before any test world replaces it with the capturing fake
ORIGINAL_BREVO_SENDER = otp_service._send_brevo_email


def bug(ident: str, why: str = ""):
    return pytest.mark.xfail(strict=True, reason=f"{ident} {why}".strip())


async def send_code(w, who: str = "member") -> tuple[dict, dict]:
    """Ask for a code for a seeded person; returns (that person, the result of the request)."""
    user = await w.user(who)
    result = await otp_service.generate_and_send_otp(
        user["user_id"],
        user["email"],
        user["user_name"],
        user["org_name"],
        user["org_id"],
        {"description": "a test"},
        user["source_key"],
    )
    return user, result


# ───────────────────────────── B. phone numbers ─────────────────────────────


def test_B01_admin_typed_phone_numbers_are_kept_in_one_format():
    from app.admin_panel.people import clean_phone

    assert clean_phone("+91 98765 43210") == "+919876543210"
    assert clean_phone("0091 98765 43210") == "+919876543210"
    assert clean_phone("(+91) 98765-43210") == "+919876543210"
    for bad in ("098765 43210", "98765", "abc", "+91 98765 4321 0000 0000"):
        with pytest.raises(HTTPException):
            clean_phone(bad)


@settings(max_examples=200, deadline=None)
@given(st.from_regex(r"\+?[0-9][0-9 ()\-]{6,18}", fullmatch=True))
def test_B_property_a_phone_that_is_accepted_is_plus_and_8_to_15_digits(raw):
    from app.admin_panel.people import clean_phone

    try:
        out = clean_phone(raw)
    except HTTPException:
        return
    assert out.startswith("+") and out[1:].isdigit() and 8 <= len(out) - 1 <= 15


@needs_qa
def test_B01b_a_whatsapp_number_arriving_without_a_plus_finds_the_person():
    async def scenario(w):
        await w.login("admin")
        response = await w.wa_post(w.wa_payload("919000000001", "/status"))
        assert response.status_code == 200
        assert w.texts_to("+919000000001"), "the person was not recognised"

    qa_run(scenario)


# ───────────────────────────── B. linking and self-registration on Telegram ─────────────────────────────


@needs_qa
def test_B06_control_an_added_person_links_their_telegram_chat_with_their_email_and_a_code():
    async def scenario(w):
        chat = "tg:556"
        await w.say(chat, "neha@example.test")
        code = w.last_otp("neha@example.test")
        assert code, "no code was sent to the e-mail address"
        await w.say(chat, code)
        row = await w.one("SELECT phone FROM users WHERE email = 'neha@example.test'")
        assert row["phone"] == chat

    qa_run(scenario)


async def register_as(
    w, chat: str, email: str, name: str, role_number: str
) -> dict | None:
    """A stranger on Telegram: email, name, a role from the list, yes, then the code from the e-mail."""
    await w.say(chat, email)
    await w.say(chat, name)
    await w.say(chat, role_number)
    await w.say(chat, "yes")
    code = w.last_otp(email)
    if code:
        await w.say(chat, code)
    row = await w.one(
        "SELECT r.name AS role, u.is_active, u.phone FROM users u JOIN roles r ON r.id = u.role_id WHERE lower(u.email) = $1",
        email.lower(),
    )
    return dict(row) if row else None


async def allow_self_registration(w, roles):
    """The organisation's own list of roles a stranger may take (orgs.settings -> self_registration.roles)."""
    await w.run(
        "UPDATE orgs SET settings = settings || $1::jsonb",
        json.dumps({"self_registration": {"roles": roles}}),
    )


@needs_qa
def test_B_control_a_stranger_can_register_as_a_member():
    async def scenario(w):
        await allow_self_registration(w, ["member"])
        row = await register_as(
            w, "tg:555", "carol@example.test", "Carol Newcomer", "1"
        )
        assert row and row["role"] == "member" and row["phone"] == "tg:555", row

    qa_run(scenario)


@needs_qa
def test_B03_a_stranger_on_telegram_cannot_register_themselves_as_admin():
    async def scenario(w):
        await allow_self_registration(w, ["member", "staff"])
        # the first role on the list is what "1" picks: admin is not on it, so it is not even offered
        row = await register_as(
            w, "tg:555", "mallory@example.test", "Mallory Stranger", "1"
        )
        assert row is None or row["role"] != "admin", (
            f"a stranger now holds the role {row['role']!r}"
        )
        offered = "\n".join(w.texts_to("tg:555")).lower()
        assert not re.search(r"(?m)^\s*\d+\.\s*admin", offered), offered

    qa_run(scenario)


@needs_qa
def test_B03b_with_no_list_of_roles_nobody_can_register_themselves():
    async def scenario(w):
        await w.say("tg:555", "dave@example.test")
        said = " ".join(w.texts_to("tg:555")).lower()
        assert "not open" in said and "ask your admin" in said, said
        assert not await w.one(
            "SELECT 1 AS x FROM users WHERE lower(email) = 'dave@example.test'"
        )
        # and she is not left half way through a sign-up: the next message does not ask for a name
        before = len(w.texts_to("tg:555"))
        await w.say("tg:555", "Dave Stranger")
        assert not await w.one("SELECT 1 AS x FROM users WHERE name = 'Dave Stranger'")
        assert len(w.texts_to("tg:555")) > before

    qa_run(scenario)


@needs_qa
def test_B03c_a_role_that_is_not_on_the_list_cannot_be_taken_even_from_an_old_or_forged_chat():
    async def scenario(w):
        from app.redis_client import set_session

        await allow_self_registration(w, ["member"])
        # a chat state that says "admin" (the list changed meanwhile, or the state was tampered with)
        await set_session(
            "tglink:tg:555",
            {
                "state": "awaiting_new_user_confirm",
                "name": "Mallory Stranger",
                "new_user_email": "mallory@example.test",
                "role_id": str(w.ids.role["admin"]),
                "role_name": "admin",
                "role_options": [{"id": str(w.ids.role["admin"]), "name": "admin"}],
            },
            ttl=300,
        )
        await w.say("tg:555", "yes")
        assert not await w.one(
            "SELECT 1 AS x FROM users WHERE lower(email) = 'mallory@example.test'"
        ), "the account was made"

    qa_run(scenario)


@needs_qa
def test_B03d_the_list_of_roles_is_read_safely_whatever_was_typed_into_the_setting():
    async def scenario(w):
        from app.routers import webhook

        for value, expected in (
            (["Member", " staff ", "", 5, None], ["member", "staff"]),
            ("member", []),
            ({"a": 1}, []),
            (None, []),
        ):
            await w.run(
                "UPDATE orgs SET settings = jsonb_set(settings, '{self_registration}', $1::jsonb)",
                json.dumps({"roles": value}),
            )
            assert await webhook._self_registration_roles(w.key) == expected, value
        await w.run("UPDATE orgs SET settings = settings - 'self_registration'")
        assert await webhook._self_registration_roles(w.key) == []

    qa_run(scenario)


# ───────────────────────────── A. the Telegram secret ─────────────────────────────


@needs_qa
def test_A15_telegram_updates_with_a_wrong_or_missing_secret_are_refused_when_a_secret_is_configured():
    async def scenario(w):
        from app.routers import telegram_webhook

        _patch(w, telegram_webhook, "TELEGRAM_WEBHOOK_SECRET", "s3cret")
        assert (await w.tg_post(777, "/status", secret=None)).status_code == 403
        assert (await w.tg_post(777, "/status", secret="wrong")).status_code == 403
        assert (await w.tg_post(777, "/status", secret="s3cret")).status_code == 200

    qa_run(scenario)


@needs_qa
def test_A16_telegram_updates_are_refused_when_no_secret_is_configured():
    async def scenario(w):
        from app.routers import telegram_webhook

        _patch(w, telegram_webhook, "TELEGRAM_WEBHOOK_SECRET", "")
        # a person who is signed in on Telegram right now: whoever knows the chat number can speak for them
        await w.run(
            "INSERT INTO users (org_id, role_id, name, phone, email, channel) VALUES ($1, $2, 'Victim Admin', 'tg:777', 'victim@example.test', 'telegram')",
            w.ids.org_id,
            w.ids.role["admin"],
        )
        await w.login("tg:777")
        response = await w.tg_post(777, "/status")
        assert response.status_code in (401, 403, 503), (
            f"answered {response.status_code}"
        )
        assert not w.texts_to("tg:777"), (
            "a forged update was handled as the real person"
        )

    qa_run(scenario)


# ───────────────────────────── B. codes (one-time passwords) ─────────────────────────────


@needs_qa
def test_B_control_the_right_code_is_accepted_once():
    async def scenario(w):
        user, result = await send_code(w)
        assert result["sent"]
        code = w.last_otp(user["email"])
        assert (
            await otp_service.verify_otp(user["user_id"], code, user["source_key"])
        )["valid"] is True
        again = await otp_service.verify_otp(user["user_id"], code, user["source_key"])
        assert again["valid"] is False  # B12: a used code does not work a second time

    qa_run(scenario)


@needs_qa
def test_B11_an_expired_code_is_refused():
    async def scenario(w):
        user, _ = await send_code(w)
        code = w.last_otp(user["email"])
        await w.run("UPDATE otp_tokens SET expires_at = now() - interval '1 minute'")
        assert (
            await otp_service.verify_otp(user["user_id"], code, user["source_key"])
        )["valid"] is False

    qa_run(scenario)


@needs_qa
def test_B16_asking_for_a_second_code_at_once_is_held_back():
    async def scenario(w):
        _, first = await send_code(w)
        _, second = await send_code(w)
        assert first["sent"] is True
        assert second["sent"] is False and second["reason"] == "cooldown"

    qa_run(scenario)


@needs_qa
def test_B_three_wrong_codes_in_a_row_use_the_code_up():
    async def scenario(w):
        user, _ = await send_code(w)
        code = w.last_otp(user["email"])
        wrong = "0000" if code != "0000" else "1111"
        for _ in range(3):
            assert (
                await otp_service.verify_otp(user["user_id"], wrong, user["source_key"])
            )["valid"] is False
        assert (
            await otp_service.verify_otp(user["user_id"], code, user["source_key"])
        )["valid"] is False

    qa_run(scenario)


@needs_qa
@bug(
    "QA-014",
    "the attempt counter is read, then increased in a second statement, so parallel guesses all get checked",
)
def test_B13_wrong_codes_sent_at_the_same_moment_are_limited_to_the_allowed_number():
    async def scenario(w):
        user, _ = await send_code(w)
        code = w.last_otp(user["email"])
        w.slow_after(
            otp_service,
            "fetch_one",
            0.1,
            when=lambda q, *a, **k: "expires_at, attempts" in q,
        )
        guesses = [f"{n:04d}" for n in range(1, 40) if f"{n:04d}" != code][:20]
        await asyncio.gather(
            *[
                otp_service.verify_otp(user["user_id"], g, user["source_key"])
                for g in guesses
            ]
        )
        row = await w.one(
            "SELECT attempts FROM otp_tokens ORDER BY created_at DESC LIMIT 1"
        )
        assert row["attempts"] <= 3, (
            f"{row['attempts']} guesses were checked against a limit of 3"
        )

    qa_run(scenario)


@needs_qa
@bug(
    "QA-014", "the code is made with random.randint, so a known seed gives a known code"
)
def test_B14_codes_cannot_be_predicted_from_a_known_random_seed():
    async def scenario(w):
        first, _ = await send_code(w, "member")
        random.seed(1234)
        await w.run("DELETE FROM otp_tokens")
        await send_code(w, "member")
        a = w.last_otp(first["email"])
        random.seed(1234)
        await w.run("DELETE FROM otp_tokens")
        await send_code(w, "member")
        b = w.last_otp(first["email"])
        assert a != b, "the same seed produced the same code"

    qa_run(scenario)


@needs_qa
@bug(
    "QA-030",
    "the person's name and the action text are put into the e-mail's HTML without escaping",
)
def test_B17_a_name_with_html_in_it_is_escaped_in_the_code_e_mail():
    async def scenario(w):
        sent = []

        async def fake_post(self, url, **kw):
            sent.append(kw.get("json", {}))
            return SimpleNamespace(status_code=201)

        _patch(w, httpx.AsyncClient, "post", fake_post)
        await ORIGINAL_BREVO_SENDER(
            "a@example.test", "<b>Eve</b>", "1234", "<i>approve</i>", "Org", 3
        )
        html = sent[0]["htmlContent"]
        assert "<b>Eve</b>" not in html and "&lt;b&gt;" in html

    qa_run(scenario)


# ───────────────────────────── B. identity across tenants, G19 pools ─────────────────────────────


async def two_tenants_with_one_phone(w) -> str:
    """The same phone number is registered in both organisations."""
    phone = phone_of(w, "admin")
    role = await w.one("SELECT id FROM roles LIMIT 1", kind="jewellery")
    org = await w.one("SELECT id FROM orgs LIMIT 1", kind="jewellery")
    await w.run(
        "INSERT INTO users (org_id, role_id, name, phone, email, channel) VALUES ($1, $2, 'Same Phone', $3, 'same@example.test', 'whatsapp')",
        org["id"],
        role["id"],
        phone,
        kind="jewellery",
    )
    return phone


@needs_qa
@bug(
    "QA-020",
    "the first organisation the database happens to list wins; no order, no warning",
)
def test_B04_one_phone_in_two_organisations_gives_the_same_answer_whatever_the_listing_order():
    async def scenario(w):
        from app.services.identity import resolve_identity

        phone = await two_tenants_with_one_phone(w)
        first = (await resolve_identity(phone))["source_key"]
        rows = await w.routing.fetch(
            "SELECT source_key, database_url, messaging_channel FROM data_sources"
        )
        await w.routing.execute("DELETE FROM data_sources")
        for row in reversed(rows):
            await w.routing.execute(
                "INSERT INTO data_sources (source_key, database_url, messaging_channel) VALUES ($1, $2, $3)",
                row["source_key"],
                row["database_url"],
                row["messaging_channel"],
            )
        second = (await resolve_identity(phone))["source_key"]
        assert first == second, (
            f"{first} when listed one way, {second} when listed the other"
        )

    qa_run(scenario, kinds=("housing", "jewellery"))


@needs_qa
@bug(
    "QA-020",
    "a lookup that fails inside one organisation (for example a changed table) is logged only at debug level",
)
def test_B05_an_organisation_that_cannot_be_searched_is_reported_above_debug_level(
    caplog,
):
    async def scenario(w):
        from app.services.identity import resolve_identity

        await w.run("ALTER TABLE users RENAME TO users_moved", kind="jewellery")
        with caplog.at_level(logging.DEBUG):
            found = await resolve_identity(w.jewellery.phone)
        assert found is None  # today: simply "not registered"
        loud = [
            r
            for r in caplog.records
            if r.levelno >= logging.WARNING and "qa_jewellery" in r.getMessage()
        ]
        assert loud, (
            "nothing above debug level says that a whole organisation could not be searched"
        )

    qa_run(scenario, kinds=("housing", "jewellery"))


@needs_qa
def test_J05_a_telegram_chat_and_a_whatsapp_number_are_each_routed_to_their_own_organisation():
    async def scenario(w):
        from app.db import get_source_key_for_channel

        assert await get_source_key_for_channel("telegram") == w.keys["housing"]
        assert await get_source_key_for_channel("whatsapp") == w.keys["jewellery"]

    qa_run(scenario, kinds=("housing", "jewellery"))


@needs_qa
@bug(
    "QA-029",
    "two first calls for the same organisation each create a pool; one is lost and never closed",
)
def test_G19_two_first_calls_make_one_connection_pool():
    async def scenario(w):
        from app import db

        key = w.key
        saved = db._pools.pop(key)
        created = []
        original = asyncpg.create_pool

        def counting(*a, **k):
            created.append(1)
            return original(*a, **k)

        _patch(w, asyncpg, "create_pool", counting)
        pools = await asyncio.gather(*[db.get_pool(key) for _ in range(5)])
        for pool in {id(p): p for p in pools}.values():
            await pool.close()
        db._pools[key] = saved
        assert len(created) == 1, f"{len(created)} pools were made for one organisation"

    qa_run(scenario)
