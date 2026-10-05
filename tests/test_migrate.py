"""Tests for tools/migrate.py.

The tests that need a database use a Postgres on THIS computer, given by
MIGRATE_TEST_PG, for example  postgresql://postgres@127.0.0.1:55432/postgres
They create their own throwaway databases and drop them afterwards, and they refuse to
run against a Postgres that is not on this computer. Without MIGRATE_TEST_PG only the
tests that need no database run.

    python -m pytest tests -q
"""

import asyncio
import os
import time
import uuid
from urllib.parse import urlsplit

import asyncpg
import pytest

from tools import migrate

ADMIN = os.environ.get("MIGRATE_TEST_PG", "").strip()
needs_pg = pytest.mark.skipif(
    not ADMIN, reason="set MIGRATE_TEST_PG to a local Postgres to run this test"
)

CORE_1 = "CREATE TABLE IF NOT EXISTS t1 (id serial PRIMARY KEY, a int);\n"


def write(root, rel, text):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


# ------------------------------------------------------------ no database needed


def test_split_keeps_semicolons_inside_quotes_and_bodies():
    sql = """
-- a comment; with a semicolon
CREATE TABLE a (x text DEFAULT 'one;two');
SELECT "we;ird" FROM a;
DO $$ BEGIN PERFORM 1; PERFORM 2; END $$;
/* block ; comment */
INSERT INTO a VALUES (E'it\\'s;');
SELECT 1
"""
    assert len(migrate.split_statements(sql)) == 5


def test_split_code_only_hides_words_in_text_and_comments():
    [(_, code)] = migrate.split_statements("SELECT 'DROP TABLE x' -- RENAME\n")
    assert "DROP" not in code
    assert "RENAME" not in code


@pytest.mark.parametrize(
    "bad", ["\\i other.sql", "SELECT 'oops", "SELECT $$oops", "/* oops", 'SELECT "oops']
)
def test_split_rejects_psql_commands_and_unclosed_quotes(bad):
    with pytest.raises(migrate.MigrationError):
        migrate.split_statements(bad)


@pytest.mark.parametrize(
    ("dsn", "local"),
    [
        ("postgresql://postgres@127.0.0.1:55432/x", True),
        ("postgresql://u:p@localhost/x", True),
        ("postgresql://u:p@[::1]:5432/x", True),
        ("postgres://u:p@db.localhost/x", True),
        ("postgresql:///x?host=/var/run/postgresql", True),
        ("host=localhost dbname=x user=u", True),
        ("postgresql://u:p@junction.proxy.rlwy.net:12345/railway", False),
        ("postgresql://u:p@postgres.railway.internal:5432/railway", False),
        ("postgresql://u:p@10.0.0.5/x", False),
        ("postgresql://u:p@127.0.0.1.evil.example/x", False),
        ("postgresql://u:p@localhost.evil.example/x", False),
        ("postgresql://u:p@localhost,remote.example/x", False),
        ("host=localhost,remote.example dbname=x", False),
        ("postgresql:///x", False),
        ("", False),
    ],
)
def test_only_this_computer_counts_as_local(dsn, local):
    assert migrate.dsn_is_local(dsn) is local


def test_redact_hides_addresses_and_passwords():
    text = "failed: postgresql://u:secret@db.example:5432/x and password=hunter2 ok"
    out = migrate.redact(text)
    for word in ("secret", "hunter2", "db.example"):
        assert word not in out


def test_header_flags_only_read_the_top_comment_lines():
    assert migrate.header_flags("-- no-transaction\n-- more\nSELECT 1;") == {
        "no-transaction"
    }
    assert migrate.header_flags("-- hi\n\n-- allow-destructive\nSELECT 1;") == {
        "allow-destructive"
    }
    assert migrate.header_flags("SELECT 1;\n-- no-transaction\n") == set()


def test_checksum_ignores_line_endings_and_bom(tmp_path):
    a = tmp_path / "a.sql"
    b = tmp_path / "b.sql"
    a.write_bytes(b"SELECT 1;\nSELECT 2;\n")
    b.write_bytes(b"\xef\xbb\xbfSELECT 1;\r\nSELECT 2;\r\n")
    assert migrate.read_sql(a)[1] == migrate.read_sql(b)[1]


def test_file_names_must_follow_the_pattern(tmp_path):
    write(tmp_path, "core/0001_bad.sql", "SELECT 1;")
    with pytest.raises(migrate.MigrationError, match="must look like"):
        migrate.load_catalog(tmp_path)


def test_a_file_must_carry_its_own_folders_prefix(tmp_path):
    write(tmp_path, "core/control-0001_x.sql", "SELECT 1;")
    with pytest.raises(migrate.MigrationError, match="must look like"):
        migrate.load_catalog(tmp_path)


def test_two_files_may_not_share_a_number(tmp_path):
    write(tmp_path, "core/core-0001_a.sql", "SELECT 1;")
    write(tmp_path, "core/core-0001_b.sql", "SELECT 2;")
    with pytest.raises(migrate.MigrationError, match="used twice"):
        migrate.load_catalog(tmp_path)


@pytest.mark.parametrize(
    ("sql", "message"),
    [
        ("BEGIN;\nSELECT 1;\nCOMMIT;", "do not use BEGIN"),
        ("CREATE INDEX CONCURRENTLY i ON t (a);", "CONCURRENTLY"),
        ("DROP TABLE x;", "refuses"),
        ("ALTER TABLE x DROP COLUMN y;", "refuses"),
        ("ALTER TABLE x DROP y;", "refuses"),
        ("ALTER TABLE x RENAME TO z;", "refuses"),
        ("ALTER TABLE x RENAME COLUMN a TO b;", "refuses"),
        ("TRUNCATE x;", "refuses"),
        ("DROP SCHEMA public CASCADE;", "refuses"),
        ("DO $$ BEGIN DROP TABLE x; END $$;", "refuses"),
        (
            "DO $$ BEGIN IF true THEN ALTER TABLE x DROP COLUMN y; END IF; END $$;",
            "refuses",
        ),
        (
            "DO $a$ BEGIN EXECUTE 'x'; DO $$ BEGIN TRUNCATE t; END $$; END $a$;",
            "refuses",
        ),
    ],
)
def test_dangerous_files_are_refused(tmp_path, sql, message):
    write(tmp_path, "core/core-0001_x.sql", sql)
    with pytest.raises(migrate.MigrationError, match=message):
        migrate.load_catalog(tmp_path)


@pytest.mark.parametrize(
    "sql",
    [
        "ALTER TABLE x DROP CONSTRAINT IF EXISTS c, ADD CONSTRAINT c CHECK (a > 0);",
        "ALTER TABLE x ALTER COLUMN a DROP DEFAULT;",
        "ALTER TABLE x ALTER COLUMN a DROP NOT NULL;",
        "DROP INDEX IF EXISTS some_index;",
        "SELECT 'DROP TABLE x';",
        "-- DROP TABLE x\nSELECT 1;",
        'CREATE TABLE x ("rename" int);',
        "DO $$ BEGIN ALTER TABLE x ADD COLUMN y int; DROP INDEX IF EXISTS i; END $$;",
        "SELECT $$it's fine$$;",
    ],
)
def test_ordinary_files_are_not_refused(tmp_path, sql):
    write(tmp_path, "core/core-0001_x.sql", sql)
    assert len(migrate.load_catalog(tmp_path).core) == 1


def test_allow_destructive_marker_lets_a_file_through(tmp_path):
    write(
        tmp_path,
        "core/core-0001_x.sql",
        "-- allow-destructive\nDROP TABLE IF EXISTS x;\n",
    )
    assert migrate.load_catalog(tmp_path).core[0].allow_destructive


def test_features_apply_only_to_listed_clients(tmp_path):
    write(tmp_path, "core/core-0001_a.sql", "SELECT 1;")
    write(tmp_path, "features/housing/feature.json", '{"tenants": ["alpha"]}')
    write(tmp_path, "features/housing/housing-0001_h.sql", "SELECT 1;")
    catalog = migrate.load_catalog(tmp_path)
    assert [m.version for m in catalog.for_tenant("alpha")] == [
        "core-0001",
        "housing-0001",
    ]
    assert [m.version for m in catalog.for_tenant("beta")] == ["core-0001"]
    assert catalog.for_control() == []


def test_a_feature_folder_needs_its_client_list(tmp_path):
    write(tmp_path, "features/housing/housing-0001_h.sql", "SELECT 1;")
    with pytest.raises(migrate.MigrationError, match=r"feature\.json"):
        migrate.load_catalog(tmp_path)


def test_a_feature_may_not_be_called_core(tmp_path):
    write(tmp_path, "features/core/feature.json", '{"tenants": []}')
    with pytest.raises(migrate.MigrationError, match="not 'core'"):
        migrate.load_catalog(tmp_path)


def test_the_real_migrations_folder_is_valid():
    catalog = migrate.load_catalog(migrate.MIGRATIONS_DIR)
    versions = [m.version for m in catalog.core]
    assert versions == sorted(versions)
    assert "core-0001" in versions
    by_name = {m.name: m for m in catalog.core}
    assert by_name["align_indexes"].no_transaction
    assert not by_name["align"].no_transaction
    assert not any(m.allow_destructive for m in catalog.core)
    for name, (tenants, _) in catalog.features.items():
        assert tenants, f"feature {name} lists no client"
    # the Godrej-only label clean-up reaches Godrej and nobody else
    assert "housing-0001" in [m.version for m in catalog.for_tenant("godrej")]
    assert "housing-0001" not in [m.version for m in catalog.for_tenant("baanganga")]


def test_missing_routing_address_stops_before_anything(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv(migrate.ROUTING_ENV, raising=False)
    assert migrate.main(["--dir", str(tmp_path)]) == 1
    assert "is not set" in capsys.readouterr().out


def test_a_remote_database_is_refused_without_the_flag(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv(
        migrate.ROUTING_ENV, "postgresql://user:topsecret@db.example.invalid:5432/x"
    )
    assert migrate.main(["--dir", str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "not on this computer" in out
    assert "topsecret" not in out
    assert "example.invalid" not in out


def test_changing_a_remote_database_also_needs_the_backup_flag(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setenv(
        migrate.ROUTING_ENV, "postgresql://user:topsecret@db.example.invalid:5432/x"
    )
    code = migrate.main(["--dir", str(tmp_path), "--apply", "--allow-remote"])
    out = capsys.readouterr().out
    assert code == 1
    assert "--backup-taken" in out
    assert "topsecret" not in out


# ------------------------------------------------------- a local database needed


async def _admin_run(statements):
    admin = await asyncpg.connect(ADMIN)
    try:
        for statement in statements:
            await admin.execute(statement)
    finally:
        await admin.close()


def _dsn_for(name):
    return urlsplit(ADMIN)._replace(path=f"/{name}").geturl()


def _query(dsn, sql, *args, execute=False):
    async def go():
        conn = await asyncpg.connect(dsn)
        try:
            if execute:
                return await conn.execute(sql, *args)
            return await conn.fetch(sql, *args)
        finally:
            await conn.close()

    return asyncio.run(go())


class World:
    """Three throwaway databases: a control one and two clients, alpha and beta."""

    def __init__(self, capsys):
        self.capsys = capsys
        suffix = uuid.uuid4().hex[:8]
        self.names = {k: f"migtest_{suffix}_{k}" for k in ("control", "alpha", "beta")}
        self.dsn = {k: _dsn_for(v) for k, v in self.names.items()}

    def create(self):
        asyncio.run(_admin_run([f'CREATE DATABASE "{n}"' for n in self.names.values()]))
        self.execute(
            "control",
            "CREATE TABLE public.data_sources ("
            "id uuid DEFAULT gen_random_uuid() NOT NULL, source_key text NOT NULL, "
            "database_url text NOT NULL, description text, "
            "created_at timestamptz DEFAULT now(), messaging_channel text)",
        )
        for key in ("alpha", "beta"):
            self.execute(
                "control",
                "INSERT INTO data_sources (source_key, database_url) VALUES ($1, $2)",
                key,
                self.dsn[key],
            )

    def drop(self):
        asyncio.run(
            _admin_run(
                [
                    f'DROP DATABASE IF EXISTS "{n}" WITH (FORCE)'
                    for n in self.names.values()
                ]
            )
        )

    def execute(self, which, sql, *args):
        return _query(self.dsn[which], sql, *args, execute=True)

    def rows(self, which, sql, *args):
        return _query(self.dsn[which], sql, *args)

    def versions(self, which):
        sql = "SELECT version FROM schema_migrations ORDER BY 1"
        return [r["version"] for r in self.rows(which, sql)]

    def has_table(self, which, name):
        sql = "SELECT to_regclass($1) IS NOT NULL AS found"
        return self.rows(which, sql, f"public.{name}")[0]["found"]

    def call(self, main, *argv):
        """Run a tool's main() with these arguments; returns (exit code, printed text)."""
        code = main(list(argv))
        return code, self.capsys.readouterr().out

    def run(self, root, *args):
        return self.call(migrate.main, "--dir", str(root), *args)


@pytest.fixture
def world(monkeypatch, capsys):
    if not migrate.dsn_is_local(ADMIN):
        pytest.fail("MIGRATE_TEST_PG must point at a Postgres on this computer")
    w = World(capsys)
    w.create()
    monkeypatch.setenv(migrate.ROUTING_ENV, w.dsn["control"])
    yield w
    w.drop()


@needs_pg
def test_a_plan_changes_nothing(world, tmp_path):
    write(tmp_path, "core/core-0001_t1.sql", CORE_1)
    for args in ([], ["--status"], ["--dry-run"], ["--apply", "--dry-run"]):
        code, out = world.run(tmp_path, *args)
        assert code == 0, out
        assert "waiting" in out
        assert "Plan only" in out
    for which in ("control", "alpha", "beta"):
        assert not world.has_table(which, "schema_migrations")
    assert not world.has_table("alpha", "t1")


@needs_pg
def test_plan_sessions_are_read_only(world, tmp_path, monkeypatch):
    seen = {}
    real = migrate.inspect

    async def sneaky(conn, plan, all_versions, report):
        try:
            await conn.execute("CREATE TABLE sneaky (id int)")
            seen["wrote"] = True
        except asyncpg.PostgresError as exc:
            seen["blocked"] = type(exc).__name__
        await real(conn, plan, all_versions, report)

    monkeypatch.setattr(migrate, "inspect", sneaky)
    world.run(tmp_path)
    assert "wrote" not in seen
    assert seen["blocked"] == "ReadOnlySQLTransactionError"


@needs_pg
def test_apply_then_apply_again_changes_nothing(world, tmp_path):
    write(tmp_path, "core/core-0001_t1.sql", CORE_1)
    code, out = world.run(tmp_path, "--apply")
    assert code == 0, out
    assert world.versions("alpha") == ["core-0001"]
    assert world.versions("beta") == ["core-0001"]
    assert world.versions("control") == []
    assert world.has_table("alpha", "t1")
    assert world.has_table("beta", "t1")
    assert not world.has_table("control", "t1")

    sql = "SELECT version, applied_at, checksum, applied_by FROM schema_migrations"
    before = [tuple(r) for r in world.rows("alpha", sql)]
    assert before[0][3]  # applied_by is filled in

    code, out = world.run(tmp_path, "--apply")
    assert code == 0, out
    assert "Applied 0 file(s)" in out
    assert [tuple(r) for r in world.rows("alpha", sql)] == before


@needs_pg
def test_failure_in_one_database_rolls_it_back_and_spares_the_others(world, tmp_path):
    world.execute("alpha", "CREATE TABLE only_alpha (id int)")
    write(tmp_path, "core/core-0001_t1.sql", CORE_1)
    write(
        tmp_path,
        "core/core-0002_extra.sql",
        "ALTER TABLE only_alpha ADD COLUMN IF NOT EXISTS extra int;\n",
    )
    code, out = world.run(tmp_path, "--apply")
    assert code == 2, out
    assert world.versions("alpha") == ["core-0001", "core-0002"]
    assert world.has_table("alpha", "t1")
    # beta has no only_alpha table, so core-0002 fails there and the WHOLE transaction
    # is undone - even core-0001, which was fine on its own.
    assert world.versions("beta") == []
    assert not world.has_table("beta", "t1")
    assert "undone" in out


@needs_pg
def test_a_second_run_cannot_overlap(world, tmp_path, capsys):
    write(tmp_path, "core/core-0001_t1.sql", CORE_1)

    async def scenario():
        holder = await asyncpg.connect(world.dsn["alpha"])
        try:
            await holder.fetchval("SELECT pg_advisory_lock($1)", migrate.LOCK_KEY)
            return await asyncio.to_thread(
                migrate.main, ["--dir", str(tmp_path), "--apply"]
            )
        finally:
            await holder.close()

    code = asyncio.run(scenario())
    out = capsys.readouterr().out
    assert code == 2
    assert "lock busy" in out
    assert not world.has_table("alpha", "schema_migrations")  # not touched at all
    assert world.versions("beta") == ["core-0001"]  # the others carried on


@needs_pg
def test_a_file_edited_after_it_was_applied_is_caught(world, tmp_path):
    path = write(tmp_path, "core/core-0001_t1.sql", CORE_1)
    assert world.run(tmp_path, "--apply")[0] == 0
    path.write_text(CORE_1 + "-- a late edit\n", encoding="utf-8", newline="\n")
    write(tmp_path, "core/core-0002_t2.sql", "CREATE TABLE IF NOT EXISTS t2 (id int);")
    code, out = world.run(tmp_path, "--apply")
    assert code == 2
    assert "CHANGED" in out
    assert not world.has_table("alpha", "t2")  # nothing new was applied
    code, out = world.run(tmp_path, "--status")
    assert code == 2
    assert "CHANGED" in out


@needs_pg
def test_no_transaction_files_run_in_order(world, tmp_path):
    write(tmp_path, "core/core-0001_t1.sql", CORE_1)
    write(
        tmp_path,
        "core/core-0002_index.sql",
        "-- no-transaction\nCREATE INDEX CONCURRENTLY IF NOT EXISTS t1_a_idx ON t1 (a);\n",
    )
    write(tmp_path, "core/core-0003_t3.sql", "CREATE TABLE IF NOT EXISTS t3 (id int);")
    code, out = world.run(tmp_path, "--apply")
    assert code == 0, out
    assert world.versions("alpha") == ["core-0001", "core-0002", "core-0003"]
    sql = (
        "SELECT i.indisvalid AS ok FROM pg_index i "
        "JOIN pg_class c ON c.oid = i.indexrelid WHERE c.relname = 't1_a_idx'"
    )
    assert [r["ok"] for r in world.rows("alpha", sql)] == [True]


@needs_pg
def test_an_invalid_index_is_a_failure(world, tmp_path):
    write(
        tmp_path,
        "core/core-0001_t1.sql",
        CORE_1 + "INSERT INTO t1 (a) VALUES (1), (1);\n",
    )
    write(
        tmp_path,
        "core/core-0002_unique.sql",
        "-- no-transaction\n"
        "CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS t1_a_uq ON t1 (a);\n",
    )
    code, out = world.run(tmp_path, "--apply")
    assert code == 2
    assert "PROBLEM" in out
    assert "invalid indexes" in out  # the leftover is listed
    assert world.versions("alpha") == ["core-0001"]  # core-0002 is not recorded
    # Second run: IF NOT EXISTS skips the broken index, but the tool still notices.
    code, out = world.run(tmp_path, "--apply")
    assert code == 2
    assert "invalid index was left behind" in out
    assert world.versions("alpha") == ["core-0001"]


@needs_pg
def test_feature_files_reach_only_the_listed_clients(world, tmp_path):
    write(tmp_path, "features/housing/feature.json", '{"tenants": ["alpha"]}')
    write(
        tmp_path,
        "features/housing/housing-0001_h.sql",
        "CREATE TABLE IF NOT EXISTS h (id int);\n",
    )
    code, out = world.run(tmp_path, "--apply")
    assert code == 0, out
    assert world.has_table("alpha", "h")
    assert not world.has_table("beta", "h")
    assert world.versions("alpha") == ["housing-0001"]
    assert world.versions("beta") == []


@needs_pg
def test_control_files_reach_only_the_routing_database(world, tmp_path):
    write(
        tmp_path,
        "control/control-0001_c.sql",
        "CREATE TABLE IF NOT EXISTS c1 (id int);\n",
    )
    code, out = world.run(tmp_path, "--apply")
    assert code == 0, out
    assert world.has_table("control", "c1")
    assert not world.has_table("alpha", "c1")
    assert world.versions("control") == ["control-0001"]


@needs_pg
def test_the_tenant_option_limits_a_run(world, tmp_path):
    write(tmp_path, "core/core-0001_t1.sql", CORE_1)
    code, out = world.run(tmp_path, "--apply", "--tenant", "beta")
    assert code == 0, out
    assert world.versions("beta") == ["core-0001"]
    assert not world.has_table("alpha", "schema_migrations")
    assert not world.has_table("control", "schema_migrations")
    code, out = world.run(tmp_path, "--tenant", "nobody")
    assert code == 1
    assert "unknown database" in out


@needs_pg
def test_an_unreachable_database_is_reported_without_secrets(world, tmp_path):
    world.execute(
        "control",
        "INSERT INTO data_sources (source_key, database_url) VALUES ('gamma', $1)",
        "postgresql://postgres:supersecret@127.0.0.1:1/nope",
    )
    write(tmp_path, "core/core-0001_t1.sql", CORE_1)
    code, out = world.run(tmp_path)
    assert code == 2
    assert "gamma" in out
    assert "could not connect" in out
    assert "supersecret" not in out
    assert "waiting" in out  # the other databases were still looked at


@needs_pg
def test_a_change_that_cannot_get_its_table_lock_gives_up_and_changes_nothing(
    world, tmp_path, capsys
):
    for which in ("alpha", "beta"):
        world.execute(which, "CREATE TABLE t1 (id int)")
    write(
        tmp_path,
        "core/core-0001_extra.sql",
        "ALTER TABLE t1 ADD COLUMN IF NOT EXISTS extra int;\n",
    )

    async def scenario():
        reader = await asyncpg.connect(world.dsn["alpha"])
        try:
            tx = reader.transaction()
            await tx.start()
            # an ordinary reader: it blocks any ALTER TABLE until it finishes
            await reader.execute("LOCK TABLE t1 IN ACCESS SHARE MODE")
            started = time.monotonic()
            code = await asyncio.to_thread(
                migrate.main,
                ["--dir", str(tmp_path), "--apply", "--lock-timeout", "1"],
            )
            return code, time.monotonic() - started
        finally:
            await reader.close()

    code, seconds = asyncio.run(scenario())
    out = capsys.readouterr().out
    assert code == 2
    assert seconds < 20  # it gave up after about a second instead of waiting
    assert "lock timeout" in out
    assert world.versions("alpha") == []  # nothing was recorded there
    columns = world.rows(
        "alpha",
        "SELECT column_name FROM information_schema.columns WHERE table_name = 't1'",
    )
    assert [r["column_name"] for r in columns] == ["id"]  # and nothing was added
    assert world.versions("beta") == [
        "core-0001"
    ]  # beta had no reader, so it went through


@needs_pg
def test_who_applied_a_file_can_be_set_from_the_environment(
    world, tmp_path, monkeypatch
):
    monkeypatch.setenv("MIGRATE_APPLIED_BY", "release-day")
    write(tmp_path, "core/core-0001_t1.sql", CORE_1)
    assert world.run(tmp_path, "--apply")[0] == 0
    rows = world.rows("alpha", "SELECT applied_by FROM schema_migrations")
    assert rows[0]["applied_by"] == "release-day"


@needs_pg
def test_a_version_with_no_file_is_a_note_not_a_failure(world, tmp_path):
    write(tmp_path, "core/core-0001_t1.sql", CORE_1)
    assert world.run(tmp_path, "--apply")[0] == 0
    world.execute(
        "alpha",
        "INSERT INTO schema_migrations (version, checksum, applied_by) "
        "VALUES ('core-9999', 'x', 'someone')",
    )
    code, out = world.run(tmp_path, "--status")
    assert code == 0
    assert "core-9999 is recorded as applied but has no file here" in out
