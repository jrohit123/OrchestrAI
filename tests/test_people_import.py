"""Adding many people from a CSV file: reading the file, checking every row, and saving the kept rows with their role and
seats. The reading tests need no database; the rest run against a throwaway database on this computer (MIGRATE_TEST_PG)."""

import pytest

from app.admin_panel import common, people_import
from tests.test_migrate import needs_pg
from tests.test_panel_roles import ORG, SCHEMA, ctx, run

SEATS = """
CREATE TABLE committee_positions (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), org_id uuid NOT NULL, name text NOT NULL);
CREATE TABLE committee_members (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), org_id uuid NOT NULL,
    user_id uuid NOT NULL REFERENCES users(id), position_id uuid NOT NULL REFERENCES committee_positions(id),
    status text NOT NULL DEFAULT 'active', start_date date, end_date date);
"""

FILE = (
    "Full name;E-mail;Mobile;Role;Responsibilities\n"
    "Ravi Kumar;ravi@example.com;9876543210;Member;Secretary\n"
    "Asha Rao;asha@example.com;;Member;\n"
    "Dup One;dup@example.com;;member;\n"
    "Dup Two;DUP@example.com;;member;\n"
    "No Mail;not-an-email;;member;\n"
    "Odd Role;odd@example.com;;Astronaut;Treasurer; Ghost\n"
)


def test_the_file_is_read_whatever_the_separator_and_column_names():
    columns, data = people_import.read_csv("﻿" + FILE)
    assert set(columns) == {"name", "email", "phone", "role", "seat"}
    assert len(data) == 6
    columns, data = people_import.read_csv("Name,Email\nA B,a@b.co\n")
    assert columns == {"name": 0, "email": 1} and data == [["A B", "a@b.co"]]


@pytest.mark.parametrize(
    "text, word",
    [
        ("", "empty"),
        ("Name,Email\n", "at least one person"),
        ("Name,Role\nA,B\n", "Email column"),
        ("Name,Email\n" + "a,b@c.de\n" * 501, "Up to 500"),
    ],
)
def test_a_bad_file_is_told_in_words(text, word):
    with pytest.raises(ValueError, match=word):
        people_import.read_csv(text)


def test_numbers_need_a_country_code_unless_one_is_given():
    assert people_import.clean_number("+91 98765-43210", "") == "+919876543210"
    assert people_import.clean_number("9876543210", "+91") == "+919876543210"
    assert people_import.clean_number("00447911123456", "") == "+447911123456"
    with pytest.raises(ValueError):
        people_import.clean_number("9876543210", "")


async def _world(conn):
    await conn.execute(SCHEMA)
    await conn.execute(SEATS)
    await conn.execute("ALTER TABLE users ALTER COLUMN channel SET DEFAULT 'whatsapp'")
    common._channel_cache.clear()
    roles = {}
    for n in ("member", "committee"):
        roles[n] = await conn.fetchval(
            "INSERT INTO roles (org_id, name) VALUES ($1, $2) RETURNING id", ORG, n
        )
    seats = {}
    for n in ("Secretary", "Treasurer"):
        seats[n] = await conn.fetchval(
            "INSERT INTO committee_positions (org_id, name) VALUES ($1, $2) RETURNING id",
            ORG,
            n,
        )
    await conn.execute(
        "INSERT INTO users (org_id, role_id, name, email) VALUES ($1, $2, 'Asha Rao', 'asha@example.com')",
        ORG,
        roles["member"],
    )
    return roles, seats


def _ctx():
    c = ctx()
    c.caps["seats"] = True
    return c


@needs_pg
def test_every_row_is_checked_before_anything_is_saved(world):
    async def work(conn):
        await _world(conn)
        out = await people_import.preview(
            _ctx(), people_import.PreviewBody(csv_text=FILE, country="+91")
        )
        rows = {r["name"]: r for r in out["rows"]}
        assert (
            rows["Ravi Kumar"]["ok"] and rows["Ravi Kumar"]["phone"] == "+919876543210"
        )
        assert (
            rows["Ravi Kumar"]["role_id"] and rows["Ravi Kumar"]["seat_ids"] == []
        )  # a Seat column is ignored: seats are not used any more
        assert not any("seat" in n.lower() for r in rows.values() for n in r["notes"])
        assert (
            not rows["Asha Rao"]["ok"]
            and "already here" in rows["Asha Rao"]["problems"][0]
        )
        assert rows["Dup One"]["ok"] and not rows["Dup Two"]["ok"]
        assert not rows["No Mail"]["ok"]
        odd = rows["Odd Role"]
        assert (
            odd["ok"]
            and odd["role_id"] is None
            and any("Astronaut" in n for n in odd["notes"])
        )
        assert (
            await conn.fetchval("SELECT count(*) FROM users") == 1
        )  # nothing was written
        assert out["ok"] == 3

    run(world, work)


@needs_pg
def test_kept_rows_are_added_with_their_role_seats_are_ignored_and_a_bad_row_does_not_stop_the_rest(
    world,
):
    async def work(conn):
        roles, seats = await _world(conn)
        row = lambda line, name, email, role, seat=(): people_import.ImportRow(
            line=line, name=name, email=email, role_id=role, seat_ids=list(seat)
        )
        out = await people_import.commit(
            _ctx(),
            people_import.CommitBody(
                rows=[
                    row(
                        2,
                        "Ravi Kumar",
                        "ravi@example.com",
                        roles["committee"],
                        [seats["Secretary"]],
                    ),
                    row(3, "Asha Again", "ASHA@example.com", roles["member"]),
                    row(4, "Mina Joshi", "mina@example.com", roles["member"]),
                ]
            ),
        )
        assert [a["name"] for a in out["added"]] == ["Ravi Kumar", "Mina Joshi"]
        assert out["skipped"][0]["line"] == 3
        held = await conn.fetchval(
            "SELECT count(*) FROM committee_members WHERE position_id = $1 AND status = 'active'",
            seats["Secretary"],
        )
        assert held == 0  # a seat sent by an old screen is ignored
        role = await conn.fetchval(
            "SELECT r.name FROM users u JOIN roles r ON r.id = u.role_id WHERE u.email = 'ravi@example.com'"
        )
        assert role == "committee"

    run(world, work)


def test_an_excel_file_is_read_like_a_csv():
    import io

    import openpyxl

    book = openpyxl.Workbook()
    sheet = book.active
    sheet.append(["Name", "Email", "Phone", "Role"])
    sheet.append(
        ["Asha Rao", "asha@example.test", 9876543210, "owner"]
    )  # a number typed as a number
    sheet.append([None, None, None, None])  # an empty row is skipped
    sheet.append(["Ravi Kumar", "ravi@example.test", "+91 98765 00002", "staff"])
    buf = io.BytesIO()
    book.save(buf)
    columns, rows = people_import.read_upload(xlsx=buf.getvalue())
    assert set(columns) >= {"name", "email", "phone", "role"}
    assert [r[columns["phone"]] for r in rows] == ["9876543210", "+91 98765 00002"]
    assert people_import.read_upload("Name,Email\nA,a@example.test")[1] == [
        ["A", "a@example.test"]
    ]


def test_a_file_that_is_not_a_csv_or_excel_is_told_in_words():
    with pytest.raises(ValueError, match="CSV or an Excel"):
        people_import.read_upload("PK\x03\x04\x00\x00binary")
    with pytest.raises(ValueError, match="cannot be read"):
        people_import.read_upload(xlsx=b"not an excel file")


def test_the_dashboard_never_offers_seats():
    from app.admin_panel import meta

    assert meta.shown_caps({"seats": True, "cases": True}) == {
        "seats": False,
        "cases": True,
    }
    assert "seats" not in [
        t["key"]
        for s in meta._sections(meta.shown_caps({"seats": True}))
        for t in s.get("tabs", [])
    ]
