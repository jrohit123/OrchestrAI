"""The parts of the WhatsApp 24-hour feature (app/services/reach.py) that need no database: the words of the
email, the safe HTML, which message only opens the door, and the numbers on the Settings screen. The behaviour with
people, Redis and the flows is tested in tests/qa/test_70_whatsapp_door.py."""

import asyncio

import pytest

from app.admin_panel import org_settings
from app.services import config_store as cs
from app.services import reach
from app.services.messages import MESSAGES


@pytest.fixture(autouse=True)
def _forget():
    cs.invalidate()
    yield
    cs.invalidate()


def test_the_subject_of_the_email_is_the_first_line_of_the_message_without_markdown():
    assert reach._first_line(
        "*Low stock alert:* Cotton has 4 left.\nReorder level is 10."
    ) == ("Low stock alert: Cotton has 4 left.")
    assert reach._first_line("\n\n  _hello_  \nmore") == "hello"
    assert reach._first_line("") == "" and reach._first_line(None) == ""
    assert len(reach._first_line("x" * 500)) == 90


def test_the_email_html_is_escaped_and_only_the_link_becomes_a_link():
    link = "https://wa.me/919876543210?text=Show%20my%20waiting%20messages"
    html_body = reach._paragraphs_html(
        [
            "Kartik sent you this:",
            "<script>alert(1)</script> 5 < 6 & more\nsecond line",
            f"tap this link:\n{link}",
        ],
        link,
    )
    assert "<script>" not in html_body and "&lt;script&gt;" in html_body
    assert "5 &lt; 6 &amp; more<br>second line" in html_body
    assert f'<a href="{link}">{link}</a>' in html_body
    assert html_body.count("<a ") == 1
    assert reach._paragraphs_html(["no link here"], None) == "<p>no link here</p>"


def test_the_ready_message_and_the_got_it_tap_only_open_the_door():
    async def check():
        ready = MESSAGES["hold.ready_text"].text
        return [
            await reach.door_message("alpha", reach.GOT_IT, "interactive"),
            await reach.door_message(
                "alpha", reach.GOT_IT, "text"
            ),  # typed, not tapped: an ordinary message
            await reach.door_message("alpha", f"  {ready.upper()}  ", "text"),
            await reach.door_message("alpha", "hello", "text"),
            await reach.door_message("alpha", "", "text"),
        ]

    assert asyncio.run(check()) == ["got_it", None, "ready", None, None]


def test_a_telegram_person_and_a_switched_off_organisation_are_never_held():
    assert reach.is_whatsapp("+919876543210") and not reach.is_whatsapp("tg:42")
    assert not reach.is_whatsapp("") and not reach.is_whatsapp(None)
    assert reach.feature_on({}) and reach.feature_on(None)
    assert not reach.feature_on({"reach": {"enabled": False}})
    assert reach.feature_on(
        {"reach": {"enabled": "no"}}
    )  # only a real false switches it off
    assert reach.got_it_on({}) and not reach.got_it_on(
        {"reach": {"got_it_button": False}}
    )


def test_every_text_the_feature_uses_is_on_the_messages_screen_with_the_values_it_needs():
    keys = [k for k in MESSAGES if k.startswith("hold.")]
    assert len(keys) == 16
    for key in keys:
        assert MESSAGES[key].group == "hold"
    # the button title must fit WhatsApp's 20 characters, and the link wording must carry its link
    assert len(MESSAGES["hold.got_it_title"].text) <= reach.BUTTON_TITLE_MAX
    assert "{link}" in MESSAGES["hold.email_footer_link"].text
    assert "{link}" not in MESSAGES["hold.email_footer_nolink"].text


def test_the_three_numbers_have_a_box_on_the_settings_screen_and_the_built_in_values():
    fields = {
        f["key"]: f
        for group in org_settings.GROUPS
        if group["key"] == "hold"
        for f in group["fields"]
    }
    assert set(fields) == {"hold_days", "hold_max", "door_margin_minutes"}
    assert (
        cs.LIMITS["hold_days"],
        cs.LIMITS["hold_max"],
        cs.LIMITS["door_margin_minutes"],
    ) == (
        (3, 1, 30),
        (5, 1, 20),
        (60, 1, 600),
    )
    for field in fields.values():
        assert field["label"] and field["unit"] and field["help"]
