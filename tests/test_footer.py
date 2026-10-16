"""The footer note under the chat bot's WhatsApp messages (app/services/footer.py, app/admin_panel/footer_settings.py)."""

import asyncio
import json

from app.admin_panel import access_rules, footer_settings
from app.services import footer, whatsapp

COMMON = {"text": "Powered by OrchestrAI", "plain": False, "available": True}


def test_each_organisation_uses_the_common_footer_its_own_or_none():
    assert footer.effective(None, COMMON) == {
        "text": "Powered by OrchestrAI",
        "plain": False,
    }  # nothing set: the common one
    assert footer.effective(
        {"mode": "own", "text": "  Godrej   helpdesk ", "plain": True}, COMMON
    ) == {"text": "Godrej helpdesk", "plain": True}
    assert footer.effective({"mode": "off"}, COMMON) is None
    assert (
        footer.effective({"mode": "common"}, {"text": "", "plain": False}) is None
    )  # no common text: nothing
    assert footer.effective({"mode": "own", "text": ""}, COMMON) is None
    assert (
        len(footer.effective({"mode": "own", "text": "x" * 200}, COMMON)["text"])
        == footer.MAX
    )


def test_a_plain_reply_gets_the_note_as_its_last_line_only_when_asked():
    assert (
        footer.with_plain_line("Hello", {"text": "Godrej helpdesk", "plain": True})
        == "Hello\n\n_Godrej helpdesk_"
    )
    assert (
        footer.with_plain_line("Hello", {"text": "Godrej helpdesk", "plain": False})
        == "Hello"
    )
    assert footer.with_plain_line("Hello", None) == "Hello"
    once = footer.with_plain_line("Hello", {"text": "G", "plain": True})
    assert (
        footer.with_plain_line(once, {"text": "G", "plain": True}) == once
    )  # never twice


def test_buttons_and_lists_carry_whatsapps_own_footer(monkeypatch):
    sent = []

    class Resp:
        status_code = 200
        text = ""

        def raise_for_status(self):
            pass

        def json(self):
            return {"messages": [{"id": "x"}]}

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, headers=None):
            sent.append(json)
            return Resp()

    async def foot():
        return {"text": "Godrej helpdesk", "plain": True}

    monkeypatch.setattr(whatsapp.httpx, "AsyncClient", lambda *a, **k: Client())
    monkeypatch.setattr(footer, "for_whatsapp", foot)
    asyncio.run(
        whatsapp.send_buttons(
            "+910000000000", "Close it?", [{"id": "y", "title": "Yes"}]
        )
    )
    asyncio.run(
        whatsapp.send_list(
            "+910000000000",
            "Menu",
            "Choose",
            [{"title": "A", "rows": [{"id": "a", "title": "A"}]}],
        )
    )
    asyncio.run(whatsapp.send_text("+910000000000", "Under review."))
    assert sent[0]["interactive"]["footer"] == {"text": "Godrej helpdesk"}
    assert sent[1]["interactive"]["footer"] == {"text": "Godrej helpdesk"}
    assert sent[2]["text"]["body"] == "Under review.\n\n_Godrej helpdesk_"

    async def none():
        return None

    monkeypatch.setattr(footer, "for_whatsapp", none)
    asyncio.run(
        whatsapp.send_buttons(
            "+910000000000", "Close it?", [{"id": "y", "title": "Yes"}]
        )
    )
    assert "footer" not in sent[3]["interactive"]
    json.dumps(sent)  # every payload stays plain JSON


def test_only_super_admins_change_the_footer():
    calls = {
        (m, r.path[len(access_rules.PREFIX) :])
        for r in footer_settings.router.routes
        for m in r.methods
    }
    assert calls <= access_rules.SUPER_CALLS and not (calls & access_rules.ADMIN_CALLS)
