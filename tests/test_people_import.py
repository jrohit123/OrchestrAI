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
            rows["Ravi Kumar"]["role_id"] and len(rows["Ravi Kumar"]["seat_ids"]) == 1
        )
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
def test_kept_rows_are_added_with_role_and_seat_and_a_bad_row_does_not_stop_the_rest(
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
                    row(
                        4,
                        "Mina Joshi",
                        "mina@example.com",
                        roles["member"],
                        [seats["Secretary"]],
                    ),
                ]
            ),
        )
        assert [a["name"] for a in out["added"]] == ["Ravi Kumar", "Mina Joshi"]
        assert out["skipped"][0]["line"] == 3
        holder = await conn.fetchval(
            "SELECT u.name FROM committee_members m JOIN users u ON u.id = m.user_id "
            "WHERE m.position_id = $1 AND m.status = 'active'",
            seats["Secretary"],
        )
        assert holder == "Ravi Kumar"  # the seat was taken, so Mina's was left alone
        assert out["added"][1]["notes"] and "Ravi Kumar" in out["added"][1]["notes"][0]
        assert (
            await conn.fetchval(
                "SELECT count(*) FROM admin_events WHERE area = 'people'"
            )
            == 3
        )

        out = await people_import.commit(
            _ctx(),
            people_import.CommitBody(
                rows=[
                    row(
                        5,
                        "Sunil Das",
                        "sunil@example.com",
                        roles["member"],
                        [seats["Secretary"]],
                    )
                ],
                replace_seats=True,
            ),
        )
        assert not out["added"][0]["notes"]
        assert (
            await conn.fetchval(
                "SELECT count(*) FROM committee_members WHERE position_id = $1 AND status = 'active'",
                seats["Secretary"],
            )
            == 1
        )

    run(world, work)
