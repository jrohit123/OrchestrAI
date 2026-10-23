"""Undo in Data & schema (schema.py): a change is undone only while what it made holds no data and no flow uses it."""

import asyncio
import json

from app.admin_panel import access_rules, schema


class Conn:
    """A stand-in for the database: answers by what the query asks."""

    def __init__(self, rows=0, used=(), undone=False):
        self.rows, self.used, self.undone = rows, list(used), undone

    async def fetchval(self, sql, *a):
        if "FROM schema_changes" in sql:
            return 1 if self.undone else None
        return self.rows

    async def fetchrow(self, sql, *a):
        if "FROM record_types" in sql:
            return {"table_name": "parking_slots", "statuses": "[]"}
        if "FROM record_fields" in sql:
            return {"key": "car_number", "storage": "column", "table_name": "parking_slots"}
        return None

    async def fetch(self, sql, *a):
        if "usecases" in sql:
            return []
        return [{"name": n} for n in self.used]


class Ctx:
    org_id = "org"

    def __init__(self, level="admin"):
        self.level = level


NEW_LIST = {"id": "c1", "status": "applied", "sql_down": 'DROP TABLE public."parking_slots"',
            "ops": json.dumps([{"op": "create_record_type", "label": "Parking slot", "plural": "Parking slots"}])}  # fmt: skip


def _plan(conn, change, level="admin"):
    return asyncio.run(schema._undo_plan(conn, Ctx(level), change))


def test_an_empty_unused_new_list_can_be_undone_and_its_table_goes():
    why, acts = _plan(Conn(), NEW_LIST)
    assert why == []
    assert any('DROP TABLE public."parking_slots"' in sql for sql, _ in acts)
    assert any("DELETE FROM record_types" in sql for sql, _ in acts)


def test_a_list_with_rows_or_used_by_a_flow_cannot_be_undone():
    why, _ = _plan(Conn(rows=3), NEW_LIST)
    assert "holds 3 records" in " ".join(why)
    why, _ = _plan(Conn(used=["Book parking"]), NEW_LIST)
    assert "Flows use it: Book parking." in " ".join(why)


def test_a_change_is_undone_once_and_an_undo_line_is_not_undone():
    assert _plan(Conn(undone=True), NEW_LIST)[0] == ["It was undone already."]
    undo_line = {"id": "c2", "status": "applied", "sql_down": "", "ops": [{"op": "undo", "of": "c1"}]}
    assert _plan(Conn(), undo_line)[0] == ["This line is itself an undo."]


def test_a_new_column_is_undone_only_while_empty():
    change = {"id": "c3", "status": "applied", "sql_down": "", "ops": [{"op": "add_field", "record_type": "Parking slot", "field": {"label": "Car number"}}]}
    why, acts = _plan(Conn(), change)
    assert why == [] and any('DROP COLUMN "car_number"' in sql for sql, _ in acts)
    assert "filled in on 2 records" in " ".join(_plan(Conn(rows=2), change)[0])


def test_only_a_super_admin_undoes_a_switch_and_admins_may_call_undo():
    change = {"id": "c4", "status": "applied", "sql_down": "", "ops": [{"op": "set_field_active", "record_type": "x", "key": "y", "active": False}]}
    assert _plan(Conn(), change, "admin")[0] and _plan(Conn(), change, "super")[0] == []
    assert ("POST", "/schema/undo/{change_id}") in access_rules.ADMIN_CALLS
