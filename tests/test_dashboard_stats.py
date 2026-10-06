"""The optional stat cards and low-stock table on Home (app/admin_panel/dashboard_stats.py):
described entirely by orgs.settings, checked against the organisation's own tables, and never able
to stop Home from opening."""

import asyncio
import json

import pytest

from app.admin_panel import dashboard_stats as ds
from app.admin_panel.common import Ctx
from app.services import step_interpreter

SCHEMA = {
    "invoices": {"id", "org_id", "status", "amount"},
    "inventory": {"id", "org_id", "name", "qty", "reorder_level"},
}


@pytest.fixture
def db(monkeypatch):
    """A pretend database: every query is written down, and the answer is what the test set."""
    seen = {"one": [], "all": [], "answer": {"val": 7}, "stock": []}

    async def allowlist(source_key):
        return SCHEMA

    async def fetch_one(sql, *args, source_key):
        seen["one"].append((sql, args))
        return seen["answer"]

    async def fetch_all(sql, *args, source_key):
        seen["all"].append((sql, args))
        return seen["stock"]

    monkeypatch.setattr(step_interpreter, "_load_schema_allowlist", allowlist)
    monkeypatch.setattr(ds, "fetch_one", fetch_one)
    monkeypatch.setattr(ds, "fetch_all", fetch_all)
    return seen


def run(coro):
    return asyncio.run(coro)


def test_no_cards_set_up_means_nothing_not_a_zero(db):
    assert run(ds.compute_stats({}, "o1", "alpha")) is None
    assert run(ds.compute_stats({"cards": []}, "o1", "alpha")) is None
    assert db["one"] == []


def test_a_count_card_and_a_sum_card_are_worked_out_from_the_settings(db):
    cfg = {
        "cards": [
            {
                "key": "paid",
                "label": "Paid",
                "table": "invoices",
                "where": {"status": "paid"},
            },
            {
                "key": "revenue",
                "table": "invoices",
                "agg": "sum",
                "column": "amount",
                "format": "currency_inr",
                "color": "#16a34a",
            },
        ]
    }
    got = run(ds.compute_stats(cfg, "o1", "alpha"))
    assert got == [
        {"key": "paid", "label": "Paid", "value": 7, "format": "number", "color": None},
        {
            "key": "revenue",
            "label": "Revenue",
            "value": 7,
            "format": "currency_inr",
            "color": "#16a34a",
        },
    ]
    (count_sql, count_args), (sum_sql, sum_args) = db["one"]
    assert (
        count_sql
        == "SELECT COUNT(*) AS val FROM invoices WHERE org_id = $1 AND status = $2"
    )
    assert count_args == ("o1", "paid")
    assert (
        sum_sql
        == "SELECT COALESCE(SUM(amount), 0) AS val FROM invoices WHERE org_id = $1"
    )
    assert sum_args == ("o1",)


def test_a_card_that_points_at_something_that_does_not_exist_is_left_out(db):
    cfg = {
        "cards": [
            {"key": "a", "table": "nope"},  # no such table
            {
                "key": "b",
                "table": "invoices",
                "agg": "sum",
                "column": "nope",
            },  # no such column
            {
                "key": "c",
                "table": "invoices",
                "where": {"nope": 1},
            },  # no such column to filter on
            {"key": "d", "table": "invoices; DROP TABLE x"},  # not even a name
            {"table": "invoices"},  # no key
            {"key": "ok", "table": "invoices"},
        ]
    }
    got = run(ds.compute_stats(cfg, "o1", "alpha"))
    assert [c["key"] for c in got] == ["ok"]
    assert len(db["one"]) == 1


def test_when_every_card_is_left_out_there_are_no_cards(db):
    assert (
        run(ds.compute_stats({"cards": [{"key": "a", "table": "nope"}]}, "o1", "alpha"))
        is None
    )


def test_the_low_stock_table_lists_what_is_at_or_under_its_reorder_level(db):
    db["stock"] = [{"name": "Ring", "qty": 1, "reorder_level": 2}]
    cfg = {
        "low_stock": {
            "label": "Running low",
            "table": "inventory",
            "qty_column": "qty",
            "reorder_column": "reorder_level",
            "display_columns": ["name", "qty", "reorder_level"],
        }
    }
    got = run(ds.compute_low_stock(cfg, "o1", "alpha"))
    assert got == {
        "title": "Running low",
        "columns": [
            {"key": "name", "label": "Name"},
            {"key": "qty", "label": "Qty"},
            {"key": "reorder_level", "label": "Reorder Level"},
        ],
        "rows": [{"name": "Ring", "qty": 1, "reorder_level": 2}],
    }
    sql, args = db["all"][0]
    assert (
        sql
        == "SELECT name, qty, reorder_level FROM inventory WHERE org_id = $1 AND qty <= reorder_level"
    )
    assert args == ("o1",)


@pytest.mark.parametrize(
    "ls",
    [
        None,
        {"table": "nope", "qty_column": "qty", "reorder_column": "reorder_level"},
        {"table": "inventory", "qty_column": "nope", "reorder_column": "reorder_level"},
        {"table": "inventory", "qty_column": "qty"},  # no reorder column named
    ],
)
def test_a_low_stock_setting_that_does_not_fit_the_tables_shows_nothing(db, ls):
    assert run(ds.compute_low_stock({"low_stock": ls}, "o1", "alpha")) is None
    assert db["all"] == []


def _ctx():
    return Ctx(
        source_key="alpha",
        org_id="o1",
        org_name="Alpha",
        caps={},
        actor="test",
        closed_values=["closed"],
    )


def test_home_gets_both_extras_from_the_organisations_settings(db):
    settings = {"dashboard_stats": {"cards": [{"key": "n", "table": "invoices"}]}}
    db["answer"] = {
        "val": 3,
        "settings": json.dumps(settings),
    }  # the same row answers both questions
    got = run(ds.home_extras(_ctx()))
    assert [c["value"] for c in got["stats"]] == [3]
    assert got["low_stock"] is None


def test_an_organisation_with_no_such_settings_gets_nothing(db):
    db["answer"] = {"settings": None}
    assert run(ds.home_extras(_ctx())) == {"stats": None, "low_stock": None}
    db["answer"] = {"settings": json.dumps({"limits": {}})}
    assert run(ds.home_extras(_ctx())) == {"stats": None, "low_stock": None}


def test_a_problem_in_the_extras_never_stops_home_from_opening(db, monkeypatch):
    async def broken(*a, **k):
        raise RuntimeError("the database is having a moment")

    monkeypatch.setattr(ds, "fetch_one", broken)
    assert run(ds.home_extras(_ctx())) == {"stats": None, "low_stock": None}
