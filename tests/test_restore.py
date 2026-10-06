"""Tests for tools/restore.py.

The database tests need MIGRATE_TEST_PG (a Postgres on this computer) and the pg_dump,
pg_restore and psql programs; the others always run.
"""

import pytest

from tests.test_migrate import needs_pg
from tools import backup, migrate, restore

needs_tools = pytest.mark.skipif(
    any(backup.find_pg_tool(t) is None for t in ("pg_dump", "pg_restore", "psql")),
    reason="pg_dump / pg_restore / psql not found",
)

TOC = """;
; Archive created at 2026-10-05 11:49:00 IST
218; 1259 16452 TABLE public admin_events postgres
219; 0 16452 TABLE DATA public admin_events postgres
220; 1259 16999 VIEW public some_view postgres
221; 1259 17000 TABLE public users postgres
"""

SCRIPT = r"""SET x = 1;
COPY public.users (id, name) FROM stdin;
1	one
2	two
\.
COPY public."odd" (id) FROM stdin;
7
\.
COPY public.empty (id) FROM stdin;
\.
"""


def test_the_tables_of_an_archive_are_read_from_its_listing():
    assert restore.archive_tables(TOC) == {"admin_events", "users"}


def test_rows_are_counted_per_table_in_a_restore_script():
    assert restore.count_copy_rows(SCRIPT) == {"users": 2, "odd": 1, "empty": 0}


def test_the_newest_backup_of_that_database_is_chosen(tmp_path):
    for name in (
        "godrej_2026-10-01_0900.dump",
        "godrej_2026-10-05_1149.dump",
        "baanganga_2026-10-09_0000.dump",
    ):
        (tmp_path / name).write_bytes(b"x")
    assert restore.find_backup(tmp_path, "godrej").name == "godrej_2026-10-05_1149.dump"
    with pytest.raises(migrate.MigrationError, match="no backup of 'control'"):
        restore.find_backup(tmp_path, "control")


def test_another_databases_backup_is_refused(tmp_path):
    other = tmp_path / "baanganga_2026-10-05_1149.dump"
    other.write_bytes(b"x")
    with pytest.raises(migrate.MigrationError, match="does not look like a backup"):
        restore.find_backup(tmp_path, "godrej", str(other))
    with pytest.raises(migrate.MigrationError, match="was not found"):
        restore.find_backup(tmp_path, "godrej", str(tmp_path / "godrej_missing.dump"))
    assert restore.find_backup(tmp_path, "baanganga", str(other)) == other


def test_differences_say_what_would_be_lost():
    lines = restore.differences(
        {"a": 2, "b": 5, "c": 1}, {"a": 4, "b": 3, "d": 9, "c": 1}
    )
    assert lines == [
        "a: backup has 2 rows, now 4 (2 newer row(s) will be lost)",
        "b: backup has 5 rows, now 3 (rows come back)",
    ]


def test_exactly_one_database_must_be_named(capsys):
    assert restore.main([]) == 1
    assert "exactly one database" in capsys.readouterr().out
    assert restore.main(["--tenant", "a,b"]) == 1
    assert "exactly one database" in capsys.readouterr().out


def test_a_remote_database_is_refused_and_no_secret_is_printed(
    tmp_path, monkeypatch, capsys
):
    (tmp_path / "x_2026-10-05_1149.dump").write_bytes(b"x")
    monkeypatch.setenv(
        migrate.ROUTING_ENV, "postgresql://user:topsecret@db.example.invalid:5432/x"
    )
    code = restore.main(["--tenant", "control", "--from", str(tmp_path)])
    out = capsys.readouterr().out
    assert code == 1
    assert "no backup of 'control'" in out or "not on this computer" in out
    code = restore.main(["--tenant", "x", "--from", str(tmp_path)])
    out = capsys.readouterr().out
    assert code == 1
    assert "not on this computer" in out
    assert "topsecret" not in out
    assert "example.invalid" not in out


# ------------------------------------------------------- a local database needed


def _fixture_tables(world):
    world.execute(
        "alpha",
        "CREATE TABLE parent (id int PRIMARY KEY, note text);"
        "CREATE TABLE child (id int PRIMARY KEY, parent_id int REFERENCES parent (id));"
        "INSERT INTO parent VALUES (1, 'café नमस्ते 📋'), (2, 'two');"
        "INSERT INTO child VALUES (1, 1), (2, 2), (3, 2);",
    )


def _change_after_the_backup(world):
    """What a migration plus some new traffic could do: a new column, a new index, a NEW
    table that points at an old one, and newer rows."""
    world.execute(
        "alpha",
        "ALTER TABLE parent ADD COLUMN extra int;"
        "CREATE INDEX parent_note_idx ON parent (note);"
        "CREATE TABLE added (id int PRIMARY KEY, parent_id int REFERENCES parent (id));"
        "INSERT INTO added VALUES (1, 1);"
        "INSERT INTO parent VALUES (3, 'three');",
    )


def _state(world):
    tables = [
        r["tablename"]
        for r in world.rows(
            "alpha",
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY 1",
        )
    ]
    columns = [
        r["column_name"]
        for r in world.rows(
            "alpha",
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'parent' ORDER BY ordinal_position",
        )
    ]
    indexes = [
        r["indexname"]
        for r in world.rows(
            "alpha",
            "SELECT indexname FROM pg_indexes WHERE schemaname = 'public' ORDER BY 1",
        )
    ]
    parent_rows = world.rows("alpha", "SELECT count(*) AS n FROM parent")[0]["n"]
    return tables, columns, indexes, parent_rows


@needs_pg
@needs_tools
def test_a_backup_goes_back_even_when_a_new_table_points_at_an_old_one(world, tmp_path):
    _fixture_tables(world)
    original = _state(world)
    assert world.call(backup.main, "--to", str(tmp_path))[0] == 0
    _change_after_the_backup(world)
    assert _state(world) != original

    # the plan says what will happen and changes nothing
    changed = _state(world)
    code, out = world.call(restore.main, "--tenant", "alpha", "--from", str(tmp_path))
    assert code == 0, out
    assert "REMOVED (the backup does not have them): added" in out
    assert "parent: backup has 2 rows, now 3 (1 newer row(s) will be lost)" in out
    assert "Plan only" in out
    assert _state(world) == changed

    # the real thing puts everything back, exactly
    code, out = world.call(
        restore.main,
        "--tenant",
        "alpha",
        "--from",
        str(tmp_path),
        "--yes-restore",
        "alpha",
    )
    assert code == 0, out
    assert "Restored and checked" in out
    assert _state(world) == original


@needs_pg
@needs_tools
def test_a_restore_that_fails_changes_nothing(world, tmp_path):
    _fixture_tables(world)
    assert world.call(backup.main, "--to", str(tmp_path))[0] == 0
    _change_after_the_backup(world)
    # a view made after the backup depends on an old table, so that table cannot be
    # dropped: the restore must fail as a whole
    world.execute("alpha", "CREATE VIEW newer_view AS SELECT * FROM child")
    changed = _state(world)
    code, out = world.call(
        restore.main,
        "--tenant",
        "alpha",
        "--from",
        str(tmp_path),
        "--yes-restore",
        "alpha",
    )
    assert code == 2, out
    assert "undone" in out
    assert _state(world) == changed  # not even the new table was removed
    views = world.rows(
        "alpha", "SELECT count(*) AS n FROM pg_views WHERE viewname = 'newer_view'"
    )
    assert views[0]["n"] == 1


@needs_pg
@needs_tools
def test_a_restore_whose_result_does_not_match_the_backup_is_reported(
    world, tmp_path, monkeypatch
):
    _fixture_tables(world)
    assert world.call(backup.main, "--to", str(tmp_path))[0] == 0
    real = restore.live_counts
    calls = {"n": 0}

    async def lying(target, opts):
        counts = await real(target, opts)
        calls["n"] += 1
        if calls["n"] == 2:  # the check made after the restore
            counts["parent"] = counts.get("parent", 0) + 1
        return counts

    monkeypatch.setattr(restore, "live_counts", lying)
    code, out = world.call(
        restore.main,
        "--tenant",
        "alpha",
        "--from",
        str(tmp_path),
        "--yes-restore",
        "alpha",
    )
    assert code == 2
    assert "do not match the backup" in out
    assert "parent" in out


@needs_pg
@needs_tools
def test_the_wrong_name_or_no_name_only_shows_the_plan(world, tmp_path):
    _fixture_tables(world)
    assert world.call(backup.main, "--to", str(tmp_path))[0] == 0
    _change_after_the_backup(world)
    changed = _state(world)
    for extra in ([], ["--yes-restore", "beta"], ["--yes-restore", "yes"]):
        code, out = world.call(
            restore.main, "--tenant", "alpha", "--from", str(tmp_path), *extra
        )
        assert code == 0, out
        assert "Plan only" in out
        assert _state(world) == changed


@needs_pg
@needs_tools
def test_another_databases_file_is_refused_by_name(world, tmp_path):
    assert world.call(backup.main, "--to", str(tmp_path))[0] == 0
    beta_file = next(tmp_path.glob("beta_*.dump"))
    code, out = world.call(
        restore.main,
        "--tenant",
        "alpha",
        "--file",
        str(beta_file),
        "--yes-restore",
        "alpha",
    )
    assert code == 1
    assert "does not look like a backup of 'alpha'" in out


@needs_pg
@needs_tools
def test_no_password_is_printed_by_a_restore(world, tmp_path, monkeypatch):
    _fixture_tables(world)
    world.execute(
        "control",
        "UPDATE data_sources SET database_url = "
        "replace(database_url, '://postgres@', '://postgres:s3cret@')",
    )
    monkeypatch.setenv(
        migrate.ROUTING_ENV,
        world.dsn["control"].replace("://postgres@", "://postgres:s3cret@"),
    )
    assert world.call(backup.main, "--to", str(tmp_path))[0] == 0
    _change_after_the_backup(world)
    code, out = world.call(
        restore.main,
        "--tenant",
        "alpha",
        "--from",
        str(tmp_path),
        "--yes-restore",
        "alpha",
    )
    assert code == 0, out
    assert "s3cret" not in out
    assert "127.0.0.1" not in out
