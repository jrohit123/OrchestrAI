"""Tests for the numbers an organisation can change (orgs.settings.limits) and the reader that
gives them to the code (config_store.org_settings / limit_of).

The promise being tested: with nothing set, every number is exactly the one the code always used.
"""

import asyncio
import datetime

import pytest

from app.services import agent, case_ops
from app.services import config_store as cs

# the numbers that were written into the code before they became settings
BUILT_IN = {
    "draft_stale_minutes": 30,
    "confirm_stale_minutes": 10,
    "reprompt_max": 3,
    "photo_max": 5,
    "photo_max_mb": 5,  # new with photos on WhatsApp
    "photo_hold_minutes": 15,
    "reminder_max_failures": 3,  # new with the case-reminder fix (QA-011)
    "turn_wait_seconds": 15,  # new with the one-message-at-a-time fix (QA-003, QA-021)
    "turn_lock_seconds": 90,
    "hold_days": 3,  # new with the WhatsApp 24-hour fix (QA-012)
    "hold_max": 5,
    "door_margin_minutes": 60,
}


@pytest.fixture(autouse=True)
def _forget():
    cs.invalidate()
    yield
    cs.invalidate()


def _rows(monkeypatch, settings, counter=None):
    async def fetch(sql, *args, source_key):
        if counter is not None:
            counter.append((sql, args, source_key))
        if isinstance(settings, Exception):
            raise settings
        return [{"settings": settings}]

    monkeypatch.setattr(cs, "_fetch", fetch)


# ------------------------------------------------------------ the built-in numbers


def test_the_built_in_numbers_are_the_ones_the_code_always_used():
    assert {k: v[0] for k, v in cs.LIMITS.items()} == BUILT_IN
    for default, smallest, largest in {**cs.LIMITS, **cs.RETENTION}.values():
        assert smallest <= default <= largest


@pytest.mark.parametrize("name", BUILT_IN)
def test_with_nothing_set_a_limit_is_the_built_in_number(name):
    assert cs.limit_of(None, name) == BUILT_IN[name]
    assert cs.limit_of({}, name) == BUILT_IN[name]
    assert cs.limit_of({"limits": {}}, name) == BUILT_IN[name]


@pytest.mark.parametrize("junk", [0, -1, "20", None, True, [], {}, float("nan")])
def test_a_typo_never_changes_a_limit(junk):
    assert cs.limit_of({"limits": {"photo_max": junk}}, "photo_max") == 5


def test_a_limit_is_a_whole_number_and_is_the_organisations_own_when_set():
    assert cs.limit_of({"limits": {"photo_max": 8}}, "photo_max") == 8
    assert cs.limit_of({"limits": {"photo_max": 8.9}}, "photo_max") == 8
    with pytest.raises(KeyError):
        cs.limit_of({}, "no_such_limit")  # a mistake in the code shows at once


# ------------------------------------------------------------ when a draft goes stale


def _draft(stage, minutes_old):
    made = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
        minutes=minutes_old
    )
    return {"stage": stage, "created_at": made.isoformat()}


@pytest.mark.parametrize(
    ("stage", "minutes_old", "stale"),
    [
        ("collecting", 29, False),
        ("collecting", 31, True),
        ("awaiting_confirmation", 9, False),
        ("awaiting_confirmation", 11, True),
        ("done", 999, False),  # only drafts being filled in can go stale
    ],
)
def test_a_draft_goes_stale_after_the_built_in_time(stage, minutes_old, stale):
    assert agent._is_draft_stale(_draft(stage, minutes_old)) is stale
    assert agent._is_draft_stale(_draft(stage, minutes_old), {}) is stale


def test_an_organisation_can_give_drafts_more_time():
    settings = {"limits": {"draft_stale_minutes": 60, "confirm_stale_minutes": 30}}
    assert agent._is_draft_stale(_draft("collecting", 31), settings) is False
    assert agent._is_draft_stale(_draft("collecting", 61), settings) is True
    assert agent._is_draft_stale(_draft("awaiting_confirmation", 11), settings) is False
    assert agent._is_draft_stale(_draft("awaiting_confirmation", 31), settings) is True


def test_a_draft_with_no_time_on_it_is_never_stale():
    assert agent._is_draft_stale({"stage": "collecting"}) is False
    assert agent._is_draft_stale(None) is False


# ------------------------------------------------------------ the reader


def test_the_organisations_settings_are_read_once_and_kept(monkeypatch):
    asked = []
    _rows(monkeypatch, '{"limits": {"photo_max": 7}}', asked)  # arrives as text

    async def scenario():
        first = await cs.org_settings("alpha", "org-1")
        second = await cs.org_settings("alpha", "org-1")
        other_org = await cs.org_settings("alpha", "org-2")
        return first, second, other_org

    first, second, other_org = asyncio.run(scenario())
    assert first == second == other_org == {"limits": {"photo_max": 7}}
    assert [a[1] for a in asked] == [("org-1",), ("org-2",)]  # org-1 only once
    assert all(a[2] == "alpha" for a in asked)


def test_a_save_shows_at_once_after_the_cache_is_forgotten(monkeypatch):
    holder = {"value": {"limits": {"photo_max": 7}}}

    async def fetch(sql, *args, source_key):
        return [{"settings": holder["value"]}]

    monkeypatch.setattr(cs, "_fetch", fetch)

    async def scenario():
        before = await cs.org_settings("alpha", "org-1")
        holder["value"] = {"limits": {"photo_max": 9}}
        still = await cs.org_settings("alpha", "org-1")  # kept
        cs.invalidate("beta")  # another database: no effect
        still_too = await cs.org_settings("alpha", "org-1")
        cs.invalidate("alpha")
        now = await cs.org_settings("alpha", "org-1")
        return before, still, still_too, now

    before, still, still_too, now = asyncio.run(scenario())
    assert before == still == still_too == {"limits": {"photo_max": 7}}
    assert now == {"limits": {"photo_max": 9}}


@pytest.mark.parametrize(
    "stored", [None, "not json", "[1, 2]", 5, RuntimeError("down")]
)
def test_settings_that_are_missing_or_cannot_be_read_give_nothing_set(
    monkeypatch, stored
):
    _rows(monkeypatch, stored)
    assert asyncio.run(cs.org_settings("alpha", "org-1")) == {}


def test_no_database_or_no_organisation_gives_nothing_set():
    assert asyncio.run(cs.org_settings(None, "org-1")) == {}
    assert asyncio.run(cs.org_settings("alpha", None)) == {}


# ------------------------------------------------------------ photos on a case


def _photo_ctx(count):
    return {
        "source_key": "alpha",
        "org_id": "org-1",
        "user": {"user_id": "u-1"},
        "fields": {"_photos": [f"file-{i}" for i in range(count)]},
        "case_id": "case-1",
    }


def _attach(monkeypatch, settings, count):
    saved = []

    async def execute(sql, *args, source_key):
        saved.append(args)

    cs.invalidate()  # each call is a fresh minute: nothing kept from the one before
    _rows(monkeypatch, settings)
    monkeypatch.setattr(case_ops, "execute", execute)
    asyncio.run(case_ops._op_attach_photos({"case_id": "$case_id"}, _photo_ctx(count)))
    return saved


def test_a_case_keeps_up_to_five_photos_unless_the_organisation_says_otherwise(
    monkeypatch,
):
    assert len(_attach(monkeypatch, {}, 8)) == 5
    assert len(_attach(monkeypatch, {"limits": {"photo_max": 2}}, 8)) == 2
    assert len(_attach(monkeypatch, {"limits": {"photo_max": 12}}, 8)) == 8
