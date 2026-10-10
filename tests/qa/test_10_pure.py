"""QA catalogue cases that need no database and no network: the guards, the gate levels, the yes/no words,
the schedule arithmetic and the SQL guards.

How to read a test name: `test_D01_...` is catalogue case D01 (docs/qa/OrchestrAI-QA-Findings.md, section 7).

A case that FAILS today is kept as `xfail(strict=True)` tagged with its bug ID. It documents the bug and keeps the
suite green. When someone fixes the bug the test starts passing, strict mode turns that into a failure, and the tag
is removed.
"""

import datetime as dt
import re

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.scheduler.jobs import compute_next_run
from app.services import sql_guard
from app.services.step_interpreter import (
    _eval_when_condition,
    _required_levels_for_gate,
)
from app.services.vocabulary import matches_vocab
from tests.qa.seed import VOCAB

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
UTC = dt.timezone.utc


def bug(ident: str, why: str = ""):
    return pytest.mark.xfail(strict=True, reason=f"{ident} {why}".strip())


def when(cond, **fields):
    return _eval_when_condition(cond, {"fields": fields})


# ───────────────────────────── D. workflow engine: `when` guards ─────────────────────────────


@bug("QA-018", "an unknown operator returns True, so the guarded step runs")
def test_D01_unknown_when_operator_does_not_run_the_step():
    assert when({"field": "$fields.a", "equal": "y"}, a="x") is not True


@bug("QA-018", "an `or` group raises KeyError: 'field'")
def test_D02_or_group_is_evaluated():
    assert when({"or": [{"field": "$fields.a", "equals": "x"}]}, a="x") is True


@bug("QA-018", "a condition without a field raises KeyError")
def test_D03_condition_without_field_is_refused_cleanly():
    try:
        result = when({"equals": "x"}, a="x")
    except KeyError:
        pytest.fail("KeyError instead of a clear refusal")
    assert result is False


@bug("QA-018", "the number 1000.0 does not equal 1000 (compared as text)")
def test_D04_equals_treats_1000_and_1000_point_0_as_equal():
    assert when({"field": "$fields.amount", "equals": 1000}, amount=1000.0) is True


@bug("QA-018", "the text 'None' matches a missing value")
def test_D05_equals_none_text_does_not_match_a_missing_value():
    assert when({"field": "$fields.v", "equals": "None"}, v=None) is False


@bug("QA-018", "'1,00,000' is not read as a number, so an amount gate is skipped")
def test_D06_indian_grouping_is_read_as_a_number():
    assert when({"field": "$fields.v", "gte": 100000}, v="1,00,000") is True


@bug("QA-018", "'Rs 5 lakh' is not read, so the amount gate is skipped")
def test_D07_unreadable_amount_is_refused_not_silently_false():
    try:
        result = when({"field": "$fields.v", "gte": 100000}, v="Rs 5 lakh")
    except ValueError:
        return
    assert result is True


@bug(
    "QA-018",
    "a large refund (-500000) is below any gte threshold and needs no approval",
)
def test_D08_a_large_negative_amount_still_meets_an_approval_threshold():
    assert when({"field": "$fields.v", "gte": 100000}, v=-500000) is True


GATE = {
    "levels": [
        {"level": 1, "role": "m", "max_amount": 100000},
        {"level": 2, "role": "d", "max_amount": None},
    ]
}


def test_D09_gate_levels_at_and_just_over_the_ceiling():
    assert [lv["level"] for lv in _required_levels_for_gate(GATE, 100000)] == [1]
    assert [lv["level"] for lv in _required_levels_for_gate(GATE, 100000.01)] == [1, 2]


def test_D10_gate_levels_at_zero_need_the_lowest_level():
    assert [lv["level"] for lv in _required_levels_for_gate(GATE, 0)] == [1]


@settings(max_examples=200, deadline=None)
@given(
    st.floats(min_value=0, max_value=1e9, allow_nan=False),
    st.floats(min_value=0, max_value=1e9, allow_nan=False),
)
def test_D_property_a_bigger_amount_never_needs_fewer_approval_levels(a, b):
    low, high = sorted((a, b))
    assert len(_required_levels_for_gate(GATE, low)) <= len(
        _required_levels_for_gate(GATE, high)
    )


KNOWN = st.sampled_from(
    ["equals", "not_equals", "in", "not_in", "exists", "gte", "lte", "gt", "lt"]
)
VALUES = st.one_of(
    st.none(),
    st.integers(-(10**9), 10**9),
    st.floats(allow_nan=False, allow_infinity=False),
    st.text(max_size=12),
    st.booleans(),
)


@settings(max_examples=300, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(KNOWN, VALUES, VALUES)
def test_D_property_known_operators_always_answer_true_or_false(op, left, right):
    cond = {"field": "$fields.v", op: [right] if op in ("in", "not_in") else right}
    assert isinstance(when(cond, v=left), bool)


UNKNOWN = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz_", min_size=3, max_size=10
).filter(
    lambda s: (
        s
        not in {
            "equals",
            "not_equals",
            "in",
            "not_in",
            "exists",
            "gte",
            "lte",
            "gt",
            "lt",
            "field",
        }
    )
)


@bug("QA-018", "any unknown operator fails open (returns True)")
@settings(max_examples=50, deadline=None)
@given(UNKNOWN, VALUES)
def test_D_property_an_unknown_operator_never_lets_a_step_run(op, value):
    assert when({"field": "$fields.v", op: value}, v="x") is False


# ───────────────────────────── C. yes / no words ─────────────────────────────

CONFIRM = frozenset(VOCAB["confirm_words"])
CANCEL = frozenset(VOCAB["cancel_words"])
CANCEL_TOKENS = frozenset(VOCAB["cancel_tokens"])
FILLERS = frozenset(VOCAB["filler_words"])


@pytest.mark.parametrize(
    "text",
    [
        "yes",
        "Yes!",
        "Yes.",
        "(yes)",
        "ok",
        "okay",
        "sure",
        "yes please",
        "haan",
        "yes save it",
        "ok thanks",
        "haan ji",
        "ji haan",
        "yes yes",
        "theek hai",
    ],
)
def test_C_plain_confirmations_confirm(text):
    assert matches_vocab(text, CONFIRM, FILLERS)


def test_C_a_word_that_only_starts_like_yes_is_not_yes():
    assert not matches_vocab("yesterday", CONFIRM, FILLERS)
    assert not matches_vocab("", CONFIRM, FILLERS)


def test_C03_yes_but_make_it_5000_is_not_a_plain_confirmation():
    assert not matches_vocab("yes but make it 5000", CONFIRM, FILLERS)


def test_C04_no_problem_go_ahead_is_not_a_cancellation():
    assert not matches_vocab("no problem, go ahead", CANCEL, FILLERS)


def test_C05_no_wait_is_not_a_silent_cancel():
    assert not matches_vocab("no, wait", CANCEL, FILLERS)


def test_C06_ok_no_wait_is_not_a_confirmation():
    assert not matches_vocab("ok no wait", CONFIRM, FILLERS)


@pytest.mark.parametrize(
    "text", ["no", "No.", "nahi", "nope", "stop", "please cancel", "no thanks"]
)
def test_C_plain_cancellations_cancel(text):
    assert matches_vocab(text, CANCEL, FILLERS)


@pytest.mark.parametrize(
    "text",
    [
        "cancel invoice INV-1",
        "don't cancel",
        "no issue",
        "nahi, doosra case",
        "yes no",
        "no yes",
    ],
)
def test_C_a_cancel_word_inside_a_longer_message_is_not_a_cancel(text):
    assert not matches_vocab(text, CANCEL_TOKENS, FILLERS)
    assert not matches_vocab(text, CANCEL, FILLERS)


def test_C_the_words_come_from_the_organisation_and_not_from_the_code():
    assert not matches_vocab("yes", frozenset())
    assert not matches_vocab("yes please", CONFIRM)  # without its polite words
    assert matches_vocab("yes please", CONFIRM, frozenset({"please"}))
    assert matches_vocab(
        "\U0001f44d\U0001f3fd", frozenset({"\U0001f44d"})
    )  # an emoji works too


# ───────────────────────────── H. schedules ─────────────────────────────


def utc(y, m, d, h=0, mi=0):
    return dt.datetime(y, m, d, h, mi, tzinfo=UTC)


def ist(value: dt.datetime) -> dt.datetime:
    return value.astimezone(IST)


@bug("QA-010", "hour 0 is treated as 'not set': the report runs at 08:00")
def test_H07_daily_at_midnight_runs_at_midnight_ist():
    nxt = compute_next_run(
        {"schedule_type": "daily", "hour": 0, "minute": 0}, from_dt=utc(2026, 10, 7, 12)
    )
    assert (ist(nxt).hour, ist(nxt).minute) == (0, 0)


@bug("QA-010", "hour 0 on a weekly schedule runs at 09:00")
def test_H08_weekly_monday_midnight_runs_at_midnight_ist():
    nxt = compute_next_run(
        {"schedule_type": "weekly", "hour": 0, "minute": 0, "day_of_week": "mon"},
        from_dt=utc(2026, 10, 7, 12),
    )
    assert (ist(nxt).weekday(), ist(nxt).hour) == (0, 0)


@pytest.mark.parametrize(
    "dom,asked",
    [
        (31, utc(2026, 1, 31, 8)),
        (31, utc(2026, 3, 31, 8)),
        (30, utc(2026, 1, 30, 8)),
        (29, utc(2026, 1, 29, 8)),
    ],
)
@bug(
    "QA-010",
    "the day is kept when the month changes: ValueError: day is out of range for month",
)
def test_H09_monthly_schedule_on_the_29th_to_31st_finds_a_next_run(dom, asked):
    nxt = compute_next_run(
        {"schedule_type": "monthly", "hour": 9, "minute": 0, "day_of_month": dom},
        from_dt=asked,
    )
    assert nxt > asked


def test_H_daily_nine_am_across_the_ist_midnight_boundary():
    asked = utc(2026, 10, 7, 18, 31)  # 00:01 on 8 October in India
    nxt = compute_next_run(
        {"schedule_type": "daily", "hour": 9, "minute": 0}, from_dt=asked
    )
    assert ist(nxt).strftime("%Y-%m-%d %H:%M") == "2026-10-08 09:00"


def test_H_minutely_and_hourly_move_forward():
    asked = utc(2026, 10, 7, 12, 5)
    assert compute_next_run(
        {"schedule_type": "minutely", "interval_minutes": 5}, from_dt=asked
    ) == asked + dt.timedelta(minutes=5)
    assert (
        compute_next_run({"schedule_type": "hourly", "minute": 30}, from_dt=asked)
        > asked
    )


ROWS = st.fixed_dictionaries(
    {
        "schedule_type": st.sampled_from(["daily", "weekly", "monthly"]),
        "hour": st.integers(0, 23),
        "minute": st.integers(0, 59),
        "day_of_week": st.sampled_from(
            ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
        ),
        "day_of_month": st.integers(1, 31),
    }
)


@bug("QA-010", "hour 0 and day 29 to 31 break the next-run calculation")
@settings(max_examples=300, deadline=None)
@given(
    ROWS,
    st.datetimes(
        min_value=dt.datetime(2026, 1, 1),
        max_value=dt.datetime(2028, 12, 31),
        timezones=st.just(UTC),
    ),
)
def test_H_property_a_valid_schedule_always_has_a_next_run_in_the_future(row, asked):
    nxt = compute_next_run(row, from_dt=asked)
    assert nxt > asked
    assert nxt - asked <= dt.timedelta(days=32)
    if row["schedule_type"] == "daily":
        assert (ist(nxt).hour, ist(nxt).minute) == (row["hour"], row["minute"])


# ───────────────────────────── G. the SQL guard for AI-written queries ─────────────────────────────

KW = dict(
    allowed_tables={"users", "cases"},
    org_id="11111111-1111-1111-1111-111111111111",
    org_scoped_tables={"users", "cases"},
    hidden_columns={"phone", "email", "id"},
    private_columns={"phone", "email"},  # personal data: not anywhere in a query
)


def prepared(sql: str) -> str:
    out, _ = sql_guard.prepare(sql, **KW)
    return out


def refused(sql: str) -> bool:
    try:
        sql_guard.prepare(sql, **KW)
    except sql_guard.GuardError:
        return True
    return False


def test_G01_a_hidden_column_is_refused():
    assert refused("SELECT phone FROM users")


def test_G01b_the_refusal_tells_the_ai_to_say_details_are_private_not_that_the_person_is_missing():
    with pytest.raises(sql_guard.GuardError) as why:
        sql_guard.prepare("SELECT name, phone FROM users", **KW)
    text = str(why.value)
    assert "kept private and is not shared in chat" in text
    assert "do not say the person" in text


def test_G02_select_star_is_allowed_by_the_guard_and_left_to_the_caller_to_strip():
    assert not refused("SELECT * FROM users")


def test_G03_a_whole_row_function_is_refused():
    assert refused("SELECT to_jsonb(u) FROM users u")


def test_G04_row_to_json_is_refused():
    assert refused("SELECT row_to_json(users) FROM users")


def test_G05_a_filter_on_a_hidden_column_is_refused():
    assert refused("SELECT name FROM users WHERE phone LIKE '+9190%'")


def test_G06_a_comma_join_into_the_system_catalogue_is_refused():
    assert refused("SELECT name FROM users, pg_catalog.pg_user")


def test_G07_two_statements_are_refused():
    assert refused("SELECT 1; DROP TABLE users")


def test_G08_a_cte_that_exposes_a_hidden_column_is_refused():
    assert refused("WITH x AS (SELECT phone FROM users) SELECT * FROM x")


def test_G09_a_table_function_is_refused():
    assert refused(
        "SELECT name FROM users u JOIN cases c ON true, generate_series(1,3)"
    )


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT phone/**/FROM users",
        'SELECT "phone" FROM users',
        "SELECT PHONE FROM users",
        "SELECT users.phone FROM users",
        "SELECT (phone) FROM users",
        "SELECT coalesce(phone, '') FROM users",
        "SELECT name FROM users -- harmless\nWHERE 1=1; DELETE FROM users",
        "SELECT name, email FROM users",
        "SELECT lower(email) FROM users",
        "SELECT name || phone FROM users",
    ],
)
def test_G10_ways_of_writing_a_hidden_column_are_all_refused(sql):
    assert refused(sql), f"the guard let this through: {sql!r}"


def test_G10b_looking_a_person_up_by_a_hidden_column_is_refused():
    assert refused("SELECT name FROM users WHERE phone = '+919000000001'")


def test_G11_writes_are_refused():
    for sql in (
        "INSERT INTO users (name) VALUES ('x')",
        "UPDATE users SET name = 'x'",
        "DELETE FROM users",
        "WITH d AS (DELETE FROM users RETURNING name) SELECT * FROM d",
        "SELECT name FROM users FOR UPDATE",
    ):
        assert refused(sql), sql


def test_G_the_organisation_filter_is_always_built_in():
    out = prepared("SELECT name FROM users")
    assert "11111111-1111-1111-1111-111111111111" in out or "org_id" in out.lower()
    assert re.search(r"limit\s+\d+", out, re.IGNORECASE)


# ───────────────────────────── P0-3 · personal data and whole rows (QA-008, QA-033) ─────────────────────────────


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT c.title FROM cases c JOIN users u ON u.phone = c.title",
        "SELECT name FROM users ORDER BY phone",
        "SELECT name FROM users GROUP BY name, email",
        "SELECT name FROM users GROUP BY name HAVING max(phone) > '1'",
        "SELECT name FROM users WHERE email IS NOT NULL",
        "SELECT count(*) FROM users WHERE users.phone LIKE '9%'",
        "SELECT name AS phone FROM users",
        "SELECT name FROM users WHERE (users).phone = 'x'",
    ],
)
def test_G13_personal_data_is_refused_in_a_join_a_sort_a_group_a_having_and_a_filter(
    sql,
):
    assert refused(sql), sql


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT u FROM users u",
        "SELECT users FROM users",
        "SELECT to_json(u.*) FROM users u",
        "SELECT row_to_json(u) FROM users u",
        "SELECT jsonb_agg(u) FROM users u",
        "SELECT json_agg(users) FROM users",
        "SELECT (u.*)::text FROM users u",
        "SELECT array_agg(u) FROM users u",
        "WITH x AS (SELECT * FROM users) SELECT to_jsonb(x) FROM x",
        "SELECT to_jsonb(q) FROM (SELECT * FROM users) q",
    ],
)
def test_G14_a_whole_row_in_any_form_is_refused(sql):
    assert refused(sql), sql


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT name FROM users WHERE name ILIKE '%asha%'",
        "SELECT count(*) FROM users",
        (
            "SELECT c.case_number, c.title, u.name FROM cases c JOIN users u ON c.assigned_to_id = u.id "
            "WHERE c.org_id = '11111111-1111-1111-1111-111111111111'"
        ),
        "SELECT u.* FROM users u",
        "SELECT * FROM cases",
        "SELECT status, count(*) FROM cases GROUP BY status ORDER BY count(*) DESC",
        "SELECT coalesce((SELECT count(*) FROM cases), 0) AS n",
        "SELECT name FROM users u JOIN cases c ON c.assigned_to_id = u.id",
    ],
)
def test_G15_the_ordinary_questions_still_work(sql):
    assert not refused(sql), sql


RESIDENT_KW = dict(
    allowed_tables={"residents"},
    org_id="11111111-1111-1111-1111-111111111111",
    org_scoped_tables={"residents"},
    hidden_columns={"phone", "email"},
    private_columns={
        "brokers_name"
    },  # the organisation's own list (orgs.settings -> ai_sql)
    private_patterns=("*mobile*",),
)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT first_owner_mobile FROM residents",
        "SELECT name FROM residents WHERE first_owner_mobile LIKE '9%'",
        "SELECT brokers_name FROM residents",
        "SELECT name FROM residents ORDER BY brokers_name",
        "SELECT tenant_mobile FROM residents",
    ],
)
def test_G16_a_column_the_organisation_listed_is_refused_by_name_and_by_pattern(sql):
    with pytest.raises(sql_guard.GuardError):
        sql_guard.prepare(sql, **RESIDENT_KW)


def test_G17_the_ordinary_columns_of_the_same_table_are_still_available():
    out, _ = sql_guard.prepare("SELECT name, flat_no FROM residents", **RESIDENT_KW)
    assert "flat_no" in out


def test_G18_the_pattern_matcher_is_case_blind_and_ignores_empty_patterns():
    is_private = sql_guard.private_matcher(["Brokers_Name"], ["*Mobile*", "", "  "])
    assert is_private("BROKERS_NAME") and is_private("First_Owner_MOBILE")
    assert not is_private("name") and not is_private("")
