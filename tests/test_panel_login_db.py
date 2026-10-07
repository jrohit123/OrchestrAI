"""The dashboard sign-in tables: migrations/control/control-0001_panel_login.sql.

The file goes to the routing (control) database only. The tests that need a database use the
throwaway databases of test_migrate.py (MIGRATE_TEST_PG, a Postgres on this computer)."""

import shutil

import asyncpg
import pytest

from tests.test_migrate import needs_pg
from tools import migrate

FILE = migrate.MIGRATIONS_DIR / "control" / "control-0001_panel_login.sql"
TABLES = ("panel_accounts", "panel_keys", "panel_audit")


def test_the_file_is_a_plain_control_file():
    catalog = migrate.load_catalog(migrate.MIGRATIONS_DIR)
    mine = [m for m in catalog.control if m.version == "control-0001"]
    assert len(mine) == 1
    assert not mine[0].allow_destructive and not mine[0].no_transaction
    for client in ("godrej", "baanganga", "anything"):
        assert "control-0001" not in [m.version for m in catalog.for_tenant(client)]


def test_the_file_only_adds():
    text = FILE.read_text(encoding="utf-8")
    for table in TABLES:
        assert f"CREATE TABLE IF NOT EXISTS public.{table}" in text
    # nothing existing is touched: no ALTER, no UPDATE of someone's rows, no other table
    code_lines = [x for x in text.splitlines() if not x.strip().startswith("--")]
    body = "\n".join(code_lines).upper()
    for word in ("ALTER TABLE", "UPDATE ", "DELETE FROM", "DROP ", "DATA_SOURCES"):
        assert word not in body


def _control_root(tmp_path):
    (tmp_path / "control").mkdir()
    shutil.copy(FILE, tmp_path / "control" / FILE.name)
    return tmp_path


@needs_pg
def test_the_tool_applies_it_to_the_routing_database_only(world, tmp_path):
    root = _control_root(tmp_path)
    code, out = world.run(root, "--apply")
    assert code == 0, out
    for table in TABLES:
        assert world.has_table("control", table)
        assert not world.has_table("alpha", table)
        assert not world.has_table("beta", table)
    assert world.versions("control") == ["control-0001"]
    # the list of clients is untouched
    keys = [
        r["source_key"]
        for r in world.rows("control", "SELECT source_key FROM data_sources")
    ]
    assert sorted(keys) == ["alpha", "beta"]
    # a second run changes nothing
    code, out = world.run(root, "--apply")
    assert code == 0, out
    assert "Applied 0 file(s)" in out


@needs_pg
def test_the_sql_is_safe_to_run_twice_by_hand(world):
    sql = FILE.read_text(encoding="utf-8")
    world.execute("control", sql)
    world.execute(
        "control",
        "INSERT INTO panel_accounts (email, name, level) VALUES ('a@x.test', 'A', 'super')",
    )
    world.execute("control", sql)
    rows = world.rows("control", "SELECT email FROM panel_accounts")
    assert [r["email"] for r in rows] == ["a@x.test"]


@pytest.fixture
def tables(world):
    world.execute("control", FILE.read_text(encoding="utf-8"))
    return world


def add(
    world,
    email="p@x.test",
    level="admin",
    orgs=("godrej",),
    status="invited",
    password=None,
):
    return world.rows(
        "control",
        "INSERT INTO panel_accounts (email, name, level, source_keys, status, password_hash) "
        "VALUES ($1, 'P', $2, $3, $4, $5) RETURNING id",
        email,
        level,
        list(orgs),
        status,
        password,
    )[0]["id"]


@needs_pg
@pytest.mark.parametrize(
    "kwargs",
    [
        {"email": "Upper@x.test"},  # not lower case
        {"email": " pad@x.test"},  # padded
        {"email": ""},
        {"level": "owner"},
        {"status": "locked"},
        {
            "level": "super",
            "orgs": ("godrej",),
        },  # a super admin opens everything: no list
        {
            "level": "admin",
            "orgs": (),
        },  # an admin that can sign in needs an organisation
        {"status": "active", "password": None},  # active means a password was chosen
    ],
)
def test_bad_accounts_are_refused_by_the_database(tables, kwargs):
    with pytest.raises(asyncpg.CheckViolationError):
        add(tables, **kwargs)


@needs_pg
def test_good_accounts_and_the_one_email_rule(tables):
    add(tables, "s@x.test", level="super", orgs=())
    add(tables, "a@x.test", status="active", password="scrypt$x")
    add(
        tables, "off@x.test", orgs=(), status="off"
    )  # switched off: the list may be empty
    with pytest.raises(asyncpg.UniqueViolationError):
        add(tables, "s@x.test", level="super", orgs=())


@needs_pg
def test_keys_session_secrets_are_unique_but_codes_may_repeat(tables):
    account = add(tables)
    sql = (
        "INSERT INTO panel_keys (account_id, kind, key_hash, expires_at) "
        "VALUES ($1, $2, $3, now() + interval '1 hour')"
    )
    tables.execute("control", sql, account, "session", "same")
    with pytest.raises(asyncpg.UniqueViolationError):
        tables.execute("control", sql, account, "session", "same")
    tables.execute("control", sql, account, "signin", "same")
    tables.execute("control", sql, account, "signin", "same")
    with pytest.raises(asyncpg.CheckViolationError):
        tables.execute("control", sql, account, "magic", "x")
    with pytest.raises(asyncpg.CheckViolationError):
        tables.execute(
            "control",
            "INSERT INTO panel_keys (account_id, kind, key_hash, expires_at, tries) "
            "VALUES ($1, 'signin', 'h', now(), -1)",
            account,
        )


@needs_pg
def test_keys_go_with_the_account_but_the_log_stays(tables):
    account = add(tables)
    tables.execute(
        "control",
        "INSERT INTO panel_keys (account_id, kind, key_hash, expires_at) "
        "VALUES ($1, 'session', 'h', now() + interval '1 hour')",
        account,
    )
    tables.execute(
        "control",
        "INSERT INTO panel_audit (account_id, email, action, detail) VALUES ($1, 'p@x.test', 'sign_in', 'ok')",
        account,
    )
    tables.execute(
        "control",
        "INSERT INTO panel_audit (email, action, ok) VALUES ('nobody@x.test', 'sign_in', false)",
    )
    tables.execute("control", "DELETE FROM panel_accounts WHERE id = $1", account)
    assert tables.rows("control", "SELECT count(*) AS n FROM panel_keys")[0]["n"] == 0
    log = tables.rows(
        "control", "SELECT account_id, email FROM panel_audit ORDER BY id"
    )
    assert [r["email"] for r in log] == ["p@x.test", "nobody@x.test"]
    assert all(r["account_id"] is None for r in log)


@needs_pg
def test_who_added_an_account_is_remembered_and_forgotten_safely(tables):
    boss = add(tables, "boss@x.test", level="super", orgs=())
    tables.execute(
        "control",
        "INSERT INTO panel_accounts (email, name, level, source_keys, invited_by) "
        "VALUES ('new@x.test', 'N', 'admin', ARRAY['godrej'], $1)",
        boss,
    )
    tables.execute("control", "DELETE FROM panel_accounts WHERE id = $1", boss)
    row = tables.rows(
        "control", "SELECT invited_by FROM panel_accounts WHERE email = 'new@x.test'"
    )[0]
    assert row["invited_by"] is None


HOUSING_4 = (
    migrate.MIGRATIONS_DIR / "features" / "housing" / "housing-0004_assign_button.sql"
)


def test_the_assign_button_file_reaches_only_godrej():
    catalog = migrate.load_catalog(migrate.MIGRATIONS_DIR)
    assert "housing-0004" in [m.version for m in catalog.for_tenant("godrej")]
    assert "housing-0004" not in [m.version for m in catalog.for_tenant("baanganga")]
    assert "housing-0004" not in [m.version for m in catalog.for_control()]


@needs_pg
def test_the_assign_setting_is_written_once_and_never_overwritten(world):
    import json

    world.execute(
        "alpha",
        "CREATE TABLE orgs (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), name text, settings jsonb)",
    )
    for name, settings in (
        ("has other settings", '{"limits": {"photo_max": 4}}'),
        ("has none", None),
        ("chose another flow", '{"case_buttons": {"assign": "my_flow", "other": 1}}'),
    ):
        world.execute(
            "alpha",
            "INSERT INTO orgs (name, settings) VALUES ($1, $2::jsonb)",
            name,
            settings,
        )
    sql = HOUSING_4.read_text(encoding="utf-8")
    world.execute("alpha", sql)
    world.execute("alpha", sql)  # twice: nothing changes
    got = {
        r["name"]: json.loads(r["settings"])
        for r in world.rows("alpha", "SELECT name, settings FROM orgs")
    }
    assert got["has other settings"] == {
        "limits": {"photo_max": 4},
        "case_buttons": {"assign": "case_pass_on"},
    }
    assert got["has none"] == {"case_buttons": {"assign": "case_pass_on"}}
    assert got["chose another flow"] == {
        "case_buttons": {"assign": "my_flow", "other": 1}
    }
