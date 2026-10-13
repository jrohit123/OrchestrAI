"""Local server for the UX audit: the dashboard against MADE-UP databases (ux_routing, ux_housing, ux_jewellery) on this computer.

Serves only the dashboard (the new panel and the classic endpoints it still calls).
No scheduler, no Telegram or WhatsApp, no Redis, and it never reads the project's .env.
It refuses to start unless every database it would touch is on this computer, and any
outbound web call is sent to a dead address, so nothing can leave this PC.
"""

import os
import re
import sys

# 1. never read .env: neutralise python-dotenv before anything in the app imports it
import dotenv

dotenv.load_dotenv = lambda *a, **k: False
dotenv.find_dotenv = lambda *a, **k: ""

# 2. drop anything in this shell's environment that could point at the real world
for _k in list(os.environ):
    if re.search(
        r"(TOKEN|SECRET|PASSWORD|API_KEY|_KEY$|DATABASE_URL|REDIS|TELEGRAM|WHATSAPP|GROQ|OPENAI|CEREBRAS|SMTP|SENDGRID|RESEND|GOOGLE)",
        _k,
        re.I,
    ):
        del os.environ[_k]

REPO = os.environ.get("DASH_REPO", r"D:\Orchestrator AI")
PORT = os.environ.get("PRACTICE_PG_PORT", "55432")
os.environ["ROUTING_DATABASE_URL"] = f"postgresql://postgres@127.0.0.1:{PORT}/ux_routing"
# Some modules insist on these names being set when they are imported. Every value is a dummy,
# so even if some code path tried to use one, nothing real could be reached (and the proxy
# below is dead anyway).
for _name, _dummy in {
    "ADMIN_TOKEN": "local-dev-not-a-secret",  # imported by the classic router, not used for login
    "OPENAI_API_KEY": "local-dummy",
    "REDIS_URL": "redis://127.0.0.1:1",
    "BREVO_API_KEY": "local-dummy",
    "SENDER_EMAIL": "local@example.invalid",
    "SENDER_NAME": "Local",
    "TELEGRAM_BOT_TOKEN": "0:local-dummy",
    "WHATSAPP_TOKEN": "local-dummy",
    "WHATSAPP_VERIFY_TOKEN": "local-dummy",
    "WHATSAPP_APP_SECRET": "local-dummy",
    "WHATSAPP_PHONE_ID": "0",
}.items():
    os.environ[_name] = _dummy
for _k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
    os.environ[_k] = "http://127.0.0.1:9"
os.environ["NO_PROXY"] = "127.0.0.1,localhost"
sys.path.insert(0, REPO)

from contextlib import asynccontextmanager  # noqa: E402

import asyncpg  # noqa: E402
from fastapi import FastAPI  # noqa: E402


async def _assert_local() -> None:
    conn = await asyncpg.connect(os.environ["ROUTING_DATABASE_URL"])
    try:
        found = await conn.fetch("SELECT source_key, database_url FROM data_sources")
    finally:
        await conn.close()
    for row in found:
        host = re.sub(r"^[a-z+]+://([^@/]*@)?([^/:]+).*$", r"\2", row["database_url"])
        if host not in ("127.0.0.1", "localhost", "::1"):
            raise SystemExit(f"STOP: data source '{row['source_key']}' is not on this computer")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await _assert_local()
    from app.db import close_db, init_db

    await init_db()
    yield
    await close_db()


app = FastAPI(title="Dashboard on the practice copy", lifespan=lifespan)

from app.admin_panel import router as panel_router  # noqa: E402

app.include_router(panel_router)

# ---- for the sign-in check: mail is kept here instead of sent, and chat messages are only noted
MAILS: list = []
SENT: list = []


async def _keep_mail(to_email, to_name, subject, text, html=None):
    MAILS.append({"to": to_email, "name": to_name, "subject": subject, "text": text})
    return True


async def _keep_text(to, text):
    SENT.append({"to": to, "text": text})


import app.admin_panel.auth_mail as _auth_mail  # noqa: E402
import app.services.messaging as _messaging  # noqa: E402

_auth_mail.send_email = _keep_mail
_messaging.send_text = _keep_text


@app.get("/__mail")
async def _mails():
    return {"mails": MAILS[-30:], "sent": SENT[-30:]}

# FAKE_AI=1 (or a file named fake_ai.flag next to this one): a pretend assistant for trying the "Describe it in chat" box without any network.
# It always claims the draft is a plain workflow, so what the dashboard does with the admin's
# choice (workflow, building block, case button) can be seen.
if os.environ.get("FAKE_AI") or os.path.exists(os.path.join(os.path.dirname(__file__), "fake_ai.flag")):
    import json as _json

    import app.services.llm_router as _router

    class _Msg:
        def __init__(self, text):
            self.content = text

    class _Choice:
        def __init__(self, text):
            self.message = _Msg(text)

    class _Res:
        def __init__(self, text):
            self.choices = [_Choice(text)]

    async def _fake_chat(messages, **_kw):
        asked = {}
        for m in messages:
            if m["role"] == "user":
                try:
                    asked = _json.loads(m["content"])
                    if "request" in asked:
                        break
                except ValueError:
                    continue
        steps = [{"op": "compute", "params": {}}]
        spec = {
            "name": "Add a note to a case",
            "kind": "workflow",
            "description": "Adds a note to a case.",
            "fields": {},
            "example_phrases": ["add a note"],
            "steps": steps,
        }
        return _Res(_json.dumps({"reply": "Here is a draft.", "workflow": spec}))

    _router.chat_completion = _fake_chat
