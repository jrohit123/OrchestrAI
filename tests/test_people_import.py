"""Adding and updating many people from a CSV or Excel file: reading the file, finding people who are already here
(by number, then email), filling in what is missing instead of adding them twice, their flats (relation, primary
member, lives here), and the People screen's own flat calls. The reading tests need no database; the rest run
against a throwaway database on this computer (MIGRATE_TEST_PG)."""

from pathlib import Path

import pytest
from fastapi import HTTPException

from app.admin_panel import common, people, people_import
from tests.test_migrate import needs_pg
from tests.test_panel_roles import ORG, SCHEMA, ctx, run

MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "migrations/features/housing/housing-0016_flat_people.sql"
)

# the residents table and its trigger as they are on the live Godrej database before housing-0016
RESIDENTS = """
DROP TABLE residents;
ALTER TABLE users ALTER COLUMN email DROP NOT NULL;
CREATE TABLE IF NOT EXISTS orgs (id uuid PRIMARY KEY, settings jsonb);
CREATE TABLE residents (
    id uuid DEFAULT gen_random_uuid() PRIMARY KEY, org_id uuid NOT NULL, user_id uuid REFERENCES users(id) ON DELETE SET NULL,
    wing text, flat_no text NOT NULL, gender varchar(10),
    residential_status varchar(20) DEFAULT 'tenant' NOT NULL, brokers_name text, first_owner_name text,
    first_owner_mobile text, registration_date date DEFAULT CURRENT_DATE,
    status varchar(20) DEFAULT 'active' NOT NULL, approved_by uuid, suspension_date date,
    created_at timestamptz DEFAULT now(), name text, custom_fields jsonb DEFAULT '{}' NOT NULL,
    CONSTRAINT residents_residential_status_check CHECK (residential_status IN ('tenant', 'first_owner', 'second_owner', 'other')),
    CONSTRAINT residents_status_check CHECK (status IN ('active', 'suspended', 'inactive', 'not_residing')));
CREATE FUNCTION sync_resident_status_to_user() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.status IN ('suspended', 'inactive') AND NEW.user_id IS NOT NULL THEN
    UPDATE users SET is_active = false WHERE id = NEW.user_id;
  ELSIF NEW.status = 'active' AND NEW.user_id IS NOT NULL THEN
    UPDATE users SET is_active = true WHERE id = NEW.user_id;
  END IF;
  RETURN NEW;
END; $$;
CREATE TRIGGER trg_sync_resident_status AFTER INSERT OR UPDATE OF status ON residents
    FOR EACH ROW EXECUTE FUNCTION sync_resident_status_to_user();
"""

SHEET = (
    "Name,Phone,Email,Wing,Flat,Relation,Primary member,Lives here,Role\n"
    "Rajeswari,9000000001,raj@example.test,B,201,Owner,Yes,Yes,\n"  # 2 found by number: email filled, flat added
    "Anil Kapoor,98200 11007,,A,103,Owner,Yes,No,\n"  # 3 found: name changed, now lives elsewhere
    "Anil Kapoor,+91 98200 11007,,B,204,Owner,Yes,No,\n"  # 4 same person, second flat, takes primary from Harish
    "Farah Khan,9820011009,,,B-204,Tenant,Yes,Yes,\n"  # 5 new; tenant cannot be primary; role from the relation
    "Suresh,,v@example.test,,,,,,\n"  # 6 found by email, but the name is someone else's: needs a look
    "Nobody,,,A,1,Owner,Yes,Yes,\n"  # 7 cannot be reached: left out
    "Gopal Das,9820011020,,C,303,Landlord,Yes,No,\n"  # 8 new, relation not known: picked on the screen
    "Rajeswari,9000000001,,B,201,Owner,Yes,Yes,\n"  # 9 the same flat again
)


# ------------------------------------------------------------ no database needed


def test_the_file_is_read_whatever_the_separator_and_column_names():
    columns, data = people_import.read_csv(
        "﻿Full name;Mobile No;E-mail;Tower;Flat No;Relationship;Primary member;Residing;Role\n"
        "Ravi;9876543210;r@example.test;A;101;Owner;Yes;Yes;owner\n"
    )
    assert set(columns) == {
        "name",
        "phone",
        "email",
        "wing",
        "flat",
        "relation",
        "primary",
        "lives",
        "role",
    }
    assert len(data) == 1
    assert people_import.read_csv("Name,Phone\nA B,+919876543210\n")[0] == {
        "name": 0,
        "phone": 1,
    }


@pytest.mark.parametrize(
    "text, word",
    [
        ("", "empty"),
        ("Name,Email\n", "at least one person"),
        ("Name,Role\nA,B\n", "Phone or Email column"),
        ("Name,Email\n" + "a,b@c.de\n" * 501, "Up to 500"),
    ],
)
def test_a_bad_file_is_told_in_words(text, word):
    with pytest.raises(ValueError, match=word):
        people_import.read_csv(text)


def test_numbers_need_a_country_code_unless_one_is_given():
    assert people_import.clean_number("+91 98765-43210", "") == "+919876543210"
    assert people_import.clean_number("9876543210", "+91") == "+919876543210"
    assert people_import.clean_number("919876543210", "+91") == "+919876543210"
    assert people_import.clean_number("00447911123456", "") == "+447911123456"
    with pytest.raises(ValueError):
        people_import.clean_number("9876543210", "")


def test_flats_are_saved_one_way_however_they_are_written():
    fp = people_import.flat_parts
    assert fp("", "a-101") == ("A", "101")
    assert fp(" b ", " 204 ") == ("B", "204")
    assert fp("", "B 204") == ("B", "204")
    assert fp("", "1203") == (None, "1203")
    assert people_import.flat_name("A", "101") == "A-101"
    assert people_import.flat_name(None, "7") == "7"


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


# ------------------------------------------------------------ with a database


async def _world(conn):
    await conn.execute(SCHEMA)
    await conn.execute(RESIDENTS)
    await conn.execute("INSERT INTO orgs (id, settings) VALUES ($1, '{}'::jsonb)", ORG)
    await conn.execute(MIGRATION.read_text(encoding="utf-8"))
    await conn.execute("ALTER TABLE users ALTER COLUMN channel SET DEFAULT 'whatsapp'")
    common._channel_cache.clear()
    common._check_cache.clear()
    roles = {}
    for n in ("owner", "tenant", "admin"):
        roles[n] = await conn.fetchval(
            "INSERT INTO roles (org_id, name) VALUES ($1, $2) RETURNING id", ORG, n
        )
    ids = {}
    for name, phone, email, role in (
        ("Rajeswari", "+919000000001", None, "tenant"),
        ("Anil", "+919820011007", "anil@example.test", "owner"),
        ("Venkatesh", None, "v@example.test", "admin"),
        ("Harish Shah", "+919000000003", None, "owner"),
    ):
        ids[name] = await conn.fetchval(
            "INSERT INTO users (org_id, role_id, name, phone, email) VALUES ($1, $2, $3, $4, $5) RETURNING id",
            ORG,
            roles[role],
            name,
            phone,
            email,
        )
    await conn.execute(
        "INSERT INTO residents (org_id, user_id, wing, flat_no, relation, is_primary, lives_here) VALUES "
        "($1, $2, 'A', '103', 'owner', true, true), ($1, $3, 'B', '204', 'owner', true, false)",
        ORG,
        ids["Anil"],
        ids["Harish Shah"],
    )
    return roles, ids


def _ctx():
    c = ctx()
    c.caps.update({"residents": True, "flat_people": True})
    c.settings = {"labels": {"co_owner": "Co-owner"}}
    return c


async def _preview(text=SHEET):
    return await people_import.preview(
        _ctx(), people_import.PreviewBody(csv_text=text, country="+91")
    )


@needs_pg
def test_people_already_here_are_found_and_only_what_differs_is_listed(world):
    async def work(conn):
        await _world(conn)
        out = await _preview()
        who = {p["name"]: p for p in out["people"]}
        assert set(who) == {
            "Rajeswari",
            "Anil Kapoor",
            "Farah Khan",
            "Suresh",
            "Gopal Das",
        }
        raj = who["Rajeswari"]
        assert raj["status"] == "update" and raj["lines"] == [2, 9]
        assert {c["label"]: (c["old"], c["new"]) for c in raj["changes"]} == {
            "Email": (None, "raj@example.test"),
            "B-201": (None, "Owner, ★ primary member, lives here"),
        }
        assert any("listed twice" in n for n in raj["notes"])
        anil = who["Anil Kapoor"]
        changes = {c["label"]: c for c in anil["changes"]}
        assert changes["Name"]["use"] and changes["Name"]["old"] == "Anil"
        assert changes["A-103"]["old"] == "Owner, ★ primary member, lives here"
        assert changes["A-103"]["new"] == "Owner, ★ primary member, lives elsewhere"
        assert (
            "Harish Shah stops being the primary member of B-204"
            in changes["B-204"]["warn"]
        )
        farah = who["Farah Khan"]
        assert (
            farah["status"] == "new" and farah["role_id"]
        )  # the tenant role, from the relation
        assert any("tenant cannot be the primary" in n for n in farah["notes"])
        suresh = who["Suresh"]
        assert suresh["status"] == "check" and suresh["match"]["name"] == "Venkatesh"
        assert not suresh["changes"][0][
            "use"
        ]  # a different name is never changed by default
        gopal = who["Gopal Das"]
        assert gopal["changes"][1]["needs_relation"] and not gopal["changes"][1]["use"]
        assert [s["line"] for s in out["skipped"]] == [7]
        assert out["counts"]["new"] == 2
        assert (
            await conn.fetchval("SELECT count(*) FROM users") == 4
        )  # nothing was written
        assert await conn.fetchval("SELECT count(*) FROM residents") == 2

    run(world, work)


@needs_pg
def test_saving_fills_in_updates_and_never_adds_anyone_twice(world):
    async def work(conn):
        roles, ids = await _world(conn)
        out = await _preview()
        body = people_import.CommitBody(
            entries=out["entries"], relations={"8": "owner"}
        )
        done = await people_import.commit(_ctx(), body)
        assert sorted(a["name"] for a in done["added"]) == ["Farah Khan", "Gopal Das"]
        assert sorted(u["name"] for u in done["updated"]) == [
            "Anil Kapoor",
            "Rajeswari",
        ]
        assert await conn.fetchval("SELECT count(*) FROM users") == 6
        raj = await conn.fetchrow("SELECT * FROM users WHERE id = $1", ids["Rajeswari"])
        assert raj["email"] == "raj@example.test" and raj["role_id"] == roles["tenant"]
        assert (
            await conn.fetchval("SELECT name FROM users WHERE id = $1", ids["Anil"])
            == "Anil Kapoor"
        )
        assert (
            await conn.fetchval(
                "SELECT name FROM users WHERE id = $1", ids["Venkatesh"]
            )
            == "Venkatesh"
        )
        homes = {
            (r["name"], r["flat"]): (r["relation"], r["is_primary"], r["lives_here"])
            for r in await conn.fetch(
                "SELECT u.name, h.wing || '-' || h.flat_no AS flat, h.relation, h.is_primary, h.lives_here "
                "FROM residents h JOIN users u ON u.id = h.user_id"
            )
        }
        assert homes == {
            ("Rajeswari", "B-201"): ("owner", True, True),
            ("Anil Kapoor", "A-103"): ("owner", True, False),
            ("Anil Kapoor", "B-204"): ("owner", True, False),
            ("Harish Shah", "B-204"): ("owner", False, False),
            ("Farah Khan", "B-204"): ("tenant", False, True),
            ("Gopal Das", "C-303"): ("owner", True, False),
        }
        assert (
            await conn.fetchval(
                "SELECT r.name FROM users u JOIN roles r ON r.id = u.role_id WHERE u.name = 'Gopal Das'"
            )
            == "owner"
        )
        # the same file again: nobody new, nothing to change
        again = await _preview(SHEET.replace("Landlord", "Owner"))
        assert again["counts"]["new"] == 0
        assert {p["name"]: p["status"] for p in again["people"]} == {
            "Rajeswari": "same",
            "Anil Kapoor": "same",
            "Farah Khan": "same",
            "Suresh": "check",
            "Gopal Das": "same",
        }
        await people_import.commit(
            _ctx(), people_import.CommitBody(entries=again["entries"])
        )
        assert await conn.fetchval("SELECT count(*) FROM users") == 6
        assert await conn.fetchval("SELECT count(*) FROM residents") == 6

    run(world, work)


@needs_pg
def test_an_unticked_change_is_not_saved_and_a_ticked_look_is(world):
    async def work(conn):
        _, ids = await _world(conn)
        out = await _preview()
        anil = next(p for p in out["people"] if p["name"] == "Anil Kapoor")
        suresh = next(p for p in out["people"] if p["name"] == "Suresh")
        skip = [c["id"] for c in anil["changes"] if c["label"] == "B-204"]
        body = people_import.CommitBody(
            entries=out["entries"], skip=skip, use=[suresh["changes"][0]["id"]]
        )
        await people_import.commit(_ctx(), body)
        assert (
            await conn.fetchval(
                "SELECT name FROM users WHERE id = $1", ids["Venkatesh"]
            )
            == "Suresh"
        )
        assert not await conn.fetchval(
            "SELECT count(*) FROM residents WHERE user_id = $1 AND flat_no = '204'",
            ids["Anil"],
        )
        assert await conn.fetchval(  # Harish keeps it, because Anil's B-204 line was unticked
            "SELECT is_primary FROM residents WHERE user_id = $1", ids["Harish Shah"]
        )

    run(world, work)


@needs_pg
def test_flats_on_the_people_screen(world):
    async def work(conn):
        _, ids = await _world(conn)
        c = _ctx()
        r = await people.add_home(
            c,
            ids["Rajeswari"],
            people.HomeNew(
                wing="b", flat_no="204 ", relation="co_owner", is_primary=True
            ),
        )
        assert r["took_primary_from"] == ["Harish Shah"]
        with pytest.raises(HTTPException) as e:
            await people.add_home(
                c,
                ids["Rajeswari"],
                people.HomeNew(wing="B", flat_no="204", relation="owner"),
            )
        assert "already linked" in e.value.detail
        home = r["id"]
        with pytest.raises(HTTPException) as e:
            await people.update_home(
                c, ids["Rajeswari"], home, people.HomePatch(relation="tenant")
            )
        assert "tenant cannot be the primary" in e.value.detail
        with pytest.raises(HTTPException) as e:
            await people.update_home(
                c, ids["Rajeswari"], home, people.HomePatch(relation="landlord")
            )
        assert "Relation must be one of" in e.value.detail
        await people.update_home(
            c, ids["Rajeswari"], home, people.HomePatch(lives_here=False)
        )
        flats = await people.list_flats(c)
        b204 = next(f for f in flats["rows"] if f["flat_no"] == "204")
        assert [(p["name"], p["is_primary"]) for p in b204["people"]] == [
            ("Rajeswari", True),
            ("Harish Shah", False),
        ]
        # suspending one of Anil's two homes keeps him on; suspending Rajeswari's only home switches her off
        await people.add_home(
            c, ids["Anil"], people.HomeNew(wing="C", flat_no="1", relation="owner")
        )
        await conn.execute(
            "UPDATE residents SET status = 'suspended' WHERE user_id = $1 AND flat_no = '1'",
            ids["Anil"],
        )
        assert await conn.fetchval(
            "SELECT is_active FROM users WHERE id = $1", ids["Anil"]
        )
        await conn.execute(
            "UPDATE residents SET status = 'suspended' WHERE id = $1", home
        )
        assert not await conn.fetchval(
            "SELECT is_active FROM users WHERE id = $1", ids["Rajeswari"]
        )
        await people.remove_home(c, ids["Rajeswari"], home)
        assert not await conn.fetchval(
            "SELECT count(*) FROM residents WHERE id = $1", home
        )
        assert await conn.fetchval(
            "SELECT count(*) FROM users WHERE id = $1", ids["Rajeswari"]
        )
        events = await conn.fetchval(
            "SELECT count(*) FROM admin_events WHERE area = 'people'"
        )
        assert (
            events == 4
        )  # two flats added, one changed, one removed; refused calls write nothing

    run(world, work)
