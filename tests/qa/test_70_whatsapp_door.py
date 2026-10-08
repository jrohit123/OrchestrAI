"""QA-012 without a template: WhatsApp's 24-hour door.

The bot may start a WhatsApp message to a person only if that person wrote to it in the last 24 hours. These tests
use the stock alert people actually met (a flow step that tells one person something) and the scheduled reports:
who is reachable, what is kept and emailed when the door is closed, what the sender is told, and what happens the
moment the person writes. Email and the model are fake, as everywhere in this harness.
"""

import json
import re
import time

from app.redis_client import get_redis
from app.services import (
    config_store,
    mailer,
    otp_service,
    pdf_engine,
    reach,
    step_interpreter,
)
from tests.qa.harness import _patch, llm_message, needs_qa, qa_run
from tests.qa.test_50_scheduler_and_reports import (
    add_report,
    script_report_text,
    tick,
    utc,
)

ALERT = "Low stock alert: Cotton Roll has 4 left. Reorder level is 10."
READY = "Show my waiting messages"


# ---------------------------------------------------------------- helpers


def mail_box(w):
    """Email is fake: everything that would be sent is kept in w.emails."""
    w.emails = []

    async def send_email(to_email, to_name, subject, text, html=None):
        w.emails.append(
            {
                "to": to_email,
                "name": to_name,
                "subject": subject,
                "text": text,
                "html": html,
            }
        )
        return True

    _patch(w, mailer, "send_email", send_email)


async def set_reach(w, **values):
    """orgs.settings -> reach (the on/off switches and the bot's number)."""
    await w.run(
        "UPDATE orgs SET settings = coalesce(settings, '{}'::jsonb) || $1::jsonb",
        json.dumps({"reach": values}),
    )
    config_store.invalidate()


async def set_limit(w, **values):
    await w.run(
        "UPDATE orgs SET settings = coalesce(settings, '{}'::jsonb) || $1::jsonb",
        json.dumps({"limits": values}),
    )
    config_store.invalidate()


async def door_ago(phone, hours):
    """The person last wrote `hours` ago."""
    await get_redis().set(f"door:{phone}", str(int(time.time() - hours * 3600)))


async def waiting(phone) -> list:
    return await reach._read(phone)


async def make_alert_flow(w):
    """What the ZZ test flow does: one notify.user step to one person."""
    steps = [
        {
            "op": "notify.user",
            "params": {
                "to": "$fields.recipient",
                "message_template": "Low stock alert: {item} has {qty} left. Reorder level is {reorder}.",
            },
        }
    ]
    await w.run(
        "INSERT INTO workflows (org_id, intent_key, name, steps, is_active, workflow_type, kind) "
        "VALUES ($1, 'zz_alert', 'ZZ test: stock alert', $2::jsonb, true, 'action', 'workflow')",
        w.ids.org_id,
        json.dumps(steps),
    )
    return dict(await w.one("SELECT * FROM workflows WHERE intent_key = 'zz_alert'"))


async def run_alert(w, flow, sender, recipient_phone):
    return await step_interpreter.run_workflow_steps(
        flow,
        {"recipient": recipient_phone, "item": "Cotton Roll", "qty": 4, "reorder": 10},
        sender,
        sender["phone"],
    )


async def two_people(w, sender="admin", recipient="member"):
    s, r = await w.user(sender), await w.user(recipient)
    row = await w.one("SELECT name, email FROM users WHERE phone = $1", r["phone"])
    return s, r, row


# ---------------------------------------------------------------- the door


@needs_qa
def test_a_person_who_just_wrote_is_reachable_and_the_door_closes_after_23_hours():
    async def scenario(w):
        user = await w.user("member")
        phone, key, org = user["phone"], user["source_key"], user["org_id"]
        assert not await reach.door_open(
            phone, key, org
        )  # nothing is known: they never wrote
        await reach.record_inbound(phone)
        assert await reach.door_open(phone, key, org)
        await door_ago(phone, 22)
        assert await reach.door_open(phone, key, org)
        # 24 hours is WhatsApp's rule; one hour is kept in hand (door_margin_minutes)
        await door_ago(phone, 23.5)
        assert not await reach.door_open(phone, key, org)
        await set_limit(w, door_margin_minutes=10)
        assert await reach.door_open(
            phone, key, org
        )  # 23.5 h is inside 24 h less 10 minutes

    qa_run(scenario)


@needs_qa
def test_a_telegram_person_is_always_reachable_and_the_feature_can_be_switched_off():
    async def scenario(w):
        user = await w.user("member")
        key, org = user["source_key"], user["org_id"]
        assert await reach.door_open(
            "tg:12345", key, org
        )  # Telegram has no 24-hour rule
        assert not await reach.door_open(user["phone"], key, org)
        await set_reach(w, enabled=False)
        assert await reach.door_open(
            user["phone"], key, org
        )  # off: the bot just tries, as it always did

    qa_run(scenario)


@needs_qa
def test_the_chat_log_is_the_second_witness_when_redis_lost_its_notes():
    async def scenario(w):
        user = await w.user("member")
        phone, key, org = user["phone"], user["source_key"], user["org_id"]
        assert not await reach.door_open(phone, key, org)
        await w.run(
            "INSERT INTO audit_log (org_id, user_id, intent_key, tier, input_text, outcome, created_at) "
            "VALUES ($1, $2, 'x', 1, 'hello', 'success', now() - interval '2 hours')",
            user["org_id"],
            user["user_id"],
        )
        assert await reach.door_open(
            phone, key, org
        )  # their last logged message was 2 hours ago

    qa_run(scenario)


@needs_qa
def test_every_kind_of_message_opens_the_door_not_only_text():
    async def scenario(w):
        user = await w.user("member")
        assert not await reach.door_open(
            user["phone"], user["source_key"], user["org_id"]
        )
        payload = w.wa_payload(
            user["phone"], msg_type="image", extra={"image": {"id": "m1"}}
        )
        assert (await w.wa_post(payload)).status_code == 200
        assert await reach.door_open(user["phone"], user["source_key"], user["org_id"])

    qa_run(scenario)


# ---------------------------------------------------------------- the stock alert, door open


@needs_qa
def test_an_alert_to_someone_who_wrote_arrives_on_whatsapp_with_a_got_it_button():
    async def scenario(w):
        mail_box(w)
        flow = await make_alert_flow(w)
        sender, recipient, _row = await two_people(w)
        await reach.record_inbound(recipient["phone"])
        result = await run_alert(w, flow, sender, recipient["phone"])
        assert result["status"] == "done"
        got = [m for m in w.sent if m["to"] == recipient["phone"]]
        assert [m["kind"] for m in got] == ["buttons"] and got[0]["text"] == ALERT
        assert got[0]["buttons"] == [{"id": reach.GOT_IT, "title": "👍 Got it"}]
        assert not w.emails and "WhatsApp is closed" not in result["message"]

    qa_run(scenario)


@needs_qa
def test_the_got_it_button_can_be_switched_off_and_a_long_message_goes_without_one():
    async def scenario(w):
        mail_box(w)
        sender, recipient, _row = await two_people(w)
        key, org = recipient["source_key"], recipient["org_id"]
        await reach.record_inbound(recipient["phone"])
        await set_reach(w, got_it_button=False)
        await reach.deliver_text(
            recipient["phone"], ALERT, source_key=key, org_id=org, sender=sender
        )
        await set_reach(w, got_it_button=True)
        await reach.deliver_text(
            recipient["phone"], "x" * 1100, source_key=key, org_id=org, sender=sender
        )
        kinds = [m["kind"] for m in w.sent if m["to"] == recipient["phone"]]
        assert kinds == ["text", "text"]

    qa_run(scenario)


@needs_qa
def test_a_stock_alert_to_yourself_is_delivered_because_you_just_wrote_to_start_it():
    async def scenario(w):
        flow = await make_alert_flow(w)
        sender = await w.user("admin")
        await reach.record_inbound(sender["phone"])  # the message that started the flow
        await run_alert(w, flow, sender, sender["phone"])
        assert ALERT in w.texts_to(sender["phone"])

    qa_run(scenario)


# ---------------------------------------------------------------- the stock alert, door closed


@needs_qa
def test_an_alert_to_someone_whose_door_is_closed_is_kept_and_emailed_and_the_sender_is_told():
    async def scenario(w):
        mail_box(w)
        flow = await make_alert_flow(w)
        sender, recipient, row = await two_people(w)
        await reach.record_inbound(sender["phone"])
        await door_ago(
            recipient["phone"], 30
        )  # wrote yesterday, more than 24 hours ago
        result = await run_alert(w, flow, sender, recipient["phone"])
        # nothing was started on WhatsApp: it would be accepted and never delivered
        assert not [m for m in w.sent if m["to"] == recipient["phone"]]
        # the whole alert went by email
        assert len(w.emails) == 1
        mail = w.emails[0]
        assert mail["to"] == row["email"] and mail["subject"] == ALERT
        assert ALERT in mail["text"]
        assert (
            "WhatsApp could not deliver this" in mail["text"]
            and "send any message to the chat bot" in mail["text"]
        )
        # it is kept for when they write, and the person who asked is told the truth instead of "Done"
        assert [i["text"] for i in await waiting(recipient["phone"])] == [ALERT]
        assert result["status"] == "done"
        assert f"{row['name']}'s WhatsApp is closed" in result["message"]
        assert "I emailed it to them" in result["message"]

    qa_run(scenario)


@needs_qa
def test_the_email_has_a_one_tap_link_that_opens_whatsapp_with_the_ready_message():
    async def scenario(w):
        mail_box(w)
        sender, recipient, _row = await two_people(w)
        await set_reach(w, whatsapp_number="+91 98765 43210")
        await reach.deliver_text(
            recipient["phone"],
            ALERT,
            source_key=recipient["source_key"],
            org_id=recipient["org_id"],
            sender=sender,
        )
        link = "https://wa.me/919876543210?text=Show%20my%20waiting%20messages"
        mail = w.emails[0]
        assert link in mail["text"] and "tap this link and press Send" in mail["text"]
        assert f'<a href="{link}">' in mail["html"]
        assert sender["user_name"] in mail["text"]  # who sent it

    qa_run(scenario)


@needs_qa
def test_a_person_without_an_email_is_not_emailed_and_the_sender_is_told_that():
    async def scenario(w):
        mail_box(w)
        flow = await make_alert_flow(w)
        sender, recipient, _row = await two_people(w)
        await w.run("UPDATE users SET email = '' WHERE phone = $1", recipient["phone"])
        result = await run_alert(w, flow, sender, recipient["phone"])
        assert not w.emails and await waiting(recipient["phone"])
        assert "there is no email address on file" in result["message"]

    qa_run(scenario)


@needs_qa
def test_with_the_feature_switched_off_the_alert_is_sent_as_before_even_to_a_closed_door():
    async def scenario(w):
        mail_box(w)
        flow = await make_alert_flow(w)
        sender, recipient, _row = await two_people(w)
        await set_reach(w, enabled=False)
        result = await run_alert(w, flow, sender, recipient["phone"])
        assert ALERT in w.texts_to(recipient["phone"]) and not w.emails
        assert "WhatsApp is closed" not in result["message"]

    qa_run(scenario)


@needs_qa
def test_a_telegram_person_is_sent_the_alert_as_before():
    async def scenario(w):
        mail_box(w)
        sender = await w.user("admin")
        out = await reach.deliver_text(
            "tg:555",
            ALERT,
            source_key=sender["source_key"],
            org_id=sender["org_id"],
            sender=sender,
        )
        assert (
            out["status"] == "sent" and w.texts_to("tg:555") == [ALERT] and not w.emails
        )

    qa_run(scenario)


# ---------------------------------------------------------------- the person writes


@needs_qa
def test_when_the_person_writes_the_kept_alert_is_sent_and_the_sender_is_told():
    async def scenario(w):
        mail_box(w)
        flow = await make_alert_flow(w)
        sender, recipient, row = await two_people(w)
        await reach.record_inbound(sender["phone"])
        await run_alert(
            w, flow, sender, recipient["phone"]
        )  # door closed: kept and emailed
        before = len(w.sent)
        await w.wa_post(
            w.wa_payload(recipient["phone"], READY)
        )  # they tap the link and press Send
        got = [m for m in w.sent[before:] if m["to"] == recipient["phone"]]
        assert len(got) == 1 and got[0]["kind"] == "buttons"
        assert got[0]["text"].startswith("📬 You have 1 waiting message(s):")
        assert re.search(
            rf"\*{sender['user_name']}\* \(\d\d/\d\d \d\d:\d\d\): {re.escape(ALERT)}",
            got[0]["text"],
        )
        told = [m["text"] for m in w.sent[before:] if m["to"] == sender["phone"]]
        assert told == [
            f"✅ {row['name']} wrote to me, so I sent them your message on WhatsApp."
        ]
        assert not await waiting(recipient["phone"])  # delivered once, not again
        await w.wa_post(w.wa_payload(recipient["phone"], READY))
        again = [m["text"] for m in w.sent if m["to"] == recipient["phone"]]
        assert again[-1] == "You have no waiting messages. 👍"

    qa_run(scenario)


@needs_qa
def test_the_sender_is_not_messaged_when_their_own_door_is_closed():
    async def scenario(w):
        mail_box(w)
        flow = await make_alert_flow(w)
        sender, recipient, _row = await two_people(w)
        await reach.record_inbound(sender["phone"])
        await run_alert(w, flow, sender, recipient["phone"])
        await door_ago(
            sender["phone"], 40
        )  # by the time the person writes, the sender's door has closed
        before = len(w.sent)
        await w.wa_post(w.wa_payload(recipient["phone"], READY))
        assert not [m for m in w.sent[before:] if m["to"] == sender["phone"]]
        assert [
            m for m in w.sent[before:] if m["to"] == recipient["phone"]
        ]  # they still get theirs

    qa_run(scenario)


@needs_qa
def test_a_tap_on_got_it_opens_the_door_and_sends_what_is_waiting_with_no_answer_of_its_own():
    async def scenario(w):
        mail_box(w)
        sender, recipient, _row = await two_people(w)
        await reach.deliver_text(
            recipient["phone"],
            ALERT,
            source_key=recipient["source_key"],
            org_id=recipient["org_id"],
            sender=sender,
        )
        before = len(w.sent)
        await w.wa_post(
            w.wa_payload(
                recipient["phone"],
                msg_type="interactive",
                extra={
                    "interactive": {
                        "type": "button_reply",
                        "button_reply": {"id": reach.GOT_IT, "title": "x"},
                    }
                },
            )
        )
        got = [m["text"] for m in w.sent[before:] if m["to"] == recipient["phone"]]
        assert (
            len(got) == 1 and ALERT in got[0]
        )  # only the kept alert: no reply to the tap itself
        assert await reach.door_open(
            recipient["phone"], recipient["source_key"], recipient["org_id"]
        )

    qa_run(scenario)


@needs_qa
def test_at_most_the_newest_few_are_kept_and_the_wording_comes_from_the_messages_screen():
    async def scenario(w):
        mail_box(w)
        sender, recipient, _row = await two_people(w)
        await set_limit(w, hold_max=2)
        await w.run(
            "INSERT INTO system_messages (key, locale, scope, scope_ref, version, body, variables, is_active, note, created_by) "
            "VALUES ('hold.waiting_intro', 'en-IN', 'tenant', '', 1, 'Waiting: {count}', '[]'::jsonb, true, 'test', 'test')"
        )
        config_store.invalidate()
        for n in (1, 2, 3):
            await reach.deliver_text(
                recipient["phone"],
                f"alert {n}",
                source_key=recipient["source_key"],
                org_id=recipient["org_id"],
                sender=sender,
            )
        assert [i["text"] for i in await waiting(recipient["phone"])] == [
            "alert 2",
            "alert 3",
        ]
        before = len(w.sent)
        await w.wa_post(w.wa_payload(recipient["phone"], READY))
        text = next(m["text"] for m in w.sent[before:] if m["to"] == recipient["phone"])
        assert text.startswith("Waiting: 2")  # the organisation's own words

    qa_run(scenario)


@needs_qa
def test_a_kept_message_that_is_older_than_the_hold_time_is_dropped():
    async def scenario(w):
        mail_box(w)
        sender, recipient, _row = await two_people(w)
        await reach.deliver_text(
            recipient["phone"],
            ALERT,
            source_key=recipient["source_key"],
            org_id=recipient["org_id"],
            sender=sender,
        )
        redis, key = get_redis(), f"waiting:{recipient['phone']}"
        item = json.loads((await redis.lrange(key, 0, -1))[0])
        item["until"] = time.time() - 1  # three days have passed
        await redis.delete(key)
        await redis.rpush(key, json.dumps(item))
        assert not await waiting(recipient["phone"])
        assert (
            await reach.deliver_waiting(
                recipient["phone"], recipient["source_key"], recipient["org_id"]
            )
            == 0
        )

    qa_run(scenario)


# ---------------------------------------------------------------- Meta says it was not delivered after all


@needs_qa
def test_a_late_failed_report_from_meta_keeps_the_message_and_tells_the_sender():
    async def scenario(w):
        mail_box(w)
        flow = await make_alert_flow(w)
        sender, recipient, row = await two_people(w)
        await reach.record_inbound(sender["phone"])
        await reach.record_inbound(recipient["phone"])  # we believe the door is open
        wa_ids = iter(["wamid.ONE", "wamid.TWO"])

        async def answer_with_an_id(to, body, buttons):
            w.sent.append(
                {"to": to, "kind": "buttons", "text": body, "buttons": buttons}
            )
            return {"messages": [{"id": next(wa_ids)}]}

        from app.services import whatsapp

        _patch(w, whatsapp, "send_buttons", answer_with_an_id)
        await run_alert(w, flow, sender, recipient["phone"])
        report = {
            "object": "whatsapp_business_account",
            "entry": [{"changes": [{"field": "messages", "value": {"statuses": [
                {"id": "wamid.ONE", "status": "failed", "recipient_id": recipient["phone"].lstrip("+"),
                 "errors": [{"code": 131047, "title": "Re-engagement message"}]},
                {"id": "wamid.UNKNOWN", "status": "failed", "recipient_id": "1",
                 "errors": [{"code": 131047, "title": "Re-engagement message"}]},
                {"id": "wamid.TWO", "status": "failed", "recipient_id": "1",
                 "errors": [{"code": 131026, "title": "Undeliverable"}]},
            ]}}]}],
        }  # fmt: skip
        assert (await w.wa_post(report)).status_code == 200
        assert (
            len(w.emails) == 1 and ALERT in w.emails[0]["text"]
        )  # only the 131047 one with a record
        assert [i["text"] for i in await waiting(recipient["phone"])] == [ALERT]
        told = [m["text"] for m in w.sent if m["to"] == sender["phone"]]
        assert any(f"{row['name']}'s WhatsApp is closed" in t for t in told)

    qa_run(scenario)


# ---------------------------------------------------------------- scheduled reports


@needs_qa
def test_a_scheduled_report_to_a_closed_door_goes_by_email_and_the_schedule_moves_on():
    async def scenario(w):
        mail_box(w)
        script_report_text(w, "Open cases: 3.")
        user = await add_report(
            w, "member", "daily", utc(2026, 10, 8, 3, 30), open_door=False
        )
        await tick(w, utc(2026, 10, 8, 4, 0))
        assert not [
            m for m in w.sent if m["to"] == user["phone"]
        ]  # nothing started on WhatsApp
        assert len(w.emails) == 1
        mail = w.emails[0]
        assert (
            "Scheduled: Open cases" in mail["subject"]
            and "Open cases: 3." in mail["text"]
        )
        assert (
            "{org_name}" not in mail["text"] and "sent you this:" in mail["text"]
        )  # the automatic wording
        row = await w.one("SELECT next_run_at, run_count FROM scheduled_reports")
        assert row["run_count"] == 1 and row["next_run_at"] == utc(2026, 10, 9, 3, 30)
        # and the newest copy waits for when they write (a second day replaces the first, it does not pile up)
        await tick(w, utc(2026, 10, 9, 4, 0))
        assert len(await waiting(user["phone"])) == 1

    qa_run(scenario)


@needs_qa
def test_a_scheduled_report_to_an_open_door_arrives_on_whatsapp_with_the_got_it_button():
    async def scenario(w):
        mail_box(w)
        script_report_text(w, "Open cases: 3.")
        user = await add_report(
            w, "member", "daily", utc(2026, 10, 8, 3, 30)
        )  # they wrote today
        await tick(w, utc(2026, 10, 8, 4, 0))
        got = [m for m in w.sent if m["to"] == user["phone"]]
        assert [m["kind"] for m in got] == [
            "buttons"
        ] and "Scheduled: Open cases" in got[0]["text"]
        assert got[0]["buttons"][0]["id"] == reach.GOT_IT and not w.emails

    qa_run(scenario)


@needs_qa
def test_a_scheduled_pdf_report_to_a_closed_door_is_emailed_with_the_way_to_get_the_next_ones():
    async def scenario(w):
        mail_box(w)
        pdfs = []

        async def fake_pdf(**kwargs):
            return b"%PDF-1.4 fake"

        async def fake_mail_with_pdf(
            to_email, to_name, subject, body, pdf_bytes, filename, org_name
        ):
            pdfs.append(
                {"to": to_email, "subject": subject, "body": body, "filename": filename}
            )
            return True

        _patch(w, pdf_engine, "generate_pdf", fake_pdf)
        _patch(w, otp_service, "send_email_with_pdf", fake_mail_with_pdf)
        asked = {"n": 0}

        def model(*a, **k):
            asked["n"] += 1
            if (
                asked["n"] == 1
            ):  # the model asks for the PDF on WhatsApp, as it always did
                return llm_message(tool_calls=[{"name": "generate_pdf", "args": {
                    "rows": [{"item": "Cotton Roll", "qty": 4}], "title": "Stock report", "send_via": "whatsapp"}}])  # fmt: skip
            return llm_message(content="Your stock report is ready.")

        w.llm.handler(model)
        user = await add_report(
            w, "member", "daily", utc(2026, 10, 8, 3, 30), open_door=False
        )
        await tick(w, utc(2026, 10, 8, 4, 0))
        # the PDF went by email even though the model asked for WhatsApp, with the way to get the next ones
        assert len(pdfs) == 1 and pdfs[0]["filename"].endswith(".pdf")
        assert (
            "Please find attached" in pdfs[0]["body"]
            and "WhatsApp could not deliver this" in pdfs[0]["body"]
        )
        # nothing on WhatsApp, and no second email that only says "your report is ready"
        assert not [m for m in w.sent if m["to"] == user["phone"]] and not w.emails
        row = await w.one("SELECT run_count FROM scheduled_reports")
        assert row["run_count"] == 1

    qa_run(scenario)


@needs_qa
def test_a_late_failed_report_for_something_the_system_sent_by_itself_uses_the_automatic_wording():
    async def scenario(w):
        mail_box(w)
        user = await w.user("member")
        await reach.record_inbound(user["phone"])
        from app.services import whatsapp

        async def answer_with_an_id(to, body, buttons):
            w.sent.append({"to": to, "kind": "buttons", "text": body})
            return {"messages": [{"id": "wamid.AUTO"}]}

        _patch(w, whatsapp, "send_buttons", answer_with_an_id)
        await reach.deliver_text(
            user["phone"], "Scheduled report text", source_key=user["source_key"], org_id=user["org_id"],
            org_name="QA Housing Society",
        )  # fmt: skip
        report = {"entry": [{"changes": [{"value": {"statuses": [
            {"id": "wamid.AUTO", "status": "failed", "recipient_id": user["phone"].lstrip("+"),
             "errors": [{"code": 131047, "title": "Re-engagement message"}]}]}}]}]}  # fmt: skip
        assert (await w.wa_post(report)).status_code == 200
        assert len(w.emails) == 1
        assert (
            "QA Housing Society sent you this:" in w.emails[0]["text"]
        )  # not "X sent you this message from X"

    qa_run(scenario)


# ---------------------------------------------------------------- "send this PDF / sheet to <person>"


async def forward_a_file(
    w, recipient_phone, door_open, email_on_file=True, tool="generate_pdf"
):
    """The member asks the bot to send a report to another person; returns what the model was told
    the tool did (that is what it repeats to the asker)."""
    mail_box(w)
    files = []

    async def fake_pdf(**kwargs):
        return b"%PDF-1.4 fake"

    def fake_sheet(rows, title, subtitle=""):  # the real sheet maker is not async
        return b"PK fake sheet"

    async def fake_mail_with_pdf(
        to_email, to_name, subject, body, pdf_bytes, filename, org_name
    ):
        files.append(
            {"to": to_email, "subject": subject, "body": body, "filename": filename}
        )
        return True

    from app.services import excel_engine

    _patch(w, pdf_engine, "generate_pdf", fake_pdf)
    _patch(w, excel_engine, "generate_excel", fake_sheet)
    _patch(w, otp_service, "send_email_with_pdf", fake_mail_with_pdf)
    asker = await w.user("member")
    await w.login("member")
    await reach.record_inbound(asker["phone"])
    if door_open:
        await reach.record_inbound(recipient_phone)
    if not email_on_file:
        await w.run("UPDATE users SET email = '' WHERE phone = $1", recipient_phone)
    seen = {"n": 0}

    def model(*a, **k):
        seen["n"] += 1
        if seen["n"] == 1:
            return llm_message(tool_calls=[{"name": tool, "args": {
                "rows": [{"item": "Cotton Roll", "qty": 4}], "title": "Stock report",
                "forward_to": recipient_phone, "forward_to_name": "Rajeswari"}}])  # fmt: skip
        return llm_message(content="Done.")

    w.llm.handler(model)
    before = len(w.sent)
    await w.say(asker["phone"], "send the stock report to Rajeswari")
    told = [m["text"] for m in w.sent[before:] if m["to"] == asker["phone"]]
    return files, " ".join(told)


@needs_qa
def test_a_pdf_sent_to_someone_who_wrote_goes_on_whatsapp():
    async def scenario(w):
        recipient = await w.user("admin")
        files, told = await forward_a_file(w, recipient["phone"], door_open=True)
        docs = [
            m
            for m in w.sent
            if m["to"] == recipient["phone"] and m["kind"] == "document"
        ]
        assert len(docs) == 1 and not files and not w.emails
        assert (
            told == ""
        )  # a file that went on WhatsApp needs no word from the bot, as before

    qa_run(scenario)


@needs_qa
def test_a_pdf_sent_to_someone_whose_door_is_closed_is_emailed_to_them_and_the_asker_is_told():
    async def scenario(w):
        recipient = await w.user("admin")
        row = await w.one(
            "SELECT name, email FROM users WHERE phone = $1", recipient["phone"]
        )
        files, told = await forward_a_file(w, recipient["phone"], door_open=False)
        assert not [
            m for m in w.sent if m["to"] == recipient["phone"]
        ]  # nothing started on WhatsApp
        assert (
            len(files) == 1
            and files[0]["to"] == row["email"]
            and files[0]["filename"].endswith(".pdf")
        )
        assert "WhatsApp could not deliver this" in files[0]["body"]
        assert (
            f"{row['name']}'s WhatsApp is closed" in told
            and "I emailed it to them." in told
        )

    qa_run(scenario)


@needs_qa
def test_a_pdf_for_someone_closed_with_no_email_is_not_pretended_to_be_sent():
    async def scenario(w):
        recipient = await w.user("admin")
        files, told = await forward_a_file(
            w, recipient["phone"], door_open=False, email_on_file=False
        )
        assert not files and not [m for m in w.sent if m["to"] == recipient["phone"]]
        assert "no email address on file" in told and "It was not sent." in told

    qa_run(scenario)


@needs_qa
def test_a_sheet_sent_to_someone_whose_door_is_closed_is_emailed_too():
    async def scenario(w):
        recipient = await w.user("admin")
        files, told = await forward_a_file(
            w, recipient["phone"], door_open=False, tool="generate_excel"
        )
        assert len(files) == 1 and files[0]["filename"].endswith(".xlsx")
        assert "I emailed it to them." in told

    qa_run(scenario)
