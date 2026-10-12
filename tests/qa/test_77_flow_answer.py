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

    async def handle_message(phone, text, msg_type="text", attachments=None):
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
def test_a_flow_answer_without_a_workflow_is_left_alone():
    async def scenario(w):
        assert await handled_after(w, {"location": "T5-901", "problem": "leak"}) == []

    qa_run(scenario)


@needs_qa
def test_a_flow_answer_that_is_not_a_workflow_key_or_not_json_is_left_alone():
    async def scenario(w):
        assert await handled_after(w, {"workflow": "x; drop table cases"}) == []
        assert await handled_after(w, "not json at all") == []
        assert await handled_after(w, ["a", "list"]) == []

    qa_run(scenario)
