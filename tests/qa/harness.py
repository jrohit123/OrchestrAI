"""QA harness for OrchestrAI: everything runs on THIS computer, nothing can reach the real world.

What it gives a test (see tests/qa/README.md):

* throwaway Postgres databases (one routing database and one or two client databases) built from the
  schema-only dumps in tests/qa/fixtures, filled with SYNTHETIC data. The server must be on this
  computer: the harness refuses any other host, and so does every pool the app opens.
* fakeredis in place of Redis.
* fake WhatsApp / Telegram transports (every outbound message is recorded in `world.sent`; failures
  can be injected), a captured OTP email (`world.otps`) and a scripted LLM (`world.llm`) that fails the
  test when something calls it unexpectedly.
* a network block: any HTTP call to a host that is not this computer raises.
* helpers to post signed webhooks, run a chat turn, and put a person in the middle of a draft.

Needs MIGRATE_TEST_PG (or QA_PG) set to a local Postgres, for example
    postgresql://postgres@127.0.0.1:55432/postgres
Without it the tests that need a database are skipped.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import shutil
import subprocess
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit, urlunsplit

import asyncpg
import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).parent / "fixtures"
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
TELEGRAM_TEST_SECRET = (
    "qa-telegram-secret"  # the webhook refuses every update without a secret
)
_TEST_SECRET = object()  # tg_post's default: send the test secret
ADMIN_DSN = (os.environ.get("QA_PG") or os.environ.get("MIGRATE_TEST_PG") or "").strip()

needs_qa = pytest.mark.skipif(
    not ADMIN_DSN,
    reason="set MIGRATE_TEST_PG (or QA_PG) to a local Postgres to run this test",
)

TEMPLATE_SOURCES = {
    "routing": "schema_routing.sql",
    "housing": "schema_housing.sql",
    "jewellery": "schema_jewellery.sql",
}

# the people and numbers in every test are made up
PHONES = {
    "admin": "+919000000001",
    "member": "+919000000002",
    "approver": "+919000000003",
    "staff": "+919000000004",
}


class NetworkBlocked(RuntimeError):
    """A test tried to call a host that is not this computer."""


def require_local(dsn: str) -> None:
    host = urlsplit(dsn).hostname
    if host not in LOCAL_HOSTS:
        raise RuntimeError(
            f"QA harness refuses a database that is not on this computer: {host!r}"
        )


def _dsn_for(db_name: str) -> str:
    parts = urlsplit(ADMIN_DSN)
    return urlunsplit(parts._replace(path="/" + db_name))


def find_psql() -> str:
    found = shutil.which("psql")
    if found:
        return found
    for folder in (
        os.environ.get("PG_BIN"),
        str(Path.home() / "scoop" / "apps" / "postgresql" / "current" / "bin"),
    ):
        if folder:
            for name in ("psql.exe", "psql"):
                candidate = Path(folder) / name
                if candidate.exists():
                    return str(candidate)
    raise RuntimeError("psql not found: put it on PATH or set PG_BIN")


_templates_ready = False


async def ensure_templates() -> None:
    """Build the three template databases once per test run from the schema dumps."""
    global _templates_ready
    if _templates_ready:
        return
    require_local(ADMIN_DSN)
    psql = find_psql()
    admin = await asyncpg.connect(ADMIN_DSN)
    try:
        for kind in TEMPLATE_SOURCES:
            await admin.execute(
                f'DROP DATABASE IF EXISTS "qa_tmpl_{kind}" WITH (FORCE)'
            )
            await admin.execute(f'CREATE DATABASE "qa_tmpl_{kind}"')
    finally:
        await admin.close()
    for kind, filename in TEMPLATE_SOURCES.items():
        result = await asyncio.to_thread(
            subprocess.run,
            [
                psql,
                "-X",
                "-q",
                "-v",
                "ON_ERROR_STOP=1",
                "-d",
                _dsn_for(f"qa_tmpl_{kind}"),
                "-f",
                str(FIXTURES / filename),
            ],
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"could not build template '{kind}': {result.stderr[-800:]}"
            )
    _templates_ready = True


# ───────────────────────────── fake LLM ─────────────────────────────


def llm_message(content: str | None = None, tool_calls: list[dict] | None = None):
    """An OpenAI-shaped chat completion with one choice."""
    calls = []
    for i, call in enumerate(tool_calls or []):
        calls.append(
            SimpleNamespace(
                id=call.get("id", f"call_{i}"),
                type="function",
                function=SimpleNamespace(
                    name=call["name"], arguments=json.dumps(call.get("args", {}))
                ),
            )
        )
    message = SimpleNamespace(
        role="assistant", content=content, tool_calls=calls or None
    )
    message.model_dump = lambda **_: {
        "role": "assistant",
        "content": content,
        **(
            {
                "tool_calls": [
                    {
                        "id": c.id,
                        "type": "function",
                        "function": {
                            "name": c.function.name,
                            "arguments": c.function.arguments,
                        },
                    }
                    for c in calls
                ]
            }
            if calls
            else {}
        ),
    }
    choice = SimpleNamespace(
        index=0, message=message, finish_reason="tool_calls" if calls else "stop"
    )
    return SimpleNamespace(
        id="chatcmpl-qa",
        model="qa-fake",
        choices=[choice],
        usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2),
    )


class ScriptedLLM:
    """Deterministic stand-in for every model call. By default any call fails the test."""

    def __init__(self):
        self.calls: list[dict] = []
        self._queue: list = []
        self._handler = None

    def queue(self, *responses):
        self._queue.extend(responses)

    def handler(self, fn):
        self._handler = fn

    async def __call__(self, *args, **kwargs):
        self.calls.append({"args": args, "kwargs": kwargs})
        if self._handler:
            out = self._handler(*args, **kwargs)
            if asyncio.iscoroutine(out):
                out = await out
            return out
        if not self._queue:
            raise AssertionError(
                "the LLM was called but the test scripted no answer for it"
            )
        item = self._queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


# ───────────────────────────── the world ─────────────────────────────


class QAWorld:
    def __init__(self):
        self.kinds: list[str] = []
        self.dbs: dict[str, str] = {}  # kind -> database name
        self.pools: dict[str, asyncpg.Pool] = {}  # kind -> pool
        self.routing: asyncpg.Pool | None = None
        self.keys: dict[str, str] = {}  # kind -> source_key
        self.sent: list[dict] = []
        self.otps: list[tuple[str, str]] = []
        self.llm = ScriptedLLM()
        self.fail_sends = None  # callable(to, kind) -> Exception | None
        self.ids = SimpleNamespace()
        self._undo: list = []
        self.http_calls: list[str] = []

    # ---- convenience --------------------------------------------------
    @property
    def key(self) -> str:
        return self.keys[self.kinds[0]]

    def texts_to(self, phone: str) -> list[str]:
        return [m["text"] for m in self.sent if m["to"] == phone and m.get("text")]

    def last_otp(self, email: str) -> str | None:
        for who, code in reversed(self.otps):
            if who == email:
                return code
        return None

    async def sql(self, query: str, *args, kind: str | None = None):
        return await self.pools[kind or self.kinds[0]].fetch(query, *args)

    async def one(self, query: str, *args, kind: str | None = None):
        return await self.pools[kind or self.kinds[0]].fetchrow(query, *args)

    async def run(self, query: str, *args, kind: str | None = None):
        return await self.pools[kind or self.kinds[0]].execute(query, *args)

    # ---- people and state ---------------------------------------------
    async def user(self, name: str, kind: str | None = None) -> dict:
        """The identity dict the app builds for a seeded person ('admin', 'member', ...)."""
        from app.services.identity import resolve_identity

        phone = getattr(self.ids, f"phone_{name}")
        user = await resolve_identity(phone)
        assert user, f"seeded user {name} not found"
        return user

    async def login(self, name_or_phone: str):
        """Mark a person as signed in, so the 4-hourly code step is not in the way."""
        from app.redis_client import set_auth_token

        phone = PHONES.get(name_or_phone) or name_or_phone
        await set_auth_token(self.ids.org_id, phone, 480)

    async def say(self, phone: str, text: str, msg_type: str = "text"):
        """One chat turn, straight into the message handler (no HTTP)."""
        from app.routers import webhook

        return await webhook.handle_message(phone=phone, text=text, msg_type=msg_type)

    async def make_pending(
        self,
        name: str,
        intent_key: str,
        fields: dict,
        stage: str = "awaiting_confirmation",
        age_minutes: float = 0,
        with_session: bool = True,
    ):
        """Put a person in the middle of a draft: in Redis (the chat's copy) and in user_drafts."""
        import datetime as dt

        from app.redis_client import get_session, set_session
        from app.services.draft_store import upsert_draft

        user = await self.user(name)
        created = (
            dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=age_minutes)
        ).isoformat()
        await upsert_draft(
            org_id=user["org_id"],
            user_id=user["user_id"],
            intent_key=intent_key,
            fields=fields,
            stage=stage,
            source_key=user["source_key"],
        )
        if with_session:
            session_id = f"{user['org_id']}:{user['phone']}"
            session = await get_session(session_id)
            session["pending_action"] = {
                "intent_key": intent_key,
                "fields": fields,
                "stage": stage,
                "created_at": created,
                "reprompt_count": 0,
            }
            await set_session(session_id, session, ttl=480 * 60)
        return user

    def use_returning_fix(self) -> None:
        """Make `execute(... RETURNING ...)` hand back rows, the way the approval code expects (QA-032).

        db.execute returns asyncpg's status text ("INSERT 0 1"), and the approval code then does
        `approval_row[0]["id"]`, which raises TypeError. A test about some OTHER approval bug calls this so the
        approval gets as far as the bug under test; the test for QA-032 itself does not call it."""
        from app import db
        from app.executor import workflow_executor
        from app.services import step_interpreter

        original = db.execute

        async def execute_returning(query, *args, source_key):
            if "RETURNING" in query.upper():
                return await db.fetch_all(query, *args, source_key=source_key)
            return await original(query, *args, source_key=source_key)

        _patch(self, step_interpreter, "execute", execute_returning)
        _patch(self, workflow_executor, "execute", execute_returning)

    def slow_after(self, obj, name: str, delay: float, when=None) -> None:
        """Wrap the async function obj.name so that, after it has answered, it waits `delay` seconds.

        That is what a real network does (a database or Redis answer takes milliseconds), and it is what makes a
        "read, then write" race show up every time instead of one run in ten on a fast local machine."""
        original = getattr(obj, name)

        async def wrapper(*a, **k):
            out = await original(*a, **k)
            if when is None or when(*a, **k):
                await asyncio.sleep(delay)
            return out

        _patch(self, obj, name, wrapper)

    # ---- webhooks -----------------------------------------------------
    def client(self) -> httpx.AsyncClient:
        from app.main import app

        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        )

    @staticmethod
    def sign(raw: bytes) -> str:
        from app.routers import webhook

        return (
            "sha256="
            + hmac.new(webhook.APP_SECRET.encode(), raw, hashlib.sha256).hexdigest()
        )

    @staticmethod
    def wa_payload(
        phone: str,
        text: str | None = None,
        msg_id: str | None = None,
        msg_type: str = "text",
        extra: dict | None = None,
        messages: list | None = None,
    ):
        number = phone.lstrip("+")
        if messages is None:
            message = {
                "from": number,
                "id": msg_id or f"wamid.{uuid.uuid4().hex}",
                "type": msg_type,
                "timestamp": "1",
            }
            if msg_type == "text":
                message["text"] = {"body": text}
            message.update(extra or {})
            messages = [message]
        return {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": "1",
                    "changes": [
                        {
                            "field": "messages",
                            "value": {
                                "messaging_product": "whatsapp",
                                "messages": messages,
                            },
                        }
                    ],
                }
            ],
        }

    async def wa_post(
        self,
        payload,
        signature: str | None = "auto",
        raw: bytes | None = None,
        client: httpx.AsyncClient | None = None,
    ):
        raw = raw if raw is not None else json.dumps(payload).encode()
        headers = {"Content-Type": "application/json"}
        if signature == "auto":
            headers["X-Hub-Signature-256"] = self.sign(raw)
        elif signature:
            headers["X-Hub-Signature-256"] = signature
        if client is not None:
            return await client.post("/webhook/whatsapp", content=raw, headers=headers)
        async with self.client() as c:
            return await c.post("/webhook/whatsapp", content=raw, headers=headers)

    async def tg_post(
        self,
        chat_id,
        text: str | None = None,
        update_id: int | None = None,
        secret=_TEST_SECRET,
        update: dict | None = None,
    ):
        """Post a Telegram update. By default it carries the test secret; pass secret=None to send none."""
        if secret is _TEST_SECRET:
            secret = TELEGRAM_TEST_SECRET
        body = update or {
            "update_id": update_id
            if update_id is not None
            else uuid.uuid4().int % 10**9,
            "message": {
                "message_id": 1,
                "chat": {"id": chat_id},
                "from": {"id": chat_id},
                "text": text,
            },
        }
        headers = {"Content-Type": "application/json"}
        if secret is not None:
            headers["X-Telegram-Bot-Api-Secret-Token"] = secret
        async with self.client() as c:
            return await c.post(
                "/webhook/telegram", content=json.dumps(body).encode(), headers=headers
            )


def _reset_caches():
    """Clear every in-memory cache the app keeps, so one test cannot see another's data."""
    from app.admin_panel import common
    from app.services import (
        agent,
        case_ops,
        config_store,
        party_access,
        schema_utils,
        sql_guard,
        step_interpreter,
        vocabulary,
    )

    for cache in (
        common._caps_cache,
        common._channel_cache,
        common._check_cache,
        agent._schema_cache,
        case_ops._category_cache,
        config_store._cache,
        party_access._cache,
        schema_utils._COLUMN_TYPE_CACHE,
        schema_utils._ENUM_CONSTRAINT_CACHE,
        sql_guard._scoped_cache,
        sql_guard._policy_cache,
        vocabulary._cache,
    ):
        cache.clear()
    step_interpreter.invalidate_schema_allowlist()


@asynccontextmanager
async def qa_world(kinds=("housing",), pool_size: int = 12, seed: bool = True):
    """Build a world, give it to the test, tear it all down (drop the databases) afterwards."""
    import fakeredis

    from app import db, redis_client

    await ensure_templates()
    require_local(ADMIN_DSN)
    world = QAWorld()
    world.kinds = list(kinds)
    run_id = uuid.uuid4().hex[:8]
    admin = await asyncpg.connect(ADMIN_DSN)

    async def tz(conn):
        await conn.execute("SET timezone = 'Asia/Kolkata'")

    try:
        for kind in ["routing", *world.kinds]:
            name = f"qa_{run_id}_{kind}"
            await admin.execute(f'CREATE DATABASE "{name}" TEMPLATE "qa_tmpl_{kind}"')
            world.dbs[kind] = name
        world.routing = await asyncpg.create_pool(
            _dsn_for(world.dbs["routing"]),
            min_size=pool_size,
            max_size=pool_size,
            init=tz,
            statement_cache_size=0,
        )
        for kind in world.kinds:
            require_local(_dsn_for(world.dbs[kind]))
            world.pools[kind] = await asyncpg.create_pool(
                _dsn_for(world.dbs[kind]),
                min_size=pool_size,
                max_size=pool_size,
                init=tz,
                statement_cache_size=0,
            )
            world.keys[kind] = f"qa_{kind}"
            channel = "telegram" if kind == "housing" else "whatsapp"
            await world.routing.execute(
                "INSERT INTO data_sources (source_key, database_url, messaging_channel) VALUES ($1, $2, $3)",
                world.keys[kind],
                _dsn_for(world.dbs[kind]),
                channel,
            )

        # wire the app to this world
        db._routing_pool = world.routing
        db._pools.clear()
        for kind in world.kinds:
            db._pools[world.keys[kind]] = world.pools[kind]
        redis_client._redis = fakeredis.FakeAsyncRedis(decode_responses=True)
        _reset_caches()
        _install_fakes(world)
        if seed:
            from tests.qa.seed import seed_housing, seed_jewellery

            if "housing" in world.kinds:
                await seed_housing(world)
            if "jewellery" in world.kinds:
                await seed_jewellery(world)
        yield world
    finally:
        for undo in reversed(world._undo):
            try:
                undo()
            except Exception:
                pass
        try:
            if redis_client._redis is not None:
                await redis_client._redis.aclose()
        except Exception:
            pass
        redis_client._redis = None
        db._routing_pool = None
        db._pools.clear()
        for pool in [*world.pools.values(), world.routing]:
            if pool is not None:
                try:
                    await asyncio.wait_for(pool.close(), 10)
                except Exception:
                    pool.terminate()
        for name in world.dbs.values():
            try:
                await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
            except Exception:
                pass
        await admin.close()


def qa_run(scenario, kinds=("housing",), **kw):
    """Run `async def scenario(world)` inside a fresh world."""

    async def go():
        async with qa_world(kinds, **kw) as world:
            return await scenario(world)

    return asyncio.run(go())


def _patch(world: QAWorld, obj, name: str, value):
    original = getattr(obj, name)
    setattr(obj, name, value)
    world._undo.append(lambda: setattr(obj, name, original))


def _install_fakes(world: QAWorld) -> None:
    """Replace every door to the outside: chat transports, email, the model, and the network."""
    from app.routers import telegram_webhook
    from app.services import agent, llm_router, otp_service, telegram, whatsapp

    _patch(world, telegram_webhook, "TELEGRAM_WEBHOOK_SECRET", TELEGRAM_TEST_SECRET)

    async def record(kind: str, to: str, text: str = "", **meta):
        if world.fail_sends:
            err = world.fail_sends(to, kind)
            if err:
                raise err
        world.sent.append({"to": to, "kind": kind, "text": text, **meta})
        return {"ok": True}

    # WhatsApp transport (phones start with +)
    async def wa_text(to, message):
        return await record("text", to, message)

    async def wa_buttons(to, body, buttons):
        return await record("buttons", to, body, buttons=buttons)

    async def wa_document(
        to, pdf_bytes, filename, caption="", mime_type="application/pdf"
    ):
        return await record(
            "document", to, caption, filename=filename, size=len(pdf_bytes or b"")
        )

    async def wa_list(to, body, button_label, sections):
        return await record("list", to, body, sections=sections)

    for name, fn in (
        ("send_text", wa_text),
        ("send_buttons", wa_buttons),
        ("send_document", wa_document),
        ("send_list", wa_list),
    ):
        _patch(world, whatsapp, name, fn)

    # Telegram transport: the chat id arrives without the tg: prefix; record it WITH the prefix
    async def tg_text(chat_id, message):
        return await record("text", f"tg:{chat_id}", message)

    async def tg_buttons(chat_id, body, buttons):
        return await record("buttons", f"tg:{chat_id}", body, buttons=buttons)

    async def tg_document(
        chat_id, pdf_bytes, filename, caption="", mime_type="application/pdf"
    ):
        return await record(
            "document",
            f"tg:{chat_id}",
            caption,
            filename=filename,
            size=len(pdf_bytes or b""),
        )

    async def tg_list(chat_id, body, button_label, sections):
        return await record("list", f"tg:{chat_id}", body, sections=sections)

    async def tg_photo(chat_id, file_id, caption=""):
        return await record("photo", f"tg:{chat_id}", caption, file_id=file_id)

    async def tg_callback(callback_id, *a, **k):
        return None

    for name, fn in (
        ("send_text", tg_text),
        ("send_buttons", tg_buttons),
        ("send_document", tg_document),
        ("send_list", tg_list),
        ("send_photo", tg_photo),
        ("answer_callback", tg_callback),
    ):
        if hasattr(telegram, name):
            _patch(world, telegram, name, fn)

    async def sync_commands(*a, **k):
        return None

    from app.services import menu

    _patch(world, menu, "sync_telegram_commands", sync_commands)

    # the OTP email: capture the code instead of sending it
    async def fake_brevo(
        to_email, user_name, otp, action_desc, org_name, expiry_minutes
    ):
        world.otps.append((to_email, otp))
        return True

    _patch(world, otp_service, "_send_brevo_email", fake_brevo)

    # the model: every entry point
    _patch(world, llm_router, "chat_completion", world.llm)
    _patch(world, agent, "_llm_chat", world.llm)

    # the network: nothing but this computer
    original_async = httpx.AsyncClient.send

    async def guarded(self, request, *a, **k):
        host = request.url.host
        world.http_calls.append(str(request.url))
        if host not in LOCAL_HOSTS and host != "testserver":
            raise NetworkBlocked(f"QA harness blocked a call to {host}")
        return await original_async(self, request, *a, **k)

    _patch(world, httpx.AsyncClient, "send", guarded)
