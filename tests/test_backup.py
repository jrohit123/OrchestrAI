"""Tests for tools/backup.py.

The database tests need MIGRATE_TEST_PG (a Postgres on this computer) and the pg_dump and
pg_restore programs; the others always run.
"""

import asyncio
import subprocess

import pytest

from tests.test_migrate import _admin_run, _dsn_for, needs_pg
from tools import backup, migrate

needs_tools = pytest.mark.skipif(
    backup.find_pg_tool("pg_dump") is None or backup.find_pg_tool("pg_restore") is None,
    reason="pg_dump / pg_restore not found",
)


def test_an_address_becomes_environment_settings():
    env = backup.dsn_to_pg_env(
        "postgresql://us%40er:p%40ss%3Aword@db.example.com:5433/my_db?sslmode=require"
    )
    assert env == {
        "PGHOST": "db.example.com",
        "PGPORT": "5433",
        "PGUSER": "us@er",
        "PGPASSWORD": "p@ss:word",
        "PGDATABASE": "my_db",
        "PGSSLMODE": "require",
    }
    assert backup.dsn_to_pg_env("postgres://localhost/x") == {
        "PGHOST": "localhost",
        "PGDATABASE": "x",
    }


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "mysql://u:p@h/x",
        "host=localhost dbname=x",
        "postgresql://u:p@h1,h2/x",
        "postgresql:///x",
    ],
)
def test_unusual_addresses_are_refused(bad):
    with pytest.raises(migrate.MigrationError):
        backup.dsn_to_pg_env(bad)


def test_error_messages_from_pg_dump_lose_hosts_and_names():
    message = (
        'pg_dump: error: connection to server at "db.secret.example" (10.1.2.3), '
        'port 5432 failed: FATAL:  password authentication failed for user "bob"'
    )
    out = backup.safe_message(message)
    for secret in ("db.secret.example", "10.1.2.3", "bob"):
        assert secret not in out


def test_the_default_folder_is_outside_the_project_and_inside_is_refused():
    assert backup.choose_folder(None) == backup.DEFAULT_FOLDER.resolve()
    with pytest.raises(migrate.MigrationError, match="inside the project"):
        backup.choose_folder(str(backup.REPO_ROOT / "backups"))
    with pytest.raises(migrate.MigrationError, match="inside the project"):
        backup.choose_folder(str(backup.REPO_ROOT))


def test_a_folder_inside_the_project_stops_the_run(monkeypatch, capsys):
    monkeypatch.setenv(migrate.ROUTING_ENV, "postgresql://u:p@127.0.0.1:1/x")
    assert backup.main(["--to", str(backup.REPO_ROOT / "backups")]) == 1
    assert "inside the project" in capsys.readouterr().out


def test_a_remote_database_is_refused_and_no_secret_is_printed(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setenv(
        migrate.ROUTING_ENV, "postgresql://user:topsecret@db.example.invalid:5432/x"
    )
    assert backup.main(["--to", str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "not on this computer" in out
    assert "topsecret" not in out
    assert "example.invalid" not in out
    assert not list(tmp_path.iterdir())


@needs_pg
@needs_tools
def test_each_database_is_saved_readable_and_no_password_is_printed(
    world,
    tmp_path,
    monkeypatch,
):
    world.execute("alpha", "CREATE TABLE keepsake (id int, note text)")
    world.execute(
        "alpha", "INSERT INTO keepsake VALUES (1, 'café नमस्ते 📋'), (2, 'two')"
    )
    # give every address a password (the local login ignores it) to prove it never shows up
    world.execute(
        "control",
        "UPDATE data_sources SET database_url = "
        "replace(database_url, '://postgres@', '://postgres:s3cret@')",
    )
    monkeypatch.setenv(
        migrate.ROUTING_ENV,
        world.dsn["control"].replace("://postgres@", "://postgres:s3cret@"),
    )
    code, out = world.call(backup.main, "--to", str(tmp_path))
    assert code == 0, out
    assert "s3cret" not in out
    names = sorted(p.name.split("_")[0] for p in tmp_path.glob("*.dump"))
    assert names == ["alpha", "beta", "control"]
    assert len(list(tmp_path.glob("backup_*.txt"))) == 1

    # the saved file really restores into a fresh database
    restored = f"{world.names['alpha']}_restored"
    asyncio.run(_admin_run([f'CREATE DATABASE "{restored}"']))
    try:
        dump = next(tmp_path.glob("alpha_*.dump"))
        done = subprocess.run(
            [
                str(backup.find_pg_tool("pg_restore")),
                "--no-owner",
                "--dbname",
                _dsn_for(restored),
                str(dump),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert done.returncode == 0, done.stderr
        count = migrate_rows(restored, "SELECT count(*) AS n FROM keepsake")
        assert count == 2
    finally:
        asyncio.run(_admin_run([f'DROP DATABASE IF EXISTS "{restored}" WITH (FORCE)']))


def migrate_rows(name, sql):
    import asyncpg

    async def go():
        conn = await asyncpg.connect(_dsn_for(name))
        try:
            return await conn.fetchval(sql)
        finally:
            await conn.close()

    return asyncio.run(go())


@needs_pg
@needs_tools
def test_a_database_that_fails_is_reported_and_the_others_are_still_saved(
    world,
    tmp_path,
    monkeypatch,
):
    world.execute(
        "control",
        "UPDATE data_sources SET database_url = "
        "replace(database_url, '://postgres@', '://postgres:s3cret@')",
    )
    world.execute(
        "control",
        "UPDATE data_sources SET database_url = "
        "replace(database_url, $1, 'no_such_database') WHERE source_key = 'beta'",
        world.names["beta"],
    )
    monkeypatch.setenv(
        migrate.ROUTING_ENV,
        world.dsn["control"].replace("://postgres@", "://postgres:s3cret@"),
    )
    code, out = world.call(backup.main, "--to", str(tmp_path))
    assert code == 2
    assert "PROBLEM" in out
    assert "NOT backed up" in out
    assert "s3cret" not in out
    assert "127.0.0.1" not in out
    names = sorted(p.name.split("_")[0] for p in tmp_path.glob("*.dump"))
    assert names == ["alpha", "control"]  # beta failed, the rest were saved
