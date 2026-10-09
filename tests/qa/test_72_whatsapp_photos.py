"""Photos sent on WhatsApp: WhatsApp keeps a photo for about 30 days only, so the chat bot saves its own copy the moment
it arrives (case_photos), puts it on the case with the request, and the dashboard can show it. Meta, the email and the
model are fake, as everywhere in this harness."""

import json
import types
import uuid

import pytest
from fastapi import HTTPException

from app.admin_panel import cases as panel_cases
from app.services import case_ops, config_store, whatsapp
from tests.qa.harness import _patch, needs_qa, qa_run

JPEG = b"\xff\xd8\xff\xe0 a pretend photo"


def meta_gives(
    w,
    *,
    mime="image/jpeg",
    size=2048,
    data=JPEG,
    download_fails=False,
    info_fails=False,
):
    """Stand in for Meta's two calls: what the file is, then the file itself."""
    asked = []

    async def info(media_id):
        asked.append(media_id)
        if info_fails:
            raise RuntimeError("Meta did not answer")
        return {
            "id": media_id,
            "url": "https://meta.example/file",
            "mime_type": mime,
            "file_size": size,
        }

    async def download(url):
        if download_fails:
            raise RuntimeError("could not download")
        return data

    _patch(w, whatsapp, "media_info", info)
    _patch(w, whatsapp, "download_media", download)
    return asked


async def send_photo(w, who, media_id="MEDIA1", caption=None):
    phone = who["phone"]
    image = {"id": media_id, "mime_type": "image/jpeg"}
    if caption:
        image["caption"] = caption
    before = len(w.sent)
    res = await w.wa_post(w.wa_payload(phone, msg_type="image", extra={"image": image}))
    assert res.status_code == 200
    return [m["text"] for m in w.sent[before:] if m["to"] == phone and m.get("text")]


async def saved(w):
    return [
        dict(r) for r in await w.pools[w.kinds[0]].fetch("SELECT * FROM case_photos")
    ]


@needs_qa
def test_a_photo_sent_on_whatsapp_is_saved_in_our_own_database():
    async def scenario(w):
        asked = meta_gives(w)
        me = await w.user("member")
        await w.login("member")
        told = await send_photo(w, me)
        rows = await saved(w)
        assert asked == ["MEDIA1"] and len(rows) == 1
        row = rows[0]
        assert (
            bytes(row["data"]) == JPEG
            and row["mime_type"] == "image/jpeg"
            and row["size_bytes"] == len(JPEG)
        )
        assert (
            row["source"] == "whatsapp"
            and row["source_ref"] == "MEDIA1"
            and row["case_id"] is None
        )
        assert str(row["org_id"]) == str(me["org_id"]) and str(row["user_id"]) == str(
            me["user_id"]
        )
        assert (
            told and "Got the photo" in told[0]
        )  # waiting for the request it is for, as on Telegram

    qa_run(scenario)


@needs_qa
def test_the_saved_photo_goes_on_the_case_with_the_request():
    async def scenario(w):
        meta_gives(w)
        me = await w.user("member")
        await w.login("member")
        await send_photo(w, me)
        (row,) = await saved(w)
        ref = f"db:{row['id']}"
        case_id = uuid.uuid4()
        await w.run(
            "INSERT INTO cases (id, org_id, case_number, title) VALUES ($1, $2, 'CS-1', 'Leak')",
            case_id,
            me["org_id"],
        )
        ctx = {
            "org_id": me["org_id"],
            "source_key": me["source_key"],
            "user": me,
            "fields": {"_photos": [ref, "a-telegram-file-id"]},
            "case_id": str(case_id),
        }
        await case_ops._op_attach_photos({"case_id": "$case_id"}, ctx)
        photo = await w.one("SELECT case_id FROM case_photos WHERE id = $1", row["id"])
        assert photo["case_id"] == case_id
        acts = [
            json.loads(r["payload"])
            for r in await w.pools[w.kinds[0]].fetch(
                "SELECT payload FROM case_activity WHERE case_id = $1 AND activity_type = 'evidence'",
                case_id,
            )
        ]
        assert {"photo_id": str(row["id"])} in acts and {
            "telegram_file_id": "a-telegram-file-id"
        } in acts

    qa_run(scenario)


@needs_qa
def test_a_photo_that_is_too_big_is_not_saved_and_the_person_is_told_the_limit():
    async def scenario(w):
        meta_gives(w, size=9 * 1024 * 1024)
        me = await w.user("member")
        await w.login("member")
        told = await send_photo(w, me)
        assert not await saved(w)
        limit = config_store.LIMITS["photo_max_mb"][0]
        assert told and "too big" in told[0] and f"{limit} MB" in told[0]

    qa_run(scenario)


@needs_qa
def test_the_organisations_own_limit_decides_what_is_too_big():
    async def scenario(w):
        await w.run(
            "UPDATE orgs SET settings = coalesce(settings, '{}'::jsonb) || $1::jsonb",
            json.dumps({"limits": {"photo_max_mb": 10}}),
        )
        config_store.invalidate()
        meta_gives(w, size=9 * 1024 * 1024)
        me = await w.user("member")
        await w.login("member")
        await send_photo(w, me)
        assert len(await saved(w)) == 1

    qa_run(scenario)


@needs_qa
@pytest.mark.parametrize(
    "gives",
    [
        {"mime": "image/gif"},
        {"mime": "application/pdf"},
        {"download_fails": True},
        {"info_fails": True},
    ],
    ids=["gif", "pdf", "download fails", "meta does not answer"],
)
def test_a_photo_that_cannot_be_saved_is_told_so_and_nothing_is_kept(gives):
    async def scenario(w):
        meta_gives(w, **gives)
        me = await w.user("member")
        await w.login("member")
        told = await send_photo(w, me)
        assert not await saved(w)
        assert told and "couldn't save that photo" in told[0]

    qa_run(scenario)


@needs_qa
def test_a_voice_note_or_a_document_is_answered_not_ignored():
    async def scenario(w):
        me = await w.user("member")
        await w.login("member")
        for kind in ("audio", "document", "location", "video"):
            before = len(w.sent)
            res = await w.wa_post(
                w.wa_payload(me["phone"], msg_type=kind, extra={kind: {"id": "X"}})
            )
            assert res.status_code == 200
            told = [
                m["text"]
                for m in w.sent[before:]
                if m["to"] == me["phone"] and m.get("text")
            ]
            assert told == [
                "I can only read text and photos here. Please type your message or send a photo."
            ], kind

    qa_run(scenario)


@needs_qa
def test_a_reaction_to_a_message_is_still_ignored_quietly():
    async def scenario(w):
        me = await w.user("member")
        before = len(w.sent)
        res = await w.wa_post(
            w.wa_payload(
                me["phone"], msg_type="reaction", extra={"reaction": {"emoji": "👍"}}
            )
        )
        assert res.status_code == 200 and len(w.sent) == before

    qa_run(scenario)


async def case_with_photo(w, mime="image/jpeg"):
    me = await w.user("member")
    case_id, photo_id = uuid.uuid4(), uuid.uuid4()
    await w.run(
        "INSERT INTO cases (id, org_id, case_number, title) VALUES ($1, $2, 'CS-2', 'Lift')",
        case_id,
        me["org_id"],
    )
    await w.run(
        "INSERT INTO case_photos (id, org_id, case_id, mime_type, size_bytes, data) VALUES ($1, $2, $3, $4, $5, $6)",
        photo_id,
        me["org_id"],
        case_id,
        mime,
        len(JPEG),
        JPEG,
    )
    ctx = types.SimpleNamespace(
        org_id=me["org_id"], source_key=me["source_key"], need=lambda section: None
    )
    return ctx, case_id, photo_id


@needs_qa
def test_the_dashboard_can_show_a_photo_that_is_on_a_case():
    async def scenario(w):
        ctx, case_id, photo_id = await case_with_photo(w)
        resp = await panel_cases.case_photo(ctx, case_id, photo_id)
        assert resp.body == JPEG and resp.media_type == "image/jpeg"
        assert resp.headers["x-content-type-options"] == "nosniff"
        with pytest.raises(
            HTTPException
        ) as nope:  # a photo of another case is not found under this one
            await panel_cases.case_photo(ctx, uuid.uuid4(), photo_id)
        assert nope.value.status_code == 404

    qa_run(scenario)


@needs_qa
def test_a_stored_file_that_is_not_a_picture_is_never_handed_to_the_browser():
    async def scenario(w):
        ctx, case_id, photo_id = await case_with_photo(w, mime="text/html")
        with pytest.raises(HTTPException) as nope:
            await panel_cases.case_photo(ctx, case_id, photo_id)
        assert nope.value.status_code == 404

    qa_run(scenario)


# ---------------------------------------------------------------- telling the people on the case, with the photo


async def tell_the_case(w, door_open):
    """A request with a photo is saved; the person on the case is told. Returns (what WhatsApp got, the pictures sent)."""
    from app.services import reach
    from tests.qa.test_70_whatsapp_door import mail_box

    mail_box(w)
    pictures = []

    async def image(to, data, mime_type="image/jpeg", caption=""):
        pictures.append({"to": to, "data": data, "mime": mime_type})
        return {"messages": [{"id": "wamid.IMG"}]}

    _patch(w, whatsapp, "send_image", image)
    meta_gives(w)
    me = await w.user("member")
    helper = await w.user("admin")
    await w.login("member")
    await reach.record_inbound(me["phone"])
    if door_open:
        await reach.record_inbound(helper["phone"])
    await send_photo(w, me)
    (row,) = await saved(w)
    case_id = uuid.uuid4()
    await w.run(
        "INSERT INTO cases (id, org_id, case_number, title) VALUES ($1, $2, 'CS-3', 'Gate')",
        case_id,
        me["org_id"],
    )
    await w.run(
        "INSERT INTO case_parties (org_id, case_id, user_id, party_role, added_by) VALUES ($1, $2, $3, 'helper', $4)",
        me["org_id"],
        case_id,
        helper["user_id"],
        me["user_id"],
    )
    ctx = {
        "org_id": me["org_id"],
        "source_key": me["source_key"],
        "user": me,
        "case": {"id": str(case_id), "case_number": "CS-3", "title": "Gate"},
        "fields": {"_photos": [f"db:{row['id']}"]},
        "dry_run": False,
    }
    before = len(w.sent)
    await case_ops._op_notify_parties(
        {
            "message_template": "New case {case_case_number}: {case_title}",
            "with_photos": True,
            "roles": ["helper"],
        },
        ctx,
    )
    texts = [m for m in w.sent[before:] if m["to"] == helper["phone"]]
    return texts, pictures, ctx, helper


@needs_qa
def test_a_person_on_the_case_whose_whatsapp_is_open_gets_the_text_and_the_photo():
    async def scenario(w):
        texts, pictures, ctx, helper = await tell_the_case(w, door_open=True)
        assert [t["text"] for t in texts] == ["New case CS-3: Gate"]
        assert (
            len(pictures) == 1
            and pictures[0]["to"] == helper["phone"]
            and pictures[0]["data"] == JPEG
        )
        assert not w.emails and not ctx.get("_notes")

    qa_run(scenario)


@needs_qa
def test_a_person_on_the_case_whose_whatsapp_is_closed_is_emailed_and_the_asker_is_told():
    async def scenario(w):
        texts, pictures, ctx, _helper = await tell_the_case(w, door_open=False)
        assert not texts and not pictures  # nothing started on WhatsApp
        assert len(w.emails) == 1 and "New case CS-3: Gate" in w.emails[0]["text"]
        assert ctx["_notes"] and "WhatsApp is closed" in ctx["_notes"][0]

    qa_run(scenario)
