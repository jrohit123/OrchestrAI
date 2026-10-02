"""Checks for app/services/sql_guard.py. No database needed. Run:  python tests/check_sql_guard.py

Part 1: queries the assistant legitimately writes must pass.
Part 2: everything that has to be refused, including the bypasses that the old text-based check let through.
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for key in (
    "ROUTING_DATABASE_URL",
    "ADMIN_TOKEN",
    "WHATSAPP_VERIFY_TOKEN",
    "WHATSAPP_APP_SECRET",
    "WHATSAPP_TOKEN",
    "OPENAI_API_KEY",
    "BREVO_API_KEY",
    "SENDER_EMAIL",
    "SENDER_NAME",
    "TELEGRAM_BOT_TOKEN",
    "REDIS_URL",
):
    os.environ.setdefault(key, "postgresql://x@127.0.0.1:1/x" if "URL" in key else "x")

from app.services.query_engine import SENSITIVE_COLS  # noqa: E402
from app.services.sql_guard import GuardError, prepare  # noqa: E402

ORG = "793eead0-31b2-4538-b9b3-1885f9e94604"
SCOPED = {"cases", "case_activity", "users"}
ALLOWED = {"cases", "case_activity", "users"}


def run(sql, allowed=ALLOWED):
    return prepare(
        sql,
        allowed_tables=allowed,
        org_id=ORG,
        org_scoped_tables=SCOPED,
        hidden_columns=SENSITIVE_COLS,
    )


GOOD = [
    "SELECT status, count(*) FROM cases WHERE status <> $1 GROUP BY 1",
    "SELECT c.case_number, c.title FROM cases c WHERE c.title ILIKE '%' || $1 || '%' ORDER BY c.created_at DESC LIMIT 20",
    "WITH o AS (SELECT * FROM cases WHERE status <> 'closed') SELECT count(*) FROM o",
    "SELECT c.title, a.activity_type FROM cases c JOIN case_activity a ON a.case_id = c.id",
    "SELECT count(*) FROM cases WHERE created_at > now() - interval '7 days'",
    "SELECT title FROM cases UNION SELECT title FROM cases",
    f"SELECT c.title FROM cases c WHERE c.org_id = '{ORG}'::uuid",
    "SELECT date_trunc('day', created_at) AS d, count(*) FROM cases GROUP BY 1 ORDER BY 1",
    "SELECT title FROM cases WHERE id IN (SELECT case_id FROM case_activity)",
    "SELECT title, row_number() OVER (ORDER BY created_at) FROM cases",
    "SELECT (SELECT count(*) FROM cases x WHERE x.org_id = c.org_id) AS n FROM cases c",
    "SELECT extract(epoch FROM (now() - created_at)) FROM cases",
    "SELECT coalesce(assigned_to_id::text, 'none') FROM cases",
    "SELECT u.name, count(c.id) FROM users u LEFT JOIN cases c ON c.assigned_to_id = u.id WHERE u.name ILIKE $1 GROUP BY u.name",
    "SELECT * FROM cases",
]
BAD = [
    ("comma join to a table the role may not read", "SELECT u.name FROM cases c, users u", {"cases"}),
    ("a table the role may not read", "SELECT name FROM users", {"cases"}),
    ("phone renamed on the way out", "SELECT u.phone AS contact FROM users u", ALLOWED),
    ("phone inside a function", "SELECT lower(email) FROM users", ALLOWED),
    ("hidden column through a subquery", "SELECT p FROM (SELECT phone AS p FROM users) s", ALLOWED),
    ("an id column in the select list", "SELECT org_id FROM cases", ALLOWED),
    ("two statements", "SELECT 1; DELETE FROM cases", ALLOWED),
    ("delete", "DELETE FROM cases", ALLOWED),
    ("update", "UPDATE cases SET status = 'closed'", ALLOWED),
    ("insert", "INSERT INTO cases (title) VALUES ('x')", ALLOWED),
    ("drop", "DROP TABLE cases", ALLOWED),
    ("data-changing CTE", "WITH x AS (DELETE FROM cases RETURNING *) SELECT * FROM x", ALLOWED),
    ("sleep", "SELECT pg_sleep(10)", ALLOWED),
    ("system catalog", "SELECT * FROM pg_catalog.pg_tables", ALLOWED),
    ("information schema", "SELECT * FROM information_schema.columns", ALLOWED),
    ("select into", "SELECT * INTO newtable FROM cases", ALLOWED),
    ("row lock", "SELECT * FROM cases FOR UPDATE", ALLOWED),
    ("setting read", "SELECT current_setting('server_version')", ALLOWED),
    ("setting write", "SELECT set_config('a', 'b', false)", ALLOWED),
    ("sequence", "SELECT nextval('seq')", ALLOWED),
    ("version", "SELECT version()", ALLOWED),
    ("table function", "SELECT * FROM generate_series(1, 5)", ALLOWED),
    ("not SQL", "SELEC * FRM", ALLOWED),
    ("explain", "EXPLAIN SELECT * FROM cases", ALLOWED),
]

failed = 0
for sql in GOOD:
    try:
        run(sql)
    except GuardError as e:
        failed += 1
        print("FAIL (should pass):", sql, "->", e)
for why, sql, allowed in BAD:
    try:
        run(sql, allowed)
        failed += 1
        print("FAIL (should be refused):", why, "|", sql)
    except GuardError:
        pass

# what the rewrite does
sql, tables = run("SELECT c.title FROM cases c WHERE 1 = 1 OR c.org_id = c.org_id")
if f"org_id = '{ORG}'" not in sql or "(SELECT * FROM cases" not in sql:
    failed += 1
    print("FAIL: the organisation filter was not built in:", sql)
for given, expect in (("", 100), (" LIMIT 500", 100), (" LIMIT 10", 10)):
    out, _ = run("SELECT title FROM cases" + given)
    m = re.search(r"LIMIT (\d+)", out)
    if not m or int(m.group(1)) != expect:
        failed += 1
        print(f"FAIL: limit '{given}' became", m.group(0) if m else "nothing", "expected", expect)
out, _ = run("SELECT title FROM cases UNION SELECT title FROM cases")
if "LIMIT 100" not in out:
    failed += 1
    print("FAIL: a UNION got no row limit:", out)

total = len(GOOD) + len(BAD) + 5
print(f"sql_guard: {total - failed} of {total} checks passed")
sys.exit(1 if failed else 0)
