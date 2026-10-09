"""The approved WhatsApp template: when a message has to wait because the person has not written in 24 hours, the bot
also sends the organisation's template (chosen in orgs.settings -> reach.template; nothing about it is in the code).
The person taps its button, their WhatsApp opens again and the waiting message arrives. The email stays as the backup.
Meta, the email and the model are fake, as everywhere in this harness."""

from app.redis_client import get_redis
from app.services import reach, whatsapp
from tests.qa.harness import _patch, needs_qa, qa_run
from tests.qa.test_70_whatsapp_door import (
    ALERT,
    door_ago,
    mail_box,
    make_alert_flow,
    run_alert,
    set_limit,
    set_reach,
    two_people,
    waiting,
)

TEMPLATE = {"name": "session_active", "language": "en"}


def templates_go(w, fail_first=0):
    """Meta's template call is fake: it records what was asked, and can fail the first few times."""
    sent = []
    state = {"fails": fail_first}

    async def send_template(to, name, language="en"):
        if state["fails"]:
            state["fails"] -= 1
            raise RuntimeError("Meta refused the template")
        sent.append({"to": to, "name": name, "language": language})
        return {"messages": [{"id": "wamid.TPL"}]}

    _patch(w, whatsapp, "send_template", send_template)
    return sent


async def alert_to_a_closed_door(w, flow, sender, recipient):
    await door_ago(recipient["phone"], 30)  # wrote yesterday, more than 24 hours ago
    return await run_alert(w, flow, sender, recipient["phone"])


@needs_qa
def test_a_message_that_has_to_wait_also_sends_the_chosen_template_once():
    async def scenario(w):
        mail_box(w)
        sent = templates_go(w)
        await set_reach(w, template=TEMPLATE)
        flow = await make_alert_flow(w)
        sender, recipient, _row = await two_people(w)
        await reach.record_inbound(sender["phone"])
        await alert_to_a_closed_door(w, flow, sender, recipient)
        assert sent == [
            {"to": recipient["phone"], "name": "session_active", "language": "en"}
        ]
        assert len(w.emails) == 1 and [
            i["text"] for i in await waiting(recipient["phone"])
        ] == [ALERT]
        await run_alert(w, flow, sender, recipient["phone"])  # a second one soon after
        assert (
            len(sent) == 1
        )  # one template is enough: the person has not been asked twice
        assert (
            len(await waiting(recipient["phone"])) == 2 and len(w.emails) == 2
        )  # but nothing else is skipped

    qa_run(scenario)


@needs_qa
def test_the_hours_between_two_templates_are_the_organisations_own_number():
    async def scenario(w):
        mail_box(w)
        templates_go(w)
        await set_reach(w, template=TEMPLATE)
        await set_limit(w, template_hours=3)
        flow = await make_alert_flow(w)
        sender, recipient, _row = await two_people(w)
        await reach.record_inbound(sender["phone"])
        await alert_to_a_closed_door(w, flow, sender, recipient)
        ttl = await get_redis().ttl(f"tpl:{recipient['phone']}")
        assert 3 * 3600 - 60 <= ttl <= 3 * 3600

    qa_run(scenario)


@needs_qa
def test_with_no_template_chosen_nothing_changes():
    async def scenario(w):
        mail_box(w)
        sent = templates_go(w)
        flow = await make_alert_flow(w)
        sender, recipient, _row = await two_people(w)
        await reach.record_inbound(sender["phone"])
        await alert_to_a_closed_door(w, flow, sender, recipient)
        assert (
            not sent
            and len(w.emails) == 1
            and len(await waiting(recipient["phone"])) == 1
        )

    qa_run(scenario)


@needs_qa
def test_a_person_whose_whatsapp_is_open_is_never_sent_the_template():
    async def scenario(w):
        mail_box(w)
        sent = templates_go(w)
        await set_reach(w, template=TEMPLATE)
        flow = await make_alert_flow(w)
        sender, recipient, _row = await two_people(w)
        await reach.record_inbound(sender["phone"])
        await reach.record_inbound(recipient["phone"])
        await run_alert(w, flow, sender, recipient["phone"])
        assert not sent and not w.emails

    qa_run(scenario)


@needs_qa
def test_if_the_template_fails_the_message_is_still_kept_and_emailed_and_the_next_one_tries_again():
    async def scenario(w):
        mail_box(w)
        sent = templates_go(w, fail_first=1)
        await set_reach(w, template=TEMPLATE)
        flow = await make_alert_flow(w)
        sender, recipient, _row = await two_people(w)
        await reach.record_inbound(sender["phone"])
        result = await alert_to_a_closed_door(w, flow, sender, recipient)
        assert (
            not sent
            and len(w.emails) == 1
            and len(await waiting(recipient["phone"])) == 1
        )
        assert result["status"] == "done"
        await run_alert(w, flow, sender, recipient["phone"])  # Meta works this time
        assert len(sent) == 1

    qa_run(scenario)


@needs_qa
def test_a_tap_on_the_templates_button_delivers_what_was_waiting():
    async def scenario(w):
        mail_box(w)
        templates_go(w)
        await set_reach(w, template=TEMPLATE)
        flow = await make_alert_flow(w)
        sender, recipient, _row = await two_people(w)
        await reach.record_inbound(sender["phone"])
        await alert_to_a_closed_door(w, flow, sender, recipient)
        before = len(w.sent)
        tap = {"button": {"text": "Proceed", "payload": "Proceed"}}
        res = await w.wa_post(
            w.wa_payload(recipient["phone"], msg_type="button", extra=tap)
        )
        assert res.status_code == 200
        got = [m for m in w.sent[before:] if m["to"] == recipient["phone"]]
        assert any(ALERT in m["text"] for m in got), got  # the waiting message arrived
        assert not await waiting(recipient["phone"])
        assert await reach.door_open(
            recipient["phone"], w.key
        )  # and the door is open again

    qa_run(scenario)


@needs_qa
def test_a_tap_when_nothing_is_waiting_is_answered_kindly():
    async def scenario(w):
        me = await w.user("member")
        await w.login("member")
        before = len(w.sent)
        tap = {"button": {"text": "Proceed", "payload": "Proceed"}}
        await w.wa_post(w.wa_payload(me["phone"], msg_type="button", extra=tap))
        told = [
            m["text"]
            for m in w.sent[before:]
            if m["to"] == me["phone"] and m.get("text")
        ]
        assert told == ["You have no waiting messages. 👍"]

    qa_run(scenario)
