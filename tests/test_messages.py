"""Tests for the message list (app/services/messages.py) and for how the code uses it.

The promise being tested: the assistant says exactly what it always said until someone writes
something else, every message the code asks for exists, and nobody can slip a typed sentence back
into the chat code without a test noticing.
"""

import ast
import asyncio
import re
from pathlib import Path

import pytest

from app.executor import workflow_executor
from app.routers import webhook
from app.services import config_store as cs
from app.services import messages, otp_service
from app.services.messages import GROUPS, MESSAGES, VALUES, say

APP = Path(__file__).resolve().parent.parent / "app"
RESERVED = {
    "source_key",
    "key",
    "locale",
    "pack",
    "default",
}  # names say() takes itself


def _placeholders(text: str) -> set[str]:
    return set(re.findall(r"(?<!\{)\{([a-z_]+)\}", text))


@pytest.fixture(autouse=True)
def _forget():
    cs.invalidate()
    yield
    cs.invalidate()


# ------------------------------------------------------------ the list itself


def test_every_message_is_described_and_uses_only_known_values():
    assert len(MESSAGES) >= 70
    for key, m in MESSAGES.items():
        assert m.key == key and re.fullmatch(r"[a-z]+\.[a-z_]+", key), key
        assert m.group in GROUPS, key
        assert m.name and m.when and m.text.strip(), key
        used = _placeholders(m.text)
        assert used == set(m.values) == set(m.example), key
        assert used <= set(VALUES), key
        assert not used & RESERVED, key


def test_every_group_has_messages_and_every_value_is_used():
    used_groups = {m.group for m in MESSAGES.values()}
    assert used_groups == set(GROUPS)
    used_values = {n for m in MESSAGES.values() for n in m.values}
    assert used_values == set(VALUES)


def test_the_examples_fill_every_message_completely():
    for key, m in MESSAGES.items():
        shown = cs.fill(m.text, m.example)
        assert "{" not in shown and "}" not in shown, key


def test_a_text_cannot_reach_into_a_value():
    for bad in ("{name.__class__}", "{name[0]}", "{0}", "{}", "{name!r:>{width.x}}"):
        with pytest.raises(ValueError):
            cs.fill(bad, {"name": "Asha", "width": 3})
    assert cs.fill("{name!r}", {"name": "Asha"}) == "'Asha'"
    assert cs.fill("{unknown}", {}) == "{unknown}"


# ------------------------------------------------------------ the wording is what it always was

KEPT = {
    "error.generic": "❌ Something went wrong. Please try again.",
    "otp.none_active": "No active OTP found. Reply 'retry' to get a new code.",
    "otp.too_many": "Too many attempts. Reply 'retry' to get a new code.",
    "otp.expired": "Code has expired. Reply 'retry' to get a new code.",
    "otp.wrong_last": "Incorrect code. 0 attempts remaining. Reply 'retry' to get a new code.",
    "security.verified_resend": "✅ Identity verified! Session active for 4h. Please resend your request.",
    "security.verified_resend_short": "✅ Verified! Please resend your original request.",
    "draft.cleared": "🔄 Cleared. What would you like to do?\n\n_Type *menu* to see your options._",
    "draft.nothing_in_progress": "✅ Nothing in progress. Type *menu* to see your options.",
    "menu.intro": "📋 Here's what I can help with:",
    "menu.unknown_command": "Didn't recognise that command — here's what's available:",
    "error.document": "❌ Something went wrong creating the document. Please try again.",
    "action.completed": "Action completed successfully",
}


@pytest.mark.parametrize(("key", "text"), list(KEPT.items()))
def test_a_message_without_values_says_what_it_always_said(key, text):
    assert asyncio.run(say(None, key)) == text


def test_messages_with_values_say_what_they_always_said():
    def s(key, **v):
        return asyncio.run(say(None, key, **v))

    assert s("otp.cooldown", wait_seconds=30) == (
        "⏳ Please wait 30s before requesting another code."
    )
    assert s("otp.wrong", remaining=2) == "Incorrect code. 2 attempt(s) remaining."
    assert s("otp.rejected", reason="Code has expired.") == "❌ Code has expired."
    assert s("photo.held", minutes=15) == (
        "📎 Got the photo. Now tell me what it is for, for example start /complaint, "
        "/update or /close. I keep it for 15 minutes."
    )
    assert s("photo.added", count=2) == "📎 Photo added (2 attached)."
    assert s("photo.added_confirm", count=2) == (
        "📎 Photo added (2 attached). Reply *yes* to save."
    )
    assert s("draft.cancelled_count", intent="register_complaint", count=3) == (
        "🔄 Draft for *register_complaint* cancelled (3 field(s) discarded)."
    )
    assert s(
        "approval.request", requester="Asha (tenant)", intent="Refund", amount="12,500"
    ) == (
        "📋 *Approval Request*\n\nFrom: Asha (tenant)\nAction: Refund\n"
        "Amount: Rs.12,500\n\nPlease approve or reject:"
    )
    assert s(
        "approval.request_level",
        level=2,
        total=3,
        requester="Asha",
        intent="Refund",
        amount="12,500",
    ) == (
        "📋 *Approval Request* — level 2 of 3\n\nFrom: Asha\nAction: Refund\n"
        "Amount: Rs.12,500\n\nPlease approve or reject:"
    )
    details = s(
        "onboarding.confirm_details", name="Asha", email="a@b.co", role="Tenant"
    )
    assert details == (
        "📝 Confirm your details:\n  • Name: Asha\n  • Email: a@b.co\n  • Role: Tenant\n\n"
        "Reply *yes* to create your account, *no* to cancel, or tell me what to change "
        '(e.g. "change role to tenant").'
    )
    updated = s(
        "onboarding.details_updated", name="Asha", email="a@b.co", role="Tenant"
    )
    assert updated == details.replace(
        "Confirm your details:", "Updated. Confirm your details:"
    )


# ------------------------------------------------------------ what an organisation writes wins


def _saved(monkeypatch, rows):
    """Pretend these rows are saved in the system_messages table of database 'godrej'."""

    async def fetch(sql, *args, source_key):
        if "FROM system_messages" in sql and source_key == "godrej":
            return [
                {
                    "key": k,
                    "locale": "en-IN",
                    "scope": "tenant",
                    "scope_ref": "",
                    "version": 1,
                    "body": body,
                }
                for k, body in rows.items()
            ]
        return []

    monkeypatch.setattr(cs, "_fetch", fetch)


def test_an_organisations_own_wording_is_used_and_the_others_keep_theirs(monkeypatch):
    _saved(monkeypatch, {"otp.cooldown": "Hold on {wait_seconds} seconds, please."})
    assert asyncio.run(say("godrej", "otp.cooldown", wait_seconds=9)) == (
        "Hold on 9 seconds, please."
    )
    assert asyncio.run(say("baanganga", "otp.cooldown", wait_seconds=9)) == (
        "⏳ Please wait 9s before requesting another code."
    )
    assert asyncio.run(say("godrej", "draft.none")) == (
        "✅ No active draft. You're ready to start fresh."
    )


@pytest.mark.parametrize(
    "broken",
    [
        "Hold on {wait_seconds",
        "Hold on {wait_seconds.real}",
        "Hold on {0}",
        "Hold {} on",
    ],
)
def test_a_text_that_cannot_be_filled_in_falls_back_to_the_built_in_one(
    monkeypatch, broken
):
    _saved(monkeypatch, {"otp.cooldown": broken})
    assert asyncio.run(say("godrej", "otp.cooldown", wait_seconds=9)) == (
        "⏳ Please wait 9s before requesting another code."
    )


def test_asking_for_a_message_that_does_not_exist_is_a_mistake_that_shows():
    with pytest.raises(KeyError):
        asyncio.run(say(None, "no.such_message"))


# ------------------------------------------------------------ the code uses the list correctly


def _py_files():
    return sorted(p for p in APP.rglob("*.py") if "__pycache__" not in p.parts)


def _say_calls():
    """(file, line, keys, keyword names, has ** arguments) of every say(...) call in the app."""
    found = []
    for path in _py_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "say"
            ):
                continue
            key = node.args[1] if len(node.args) > 1 else None
            if isinstance(key, ast.Constant):
                keys = [key.value]
            elif (
                isinstance(key, ast.IfExp)
                and isinstance(key.body, ast.Constant)
                and isinstance(key.orelse, ast.Constant)
            ):
                keys = [key.body.value, key.orelse.value]
            else:
                keys = (
                    None  # a key held in a variable: checked by its string at the call
                )
            names = {k.arg for k in node.keywords if k.arg}
            spread = any(k.arg is None for k in node.keywords)
            found.append(
                (path.relative_to(APP).as_posix(), node.lineno, keys, names, spread)
            )
    return found


def test_the_code_asks_for_messages_that_exist_with_the_values_they_need():
    calls = _say_calls()
    assert len(calls) >= 60
    for file, line, keys, names, spread in calls:
        where = f"{file}:{line}"
        if keys is None:
            continue
        for key in keys:
            assert key in MESSAGES, f"{where}: no message '{key}'"
        needed = [_placeholders(MESSAGES[k].text) for k in keys]
        if not spread:
            for need in needed:
                assert need <= names, f"{where}: '{keys}' needs {sorted(need - names)}"
            assert names <= set().union(*needed), (
                f"{where}: values {sorted(names - set().union(*needed))} are not used by '{keys}'"
            )
        assert not names & RESERVED, where


def test_every_message_in_the_list_is_used_somewhere():
    strings = set()
    for path in _py_files():
        if path.name == "messages.py":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                strings.add(node.value)
    unused = sorted(k for k in MESSAGES if k not in strings)
    assert not unused, f"in the list but never asked for: {unused}"


# the places where people are written to, and what is allowed to be typed there
SENDERS = {"send_text": 1, "send_list": 1}  # the text is the argument at this position
CHAT_FILES = [
    "routers/webhook.py",
    "routers/telegram_webhook.py",
    "executor/workflow_executor.py",
    "services/otp_service.py",
]


def test_no_sentence_is_typed_into_the_chat_code_any_more():
    """Anything said to a person goes through say(), so it can be changed on the dashboard."""
    typed = []
    for name in CHAT_FILES:
        path = APP / name
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            fn = (
                node.func.attr
                if isinstance(node.func, ast.Attribute)
                else getattr(node.func, "id", "")
            )
            args = []
            if fn in SENDERS and len(node.args) > SENDERS[fn]:
                args.append(node.args[SENDERS[fn]])
            if fn == "send_buttons":
                args += [k.value for k in node.keywords if k.arg == "body"]
            for a in args:
                if isinstance(a, ast.JoinedStr) or (
                    isinstance(a, ast.Constant) and isinstance(a.value, str)
                ):
                    typed.append(f"{name}:{node.lineno}")
    assert not typed, f"sentences typed in the code, use say(): {typed}"


# ------------------------------------------------------------ real flows, with the outside faked


class Chat:
    """Stands in for the chat channel, the session store and the database."""

    def __init__(self, monkeypatch):
        self.sent = []
        self.sessions = {}
        self.monkeypatch = monkeypatch

        async def send_text(to, text, *a, **k):
            self.sent.append(text)

        async def get_session(sid):
            return dict(self.sessions.get(sid, {}))

        async def set_session(sid, data, ttl=600):
            self.sessions[sid] = data

        async def delete_session(sid):
            self.sessions.pop(sid, None)

        for name, fn in (
            ("send_text", send_text),
            ("get_session", get_session),
            ("set_session", set_session),
            ("delete_session", delete_session),
        ):
            monkeypatch.setattr(webhook, name, fn)

        async def channel(name):
            return {"telegram": "godrej", "whatsapp": "baanganga"}[name]

        async def nothing_saved(sql, *args, source_key):
            return []

        monkeypatch.setattr("app.db.get_source_key_for_channel", channel)
        monkeypatch.setattr(cs, "_fetch", nothing_saved)  # no database in these tests

    def user(self, **more):
        base = {
            "user_id": "u-1",
            "org_id": "o-1",
            "source_key": "godrej",
            "is_active": True,
            "org_active": True,
            "email": "asha@example.com",
        }
        return {**base, **more}


@pytest.fixture
def chat(monkeypatch):
    return Chat(monkeypatch)


def _identity(monkeypatch, user):
    async def resolve(phone):
        return user

    monkeypatch.setattr(webhook, "resolve_identity", resolve)


def test_someone_not_linked_on_telegram_gets_the_welcome(chat, monkeypatch):
    _identity(monkeypatch, None)
    asyncio.run(webhook._handle_message("tg:123", "hello"))
    assert chat.sent == [asyncio.run(say(None, "onboarding.welcome"))]
    assert chat.sent[0].startswith("👋 Welcome to OrchestrAI!")


def test_the_welcome_is_the_clients_own_when_it_wrote_one(chat, monkeypatch):
    _identity(monkeypatch, None)
    _saved(monkeypatch, {"onboarding.welcome": "Namaste! Send your email to begin."})
    asyncio.run(webhook._handle_message("tg:123", "hello"))
    assert chat.sent == ["Namaste! Send your email to begin."]


def _self_registration(monkeypatch, roles):
    """The roles the organisation lets a stranger take when she registers herself in the chat."""

    async def listed(source_key):
        return roles

    monkeypatch.setattr(webhook, "_self_registration_roles", listed)


def test_an_email_that_matches_no_account_is_told_so_in_the_clients_words(
    chat, monkeypatch
):
    _identity(monkeypatch, None)
    _self_registration(monkeypatch, ["member"])  # this client lets people register

    async def owner(phone):
        return "godrej"  # and it is the client that owns this kind of chat

    async def nobody(email, **kwargs):
        return None

    monkeypatch.setattr(webhook, "_channel_source_key", owner)

    monkeypatch.setattr("app.services.identity.find_unlinked_user_by_email", nobody)
    _saved(monkeypatch, {"onboarding.no_account": "No account for that email."})
    asyncio.run(webhook._handle_message("tg:123", "it is asha@example.com"))
    assert chat.sent == ["No account for that email."]
    assert chat.sessions["tglink:tg:123"]["state"] == "awaiting_new_user_name"


def test_when_the_client_does_not_let_people_register_in_the_chat_it_says_so_in_its_words(
    chat, monkeypatch
):
    _identity(monkeypatch, None)
    _self_registration(monkeypatch, [])  # nothing listed: closed

    async def nobody(email, **kwargs):
        return None

    monkeypatch.setattr("app.services.identity.find_unlinked_user_by_email", nobody)
    _saved(
        monkeypatch, {"onboarding.closed": "Sign-up here is closed. Ask your admin."}
    )
    asyncio.run(webhook._handle_message("tg:123", "it is asha@example.com"))
    assert chat.sent == ["Sign-up here is closed. Ask your admin."]
    # she is not left half way through a sign-up: no question about her name follows
    assert "tglink:tg:123" not in chat.sessions


def test_an_unknown_whatsapp_number_is_asked_for_its_email(chat, monkeypatch):
    _identity(monkeypatch, None)
    asyncio.run(webhook._handle_message("919999999999", "hi"))
    assert chat.sent == [asyncio.run(say(None, "onboarding.welcome_whatsapp"))]
    assert "WhatsApp number isn't linked" in chat.sent[0]


def test_with_the_whatsapp_link_switched_off_an_unknown_number_is_told_it_is_not_registered(
    chat, monkeypatch
):
    _identity(monkeypatch, None)

    async def off(phone):
        return False

    monkeypatch.setattr(webhook, "_whatsapp_linking_on", off)
    asyncio.run(webhook._handle_message("919999999999", "hi"))
    assert chat.sent == [
        "👋 Your number isn't registered with OrchestrAI.\nContact your admin to get access."
    ]


def test_when_the_client_cannot_be_told_the_built_in_words_are_used(chat, monkeypatch):
    _identity(monkeypatch, None)

    async def nobody(name):
        raise RuntimeError("more than one client claims this channel")

    monkeypatch.setattr("app.db.get_source_key_for_channel", nobody)
    asyncio.run(webhook._handle_message("919999999999", "hi"))
    assert chat.sent[0].startswith("👋 Welcome to OrchestrAI!")


def test_a_switched_off_account_is_told_so(chat, monkeypatch):
    _identity(monkeypatch, chat.user(is_active=False))
    asyncio.run(webhook._handle_message("919999999999", "hi"))
    assert chat.sent == ["❌ Your account is inactive. Contact admin."]


def test_cancelling_when_nothing_is_open(chat, monkeypatch):
    async def none(*a, **k):
        return None

    monkeypatch.setattr("app.services.draft_store.get_active_draft", none)
    asyncio.run(webhook.cancel_user_draft(chat.user(), "919999999999"))
    assert chat.sent == ["✅ No active draft to cancel."]


def test_cancelling_a_draft_with_answers_says_how_many_were_dropped(chat, monkeypatch):
    async def draft(*a, **k):
        return {"intent_key": "register_complaint", "fields": {"a": 1, "b": 2}}

    async def close(*a, **k):
        return None

    monkeypatch.setattr("app.services.draft_store.get_active_draft", draft)
    monkeypatch.setattr("app.services.draft_store.close_draft", close)
    asyncio.run(webhook.cancel_user_draft(chat.user(), "919999999999"))
    asyncio.run(webhook.cancel_user_draft(chat.user(), "919999999999", confirm=False))
    assert chat.sent == [
        "🔄 Draft for *register_complaint* cancelled (2 field(s) discarded).",
        "🔄 Draft cancelled.",
    ]


def _photo_flow(chat, monkeypatch, stage, settings=None):
    """A photo arrives; stage None means no request that takes photos is open."""
    cs._cache.clear()

    async def open_draft(user):
        return None if stage is None else {"stage": stage, "intent_key": "complaint"}

    async def add(user, phone, draft, ids):
        return len(ids)

    async def org_settings(source_key, org_id):
        return settings or {}

    monkeypatch.setattr(webhook, "_photo_draft", open_draft)
    monkeypatch.setattr(webhook, "_add_photos", add)
    monkeypatch.setattr(cs, "org_settings", org_settings)
    asyncio.run(webhook._take_photos(chat.user(), "919999999999", ["f1", "f2"]))
    return chat.sent


def test_a_photo_with_no_request_open_is_held_for_the_built_in_time(chat, monkeypatch):
    sent = _photo_flow(chat, monkeypatch, None)
    assert sent == [asyncio.run(say(None, "photo.held", minutes=15))]
    assert "I keep it for 15 minutes." in sent[0]


def test_the_time_a_photo_is_held_follows_the_organisations_setting(chat, monkeypatch):
    sent = _photo_flow(chat, monkeypatch, None, {"limits": {"photo_hold_minutes": 40}})
    assert "I keep it for 40 minutes." in sent[0]


def test_a_photo_added_to_a_request_says_so(chat, monkeypatch):
    assert _photo_flow(chat, monkeypatch, "collecting") == [
        "📎 Photo added (2 attached)."
    ]


def test_a_photo_added_while_waiting_for_yes_says_to_reply_yes(chat, monkeypatch):
    assert _photo_flow(chat, monkeypatch, "awaiting_confirmation") == [
        "📎 Photo added (2 attached). Reply *yes* to save."
    ]


# ------------------------------------------------------------ signed-in people: codes and cancelling

VOCAB = {
    "confirm_words": frozenset({"yes"}),
    "cancel_words": frozenset({"no", "cancel"}),
    "cancel_tokens": frozenset({"cancel"}),
    "self_reference_words": frozenset(),
    "retry_words": frozenset({"retry"}),
}


def _signed_in(chat, monkeypatch, *, authenticated, ttl=480):
    """A known person writes in; `authenticated` says whether their session is still valid."""
    _identity(
        monkeypatch,
        chat.user(
            user_name="Asha", org_name="Alpha", permissions=[], phone="919999999999"
        ),
    )

    async def keep(user):
        return user

    async def org(*a, **k):
        return {"session_ttl_minutes": ttl}

    async def vocab(org_id, source_key):
        return VOCAB

    async def auth(org_id, phone):
        return authenticated

    async def noop(*a, **k):
        return None

    monkeypatch.setattr("app.services.party_access.add_party_permissions", keep)
    monkeypatch.setattr("app.services.vocabulary.get_vocabulary", vocab)
    monkeypatch.setattr(webhook, "fetch_one", org)
    monkeypatch.setattr(webhook, "check_auth_token", auth)
    monkeypatch.setattr(webhook, "set_auth_token", noop)


def _code_result(monkeypatch, result):
    async def generate(**kwargs):
        return result

    monkeypatch.setattr(webhook, "generate_and_send_otp", generate)


def test_a_session_that_has_run_out_asks_for_a_code(chat, monkeypatch):
    _signed_in(chat, monkeypatch, authenticated=False)
    _code_result(monkeypatch, {"sent": True, "expiry_minutes": 10})
    asyncio.run(webhook._handle_message("919999999999", "show my cases"))
    assert chat.sent == [
        (
            "🔐 *Security Verification Required*\n\nYour session has expired.\n"
            "A verification code has been sent to *asha@example.com*.\n"
            "Reply with the code to continue.\n\n_Required every 8 hours for security._"
        )
    ]
    assert chat.sessions["sec:o-1:919999999999"]["pending_text"] == "show my cases"


def test_asking_for_a_code_too_soon_and_a_failed_email_say_so(chat, monkeypatch):
    _signed_in(chat, monkeypatch, authenticated=False)
    _code_result(monkeypatch, {"sent": False, "reason": "cooldown", "wait_seconds": 12})
    asyncio.run(webhook._handle_message("919999999999", "hello"))
    _code_result(monkeypatch, {"sent": False, "reason": "smtp"})
    asyncio.run(webhook._handle_message("919999999999", "hello"))
    assert chat.sent == [
        "⏳ Please wait 12s before requesting another code.",
        "❌ Could not send verification email. Contact admin.",
    ]


def test_a_code_that_is_refused_shows_the_reason(chat, monkeypatch):
    _signed_in(chat, monkeypatch, authenticated=False)
    chat.sessions["sec:o-1:919999999999"] = {"state": "awaiting_security_otp"}

    async def refuse(user_id, code, source_key):
        return {
            "valid": False,
            "reason": "Code has expired. Reply 'retry' to get a new code.",
        }

    monkeypatch.setattr(webhook, "verify_otp", refuse)
    asyncio.run(webhook._handle_message("919999999999", "123456"))
    assert chat.sent == ["❌ Code has expired. Reply 'retry' to get a new code."]


def test_a_right_code_says_how_long_the_session_lasts(chat, monkeypatch):
    _signed_in(chat, monkeypatch, authenticated=False, ttl=90)
    chat.sessions["sec:o-1:919999999999"] = {"state": "awaiting_security_otp"}

    async def accept(user_id, code, source_key):
        return {"valid": True}

    monkeypatch.setattr(webhook, "verify_otp", accept)
    asyncio.run(webhook._handle_message("919999999999", "123456"))
    assert chat.sent == [
        "✅ Identity verified!\n_Session active for 1 hour 30 minutes. Processing your request..._"
    ]


def _cancel_gate(chat, monkeypatch, open_draft):
    _signed_in(chat, monkeypatch, authenticated=True)

    async def stuck(*a, **k):
        return None

    async def draft(*a, **k):
        return {"intent_key": "register_complaint"} if open_draft else None

    monkeypatch.setattr(webhook, "_clear_stuck_draft", stuck)
    monkeypatch.setattr("app.services.draft_store.get_active_draft", draft)
    asyncio.run(webhook._handle_message("919999999999", "cancel"))
    return chat.sent


def test_cancelling_with_a_request_open_says_cleared(chat, monkeypatch):
    assert _cancel_gate(chat, monkeypatch, True) == [
        "🔄 Cleared. What would you like to do?\n\n_Type *menu* to see your options._"
    ]


def test_cancelling_with_nothing_open_says_so(chat, monkeypatch):
    assert _cancel_gate(chat, monkeypatch, False) == [
        "✅ Nothing in progress. Type *menu* to see your options."
    ]


def test_the_cancel_words_follow_the_clients_own_wording(chat, monkeypatch):
    _saved(monkeypatch, {"draft.cleared": "All clear."})
    assert _cancel_gate(chat, monkeypatch, True) == ["All clear."]


# ------------------------------------------------------------ approvals and one-time codes


def test_the_older_verified_flow_says_what_it_said(monkeypatch):
    user = {"source_key": "godrej"}

    async def noop(*a, **k):
        return None

    monkeypatch.setattr(workflow_executor, "set_session", noop)

    def run(session):
        return asyncio.run(workflow_executor.resume_after_otp(user, "sid", session))

    assert run({"pending_intent": {"type": "security_auth"}}) == (
        "✅ Identity verified! Session active for 4h. Please resend your request."
    )
    assert run({}) == "✅ Verified! Please resend your original request."


def _verify(monkeypatch, row, valid_row=None, attempts=3):
    async def fetch_one(sql, *args, source_key):
        return valid_row if "otp_hash = $2" in sql else row

    async def execute(*a, **k):
        return None

    async def config(org_id, source_key):
        return {"max_attempts": attempts}

    monkeypatch.setattr(otp_service, "fetch_one", fetch_one)
    monkeypatch.setattr(otp_service, "execute", execute)
    monkeypatch.setattr(otp_service, "_get_otp_config", config)
    return asyncio.run(otp_service.verify_otp("u-1", "123456", "godrej"))


def test_the_reasons_a_code_is_refused_are_the_ones_people_always_saw(monkeypatch):
    import datetime

    later = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=5)
    earlier = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
        minutes=5
    )

    assert _verify(monkeypatch, None)["reason"] == (
        "No active OTP found. Reply 'retry' to get a new code."
    )
    assert (
        _verify(
            monkeypatch, {"id": 1, "org_id": "o", "attempts": 3, "expires_at": later}
        )["reason"]
        == "Too many attempts. Reply 'retry' to get a new code."
    )
    assert (
        _verify(
            monkeypatch, {"id": 1, "org_id": "o", "attempts": 0, "expires_at": earlier}
        )["reason"]
        == "Code has expired. Reply 'retry' to get a new code."
    )
    wrong = {"id": 1, "org_id": "o", "attempts": 0, "expires_at": later}
    assert (
        _verify(monkeypatch, wrong)["reason"]
        == "Incorrect code. 2 attempt(s) remaining."
    )
    last = {"id": 1, "org_id": "o", "attempts": 2, "expires_at": later}
    assert _verify(monkeypatch, last)["reason"] == (
        "Incorrect code. 0 attempts remaining. Reply 'retry' to get a new code."
    )


def test_the_client_can_reword_why_a_code_was_refused(monkeypatch):
    _saved(monkeypatch, {"otp.expired": "That code is too old."})
    import datetime

    earlier = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
        minutes=5
    )
    assert (
        _verify(
            monkeypatch, {"id": 1, "org_id": "o", "attempts": 0, "expires_at": earlier}
        )["reason"]
        == "That code is too old."
    )


def test_the_module_exports_what_the_screen_will_need():
    assert callable(messages.say) and messages.MESSAGES and messages.GROUPS


def test_the_session_length_is_written_in_words_from_the_clients_own_number():
    from app.services.messages import length_text

    assert length_text(4320) == "3 days"
    assert length_text(1440) == "1 day"
    assert length_text(480) == "8 hours"
    assert length_text(240) == "4 hours"
    assert length_text(90) == "1 hour 30 minutes"
    assert length_text(45) == "45 minutes"
    assert length_text(1) == "1 minute"
    assert length_text(1500) == "1 day 1 hour"
    assert length_text(0) == "1 minute"
