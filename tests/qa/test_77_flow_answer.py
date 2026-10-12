"""The answer of a WhatsApp Flow (the in-panel menu): the workflow chosen there is taken like a tap on a menu row. An
answer without a workflow, or with something that is not a workflow's key, is left alone. Meta and the model are
fake, as everywhere in this harness."""

import json

from app.routers import webhook
from tests.qa.harness import _patch, needs_qa, qa_run


def flow_answer(w, phone, answer):
    return w.wa_payload(
        phone,
        msg_type="interactive",
        extra={
            "interactive": {
                "type": "nfm_reply",
                "nfm_reply": {
                    "name": "flow",
                    "body": "Sent",
                    "response_json": answer
                    if isinstance(answer, str)
                    else json.dumps(answer),
                },
            }
        },
    )


async def handled_after(w, answer):
    seen = []

    async def handle_message(phone, text, msg_type="text", attachments=None, form=None):
        seen.append(text)

    _patch(w, webhook, "handle_message", handle_message)
    phone = w.ids.phone_member
    reply = await w.wa_post(flow_answer(w, phone, answer))
    assert reply.status_code == 200
    return seen


@needs_qa
def test_the_workflow_chosen_in_a_flow_is_handled_like_a_menu_tap():
    async def scenario(w):
        seen = await handled_after(w, {"flow_token": "t", "workflow": "view_all_cases"})
        assert seen == ["view_all_cases"]

    qa_run(scenario)


@needs_qa
def test_a_flow_answer_with_nothing_to_do_is_left_alone():
    async def scenario(w):
        assert await handled_after(w, {"flow_token": "t", "other": "x"}) == []

    qa_run(scenario)


@needs_qa
def test_a_flow_answer_that_is_not_a_workflow_key_or_not_json_is_left_alone():
    async def scenario(w):
        assert await handled_after(w, {"workflow": "x; drop table cases"}) == []
        assert await handled_after(w, "not json at all") == []
        assert await handled_after(w, ["a", "list"]) == []

    qa_run(scenario)


@needs_qa
def test_a_filled_complaint_form_reaches_the_chat_bot_as_one_message_with_its_photos():
    async def scenario(w):
        seen = []

        async def handle_message(
            phone, text, msg_type="text", attachments=None, form=None
        ):
            seen.append((text, attachments, form))

        _patch(w, webhook, "handle_message", handle_message)
        phone = w.ids.phone_member
        answer = {
            "flow_token": "complaint:abc",
            "location": "T5-901",
            "problem": "Leakage in bathroom",
            "priority": "urgent",
            "photos": [{"id": "media-1"}],
        }
        reply = await w.wa_post(flow_answer(w, phone, answer))
        assert reply.status_code == 200
        text, attachments, form = seen[0]
        assert (
            text == "file_a_complaint"
        )  # the complaint workflow, with the answers handed along
        assert (
            form["data"]["problem"] == "Leakage in bathroom"
            and form["data"]["priority"] == "urgent"
        )
        assert attachments == ["wa:media-1"]

    qa_run(scenario)


async def flow_world(w, settings):
    """The menu is asked for with /start; Meta's Flow send is fake and records what it was asked."""
    import json as _json

    from app.services import config_store, whatsapp

    await w.run(
        "UPDATE orgs SET settings = COALESCE(settings, '{}'::jsonb) || $1::jsonb",
        _json.dumps(settings),
    )
    config_store.invalidate()
    sent = []

    async def send_flow(to, **kw):
        sent.append({"to": to, **kw})
        return {}

    _patch(w, whatsapp, "send_flow", send_flow)
    await w.login("member")
    return sent


@needs_qa
def test_the_menu_is_sent_as_a_panel_when_it_is_set_up_and_as_the_list_when_it_is_not():
    async def scenario(w):
        phone = w.ids.phone_member
        sent = await flow_world(w, {})
        await w.say(phone, "/start")
        assert sent == [] and [
            m for m in w.sent if m["to"] == phone and m["kind"] == "list"
        ]

        w.sent.clear()
        sent = await flow_world(
            w, {"whatsapp_flows": {"menu": {"enabled": True, "flow_id": "123"}}}
        )
        await w.say(phone, "/start")
        assert len(sent) == 1 and sent[0]["to"] == phone and sent[0]["flow_id"] == "123"
        assert not [m for m in w.sent if m["kind"] == "list"]  # not both

    qa_run(scenario)


@needs_qa
def test_cancelling_a_draft_also_clears_the_chats_copy_so_the_same_workflow_can_start_again():
    async def scenario(w):
        from app.redis_client import get_session

        user = await w.make_pending(
            "member", "file_a_complaint", {}, stage="collecting"
        )
        session_id = f"{user['org_id']}:{user['phone']}"
        assert (await get_session(session_id)).get("pending_action")
        await w.login("member")
        await w.say(user["phone"], "/cancel")
        assert not (await get_session(session_id)).get("pending_action")

    qa_run(scenario)


@needs_qa
def test_typed_words_that_only_say_complaint_open_the_form_instead_of_the_questions():
    async def scenario(w):
        from app.redis_client import get_session
        from app.services import flows

        sent = await flow_world(
            w,
            {
                "whatsapp_flows": {
                    "complaint": {
                        "enabled": True,
                        "flow_id": "456",
                        "workflow": "file_a_complaint",
                    }
                }
            },
        )

        async def schema(user, intent_key):
            return {"priority": {"enum": ["urgent", "low"]}}

        _patch(w, flows, "_complaint_schema", schema)
        phone = w.ids.phone_member

        async def run_agent(text, user, phone, **kw):
            # the chat bot starts the complaint with nothing filled in: it would ask the questions
            return (
                "Please provide these details!",
                [],
                {
                    "pending_action": {
                        "intent_key": "file_a_complaint",
                        "stage": "collecting",
                        "fields": {},
                    }
                },
            )

        _patch(w, webhook, "run_agent", run_agent)
        await w.say(phone, "I would like to add a complaint")
        assert len(sent) == 1 and sent[0]["screen"] == "COMPLAINT"
        assert not [m for m in w.sent if "Please provide" in m.get("text", "")]
        user = await w.user("member")
        session = await get_session(f"{user['org_id']}:{phone}")
        assert not session.get("pending_action")

    qa_run(scenario)
