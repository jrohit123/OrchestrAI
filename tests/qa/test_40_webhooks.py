"""Catalogue group A (webhook ingestion) and L01 (Redis down), end to end through the real HTTP routes.

A case that fails today is `xfail(strict=True)` tagged with its bug ID; each has a control test beside it.
"""

import asyncio
import json
import uuid

import httpx
import pytest

from tests.qa.harness import _patch, needs_qa, qa_run
from tests.qa.qa_helpers import phone_of


def bug(ident: str, why: str = ""):
    return pytest.mark.xfail(strict=True, reason=f"{ident} {why}".strip())


def tolerant_client() -> httpx.AsyncClient:
    """Like the real server: an unhandled error becomes a 500 answer instead of raising inside the test."""
    from app.main import app

    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    )


async def signed_post(w, raw: bytes, client: httpx.AsyncClient):
    return await w.wa_post(None, raw=raw, client=client)


async def register_telegram_admin(w, chat: int = 777) -> str:
    await w.run(
        "INSERT INTO users (org_id, role_id, name, phone, email, channel) VALUES ($1, $2, 'Tele Admin', $3, 'tele@example.test', 'telegram')",
        w.ids.org_id,
        w.ids.role["admin"],
        f"tg:{chat}",
    )
    await w.login(f"tg:{chat}")
    return f"tg:{chat}"


# ───────────────────────────── A. WhatsApp ─────────────────────────────


@needs_qa
def test_A_control_a_signed_message_is_answered():
    async def scenario(w):
        await w.login("admin")
        response = await w.wa_post(w.wa_payload(phone_of(w, "admin"), "/status"))
        assert response.status_code == 200
        assert w.texts_to(phone_of(w, "admin"))

    qa_run(scenario)


@needs_qa
def test_A01_a_post_with_no_signature_is_refused_and_nothing_is_handled():
    async def scenario(w):
        await w.login("admin")
        response = await w.wa_post(
            w.wa_payload(phone_of(w, "admin"), "/status"), signature=None
        )
        assert response.status_code == 403
        assert not w.texts_to(phone_of(w, "admin"))

    qa_run(scenario)


@needs_qa
def test_A02_a_post_with_a_wrong_signature_is_refused():
    async def scenario(w):
        await w.login("admin")
        response = await w.wa_post(
            w.wa_payload(phone_of(w, "admin"), "/status"),
            signature="sha256=" + "0" * 64,
        )
        assert response.status_code == 403
        assert not w.texts_to(phone_of(w, "admin"))

    qa_run(scenario)


@needs_qa
def test_A04_the_same_message_id_twice_within_five_minutes_is_handled_once():
    async def scenario(w):
        await w.login("admin")
        phone = phone_of(w, "admin")
        payload = w.wa_payload(phone, "/status", msg_id="wamid.same-one")
        await w.wa_post(payload)
        first = len(w.texts_to(phone))
        await w.wa_post(payload)
        assert first >= 1 and len(w.texts_to(phone)) == first

    qa_run(scenario)


@needs_qa
@bug("QA-013", "(f) after the 300-second window the same delivery is handled again")
def test_A05_a_delivery_repeated_after_the_five_minute_window_is_not_handled_again():
    async def scenario(w):
        from app.redis_client import get_redis

        await w.login("admin")
        phone = phone_of(w, "admin")
        payload = w.wa_payload(phone, "/status", msg_id="wamid.late-retry")
        await w.wa_post(payload)
        first = len(w.texts_to(phone))
        await get_redis().expire(
            "msg_processed:wamid.late-retry", 1
        )  # six minutes later, in effect
        await asyncio.sleep(1.2)
        await w.wa_post(payload)
        assert len(w.texts_to(phone)) == first, "the retry was processed a second time"

    qa_run(scenario)


@needs_qa
def test_A07_a_delivery_status_report_is_not_treated_as_a_message():
    async def scenario(w):
        from app.routers import webhook

        calls = []

        async def spy(**k):
            calls.append(k)

        _patch(w, webhook, "handle_message", spy)
        body = {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": "1",
                    "changes": [
                        {
                            "field": "messages",
                            "value": {"statuses": [{"id": "x", "status": "delivered"}]},
                        }
                    ],
                }
            ],
        }
        response = await w.wa_post(body)
        assert response.status_code == 200 and calls == []

    qa_run(scenario)


@needs_qa
@bug("QA-013", "(a) only the first message of a delivery is handled")
def test_A08_every_message_in_one_delivery_is_handled():
    async def scenario(w):
        await w.login("admin")
        phone = phone_of(w, "admin")
        number = phone.lstrip("+")
        messages = [
            {
                "from": number,
                "id": f"wamid.{uuid.uuid4().hex}",
                "type": "text",
                "timestamp": "1",
                "text": {"body": "/status"},
            }
            for _ in range(3)
        ]
        await w.wa_post(w.wa_payload(phone, messages=messages))
        assert len(w.texts_to(phone)) >= 3, (
            f"{len(w.texts_to(phone))} answers to 3 messages"
        )

    qa_run(scenario)


@needs_qa
@bug(
    "QA-013",
    "(c) a signed body that is not JSON raises and the server answers 500, so Meta retries",
)
def test_A09_a_signed_body_that_is_not_json_gets_a_4xx_answer():
    async def scenario(w):
        async with tolerant_client() as client:
            response = await signed_post(w, b"this is not json", client)
        assert 400 <= response.status_code < 500, response.status_code

    qa_run(scenario)


@needs_qa
@bug(
    "QA-013",
    "(c) a signed JSON list has no 'entry' and raises TypeError, outside the try block",
)
def test_A10_a_signed_json_list_gets_a_4xx_answer():
    async def scenario(w):
        async with tolerant_client() as client:
            response = await signed_post(w, json.dumps([1, 2, 3]).encode(), client)
        assert 400 <= response.status_code < 500, response.status_code

    qa_run(scenario)


@needs_qa
@bug(
    "QA-013",
    "(b) a sticker, an image, a voice note or a template button reply gets no answer at all",
)
@pytest.mark.parametrize("kind", ["sticker", "image", "audio", "button"])
def test_A12_a_message_that_is_not_plain_text_still_gets_an_answer(kind):
    async def scenario(w):
        await w.login("admin")
        phone = phone_of(w, "admin")
        extra = {kind: {"id": "media-1"}}
        if kind == "image":
            extra = {"image": {"id": "media-1", "caption": "a photo of the leak"}}
        await w.wa_post(w.wa_payload(phone, msg_type=kind, extra=extra))
        assert w.texts_to(phone), f"a {kind} message was silently dropped"

    qa_run(scenario)


@needs_qa
@bug(
    "QA-013",
    "(e) when Redis is down every webhook call fails with 500, so Meta retries and the person hears nothing",
)
def test_A19_a_redis_outage_does_not_turn_every_webhook_into_a_500():
    async def scenario(w):
        from redis.exceptions import ConnectionError as RedisDown

        from app import redis_client

        class DeadRedis:
            def __getattr__(self, name):
                async def fail(*a, **k):
                    raise RedisDown("connection refused")

                return fail

        redis_client._redis = DeadRedis()
        async with tolerant_client() as client:
            response = await w.wa_post(
                w.wa_payload(phone_of(w, "admin"), "/status"), client=client
            )
        assert response.status_code < 500, response.status_code

    qa_run(scenario)


@needs_qa
@bug(
    "QA-013",
    "(d) the 'already seen' mark is written before the message is handled, so a retry after a crash is dropped",
)
def test_A20_a_message_whose_handling_crashed_is_handled_when_meta_retries():
    async def scenario(w):
        from app.routers import webhook

        calls = []
        real = webhook.handle_message

        async def flaky(**k):
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("the process died here")
            return await real(**k)

        _patch(w, webhook, "handle_message", flaky)
        await w.login("admin")
        payload = w.wa_payload(phone_of(w, "admin"), "/status", msg_id="wamid.crashy")
        await w.wa_post(payload)
        await w.wa_post(payload)  # Meta's retry
        assert len(calls) == 2, (
            "the retry was dropped as a duplicate of a message that was never handled"
        )

    qa_run(scenario)


# ───────────────────────────── A. Telegram ─────────────────────────────


def tg_update(chat: int, text: str, key: str = "message") -> dict:
    return {
        "update_id": uuid.uuid4().int % 10**9,
        key: {
            "message_id": 1,
            "chat": {"id": chat},
            "from": {"id": chat},
            "text": text,
        },
    }


async def tg_raw(client: httpx.AsyncClient, update: dict, secret: str | None = None):
    headers = {"Content-Type": "application/json"}
    if secret is not None:
        headers["X-Telegram-Bot-Api-Secret-Token"] = secret
    return await client.post(
        "/webhook/telegram", content=json.dumps(update).encode(), headers=headers
    )


@needs_qa
def test_A_control_a_telegram_message_from_a_known_person_is_answered():
    async def scenario(w):
        chat = await register_telegram_admin(w)
        async with w.client() as client:
            await tg_raw(client, tg_update(777, "/status"))
        assert w.texts_to(chat)

    qa_run(scenario)


@needs_qa
@bug(
    "QA-026",
    "an edited message is processed as if it were a new one, which can run a second 'yes'",
)
def test_A17_an_edited_telegram_message_is_not_handled_as_a_new_message():
    async def scenario(w):
        chat = await register_telegram_admin(w)
        async with w.client() as client:
            await tg_raw(client, tg_update(777, "/status", key="edited_message"))
        assert not w.texts_to(chat)

    qa_run(scenario)


@needs_qa
@bug(
    "QA-026",
    "a callback_query without a message raises KeyError and the server answers 500",
)
def test_A18_a_telegram_callback_without_a_message_is_ignored_cleanly():
    async def scenario(w):
        update = {
            "update_id": uuid.uuid4().int % 10**9,
            "callback_query": {"id": "1", "data": "x", "from": {"id": 5}},
        }
        async with tolerant_client() as client:
            response = await tg_raw(client, update)
        assert response.status_code == 200, response.status_code

    qa_run(scenario)


@needs_qa
def test_A_a_duplicate_telegram_update_id_is_handled_once():
    async def scenario(w):
        chat = await register_telegram_admin(w)
        update = tg_update(777, "/status")
        async with w.client() as client:
            await tg_raw(client, update)
            first = len(w.texts_to(chat))
            await tg_raw(client, update)
        assert first >= 1 and len(w.texts_to(chat)) == first

    qa_run(scenario)
