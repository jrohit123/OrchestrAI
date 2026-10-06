"""Tests for the Settings screen's backend (app/admin_panel/org_settings.py): what it shows, what
it accepts, and how a save is merged into orgs.settings without disturbing anything else there."""

import copy

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.admin_panel import org_settings as os_
from app.admin_panel import router as panel_router
from app.services import config_store

Body = os_.SettingsBody


def _fields():
    return {(f["section"], f["key"]): f for g in os_.GROUPS for f in g["fields"]}


def _shown(settings, ttl=None):
    return {
        (f["section"], f["key"]): f
        for g in os_.describe(settings, ttl)["groups"]
        for f in g["fields"]
    }


# ------------------------------------------------------------ the catalog


def test_every_number_the_code_reads_has_a_box_on_the_screen():
    boxes = set(_fields())
    assert boxes == set(os_.RANGES)
    assert all(("limits", k) in boxes for k in config_store.LIMITS)
    assert all(("retention", k) in boxes for k in config_store.RETENTION)


def test_every_box_has_words_a_person_can_read():
    for field in _fields().values():
        assert field["label"] and field["unit"] and field["help"]
    for group in os_.GROUPS:
        assert group["label"] and group["intro"]


def test_the_routes_are_registered():
    paths = {
        (r.path, m)
        for r in panel_router.routes
        for m in getattr(r, "methods", ())
        if r.path.endswith("/org-settings")
    }
    assert paths == {
        ("/admin/{org_slug}/api/v2/org-settings", "GET"),
        ("/admin/{org_slug}/api/v2/org-settings", "PUT"),
    }


# ------------------------------------------------------------ what the screen shows


def test_with_nothing_set_every_box_shows_the_built_in_number():
    shown = _shown({})
    assert len(shown) == len(os_.RANGES)
    for (section, key), f in shown.items():
        built_in = os_.RANGES[(section, key)][0]
        assert (f["value"], f["default"], f["custom"]) == (built_in, built_in, False)


def test_a_number_the_organisation_set_is_shown_and_marked():
    shown = _shown(
        {"limits": {"photo_max": 8}, "retention": {"drafts_days": 14}}, ttl=600
    )
    assert (
        shown[("limits", "photo_max")]["value"],
        shown[("limits", "photo_max")]["custom"],
    ) == (8, True)
    assert shown[("retention", "drafts_days")]["value"] == 14
    assert shown[("column", "session_ttl_minutes")]["value"] == 600
    assert shown[("column", "session_ttl_minutes")]["custom"] is True
    assert shown[("limits", "draft_stale_minutes")]["custom"] is False


@pytest.mark.parametrize("junk", [0, -3, "20", None, True, [], {}])
def test_a_bad_number_in_the_settings_shows_the_built_in_one(junk):
    f = _shown({"limits": {"photo_max": junk}})[("limits", "photo_max")]
    assert (f["value"], f["custom"]) == (5, False)


def test_the_session_time_that_equals_the_built_in_one_is_not_custom():
    f = _shown({}, ttl=480)[("column", "session_ttl_minutes")]
    assert (f["value"], f["custom"]) == (480, False)
    assert _shown({}, ttl=None)[("column", "session_ttl_minutes")]["value"] == 480


def test_the_nightly_cleanup_is_on_unless_switched_off():
    def enabled(settings):
        groups = os_.describe(settings, None)["groups"]
        return next(g for g in groups if g["key"] == "retention")["enabled"]

    assert enabled({}) is True
    assert enabled({"retention": {"enabled": False}}) is False
    assert enabled({"retention": {"enabled": None}}) is True


# ------------------------------------------------------------ what it accepts


def test_the_body_takes_only_whole_numbers_and_known_places():
    assert Body(limits={"photo_max": 8}, retention={"enabled": False}).limits == {
        "photo_max": 8
    }
    for bad in (
        {"limits": {"photo_max": True}},  # a yes/no is not a number
        {"limits": {"photo_max": "8"}},
        {"limits": {"photo_max": 2.5}},
        {"retention": {"drafts_days": "7"}},
        {"session_ttl_minutes": 5.5},
        {"something_else": 1},
    ):
        with pytest.raises(ValidationError):
            Body(**bad)


@pytest.mark.parametrize(
    "body",
    [
        {"limits": {"photo_max": 0}},
        {"limits": {"photo_max": 21}},
        {"limits": {"draft_stale_minutes": 4}},
        {"limits": {"nothing_like_this": 3}},
        {"retention": {"drafts_days": 0}},
        {"retention": {"otp_days": 366}},
        {"retention": {"enabled": 3}},
        {"retention": {"made_up": 3}},
        {"session_ttl_minutes": 4},
        {"session_ttl_minutes": 10081},
    ],
)
def test_a_number_outside_its_range_or_an_unknown_name_is_refused(body):
    with pytest.raises(HTTPException) as e:
        os_.check(Body(**body))
    assert e.value.status_code == 400 and e.value.detail


def test_the_edges_of_every_range_are_accepted_and_none_means_the_built_in_number():
    for (section, key), (_, smallest, largest) in os_.RANGES.items():
        for n in (smallest, largest, None):
            body = (
                Body(session_ttl_minutes=n)
                if section == "column"
                else Body(**{section: {key: n}})
            )
            os_.check(body)  # does not raise
    os_.check(Body(retention={"enabled": False}))
    os_.check(Body())


def test_the_refusal_names_the_box_and_the_range():
    with pytest.raises(HTTPException) as e:
        os_.check(Body(limits={"photo_max": 99}))
    assert "Photos kept on one request" in e.value.detail
    assert "between 1 and 20" in e.value.detail


# ------------------------------------------------------------ how a save is merged


def test_a_save_changes_only_what_was_sent_and_leaves_the_rest_of_the_settings_alone():
    old = {
        "case_reminders": {"enabled": True, "table": "cases"},  # someone else's
        "limits": {"photo_max": 8, "reprompt_max": 4},
        "retention": {"otp_days": 2},
    }
    before = copy.deepcopy(old)
    new = os_.merged(old, Body(limits={"photo_max": 6}, retention={"drafts_days": 14}))
    assert new == {
        "case_reminders": {"enabled": True, "table": "cases"},
        "limits": {"photo_max": 6, "reprompt_max": 4},
        "retention": {"otp_days": 2, "drafts_days": 14},
    }
    assert old == before  # the original is not touched


def test_null_goes_back_to_the_built_in_number_and_empty_groups_disappear():
    old = {"limits": {"photo_max": 8}, "retention": {"enabled": False}, "x": 1}
    new = os_.merged(old, Body(limits={"photo_max": None}, retention={"enabled": None}))
    assert new == {"x": 1}


def test_switching_the_cleanup_back_on_needs_no_key():
    old = {"retention": {"enabled": False, "otp_days": 3}}
    assert os_.merged(old, Body(retention={"enabled": True})) == {
        "retention": {"otp_days": 3}
    }
    assert os_.merged({}, Body(retention={"enabled": False})) == {
        "retention": {"enabled": False}
    }


def test_a_save_into_settings_that_hold_something_odd_does_not_fail():
    assert os_.merged({"limits": "oops"}, Body(limits={"photo_max": 6})) == {
        "limits": {"photo_max": 6}
    }
    assert os_.merged({}, Body()) == {}


def test_whatever_is_saved_reads_back_the_same_through_the_code_that_uses_it():
    new = os_.merged(
        {}, Body(limits={"draft_stale_minutes": 45}, retention={"drafts_days": 14})
    )
    assert config_store.limit_of(new, "draft_stale_minutes") == 45
    assert config_store.limit_of(new, "photo_max") == 5
    assert config_store.retention_of(new, "drafts_days") == 14


# ------------------------------------------------------------ the change log line


def test_the_change_log_says_what_changed_in_the_screens_words():
    old = {"limits": {"photo_max": 8}}
    new = os_.merged(old, Body(limits={"photo_max": 6, "draft_stale_minutes": 45}))
    line = os_.summary(old, new, 480, None)
    assert line.startswith("Changed settings: ")
    assert "Photos kept on one request 6 (was 8)" in line
    assert "Drop an unfinished request after 45 (was 30)" in line


def test_the_change_log_notes_the_session_time_and_the_nightly_cleanup():
    new = os_.merged({}, Body(retention={"enabled": False}))
    line = os_.summary({}, new, 480, 600)
    assert "Forget a conversation after 600 (was 480)" in line
    assert "Nightly clean-up off" in line


def test_a_save_that_changes_nothing_says_so():
    assert os_.summary({}, {}, 480, None) == "Saved settings"
