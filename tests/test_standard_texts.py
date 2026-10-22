"""The standard texts kept in the database (migrations core-0011, housing-0003 and jewellery-0001).

They are the texts the code has always used, so storing them changes nothing for anyone. These tests
need no database: they read the migration files, and keep the stored text and the text in the code
from drifting apart. If one fails because the code's text changed, the stored copy has to change too:
add a NEW numbered migration that inserts the next version (python -m tools.seed_texts), never edit
a migration that was applied.
"""

import re
from pathlib import Path

import pytest

from app.services import config_store, platform_prompt, prompt_loader
from app.services.messages import MESSAGES
from tools import migrate, seed_texts

ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS = ROOT / "migrations"
PROMPTS = ROOT / "app" / "prompts"

# one stored text: (key, locale, scope, scope_ref, version, $tag$ the text $tag$
_MESSAGE = re.compile(
    r"\(\s*'(?P<key>[^']+)',\s*'en-IN',\s*'global',\s*'',\s*(?P<version>\d+),\s*"
    r"(?P<tag>\$[a-z0-9]+\$)(?P<body>.*?)(?P=tag)",
    re.DOTALL,
)
# the same for a prompt: (key, scope, scope_ref, version, $tag$ the text $tag$
_PROMPT = re.compile(
    r"\(\s*'(?P<key>[^']+)',\s*'(?P<scope>global|pack)',\s*'(?P<ref>[^']*)',\s*(?P<version>\d+),\s*"
    r"(?P<tag>\$[a-z0-9]+\$)(?P<body>.*?)(?P=tag)",
    re.DOTALL,
)


def _files(folder: Path, prefix: str) -> list[Path]:
    return sorted(folder.glob(f"{prefix}-*.sql"))


def _newest(rows) -> dict:
    """key (and scope, reference) -> (version, text) of the newest stored version."""
    found: dict = {}
    for ident, version, body in rows:
        if ident not in found or version > found[ident][0]:
            found[ident] = (version, body)
    return found


def _stored_messages() -> dict[str, tuple[int, str]]:
    rows = []
    for path in _files(MIGRATIONS / "core", "core"):
        sql = path.read_text(encoding="utf-8")
        if "INSERT INTO public.system_messages" not in sql:
            continue
        rows += [
            (m["key"], int(m["version"]), m["body"]) for m in _MESSAGE.finditer(sql)
        ]
    return _newest(rows)


def _stored_prompts(folder: Path, prefix: str) -> dict[tuple, tuple[int, str]]:
    rows = []
    for path in _files(folder, prefix):
        sql = path.read_text(encoding="utf-8")
        if "INSERT INTO public.prompts" not in sql:
            continue
        rows += [
            ((m["key"], m["scope"], m["ref"]), int(m["version"]), m["body"])
            for m in _PROMPT.finditer(sql)
        ]
    return _newest(rows)


# ------------------------------------------------------------ the stored text is the text in the code


def test_every_message_is_stored_and_the_newest_stored_wording_is_the_one_in_the_code():
    stored = _stored_messages()
    assert set(stored) == set(MESSAGES), (
        "A message is missing from the stored standard wording, or one is stored that the code no "
        "longer has. Add a migration: python -m tools.seed_texts messages --keys <key> --version <n>"
    )
    for key, (version, body) in stored.items():
        assert body == MESSAGES[key].text, (
            f"The wording of {key} in the code is not the newest stored one (version {version}). "
            f"Add a migration: python -m tools.seed_texts messages --keys {key} --version {version + 1}"
        )


def test_the_stored_reply_style_is_the_one_in_the_code():
    stored = _stored_prompts(MIGRATIONS / "core", "core")
    version, body = stored[(prompt_loader.REPLY_STYLE_KEY, "global", "")]
    assert body == prompt_loader.reply_style_built_in(), (
        f"The reply style in the code is not the newest stored one (version {version}). Add a "
        "migration: python -m tools.seed_texts prompt agent.reply_style --scope global --file "
        f"app/prompts/response_formatting.txt --version {version + 1}"
    )


@pytest.mark.parametrize(
    ("feature", "industry"),
    [("housing", "housing_society"), ("jewellery", "jewellery")],
)
def test_the_stored_industry_text_is_the_one_in_the_code(feature, industry):
    stored = _stored_prompts(MIGRATIONS / "features" / feature, feature)
    version, body = stored[("agent.industry", "pack", industry)]
    text = (PROMPTS / f"{industry}.txt").read_text(encoding="utf-8").strip()
    assert body == text, (
        f"The text app/prompts/{industry}.txt is not the newest stored one (version {version}). "
        f"Add a migration: python -m tools.seed_texts prompt agent.industry --scope pack --ref "
        f"{industry} --file app/prompts/{industry}.txt --version {version + 1}"
    )


# ------------------------------------------------------------ the files are fit to be applied


@pytest.mark.parametrize(
    ("folder", "prefix"),
    [
        (MIGRATIONS / "core", "core"),
        (MIGRATIONS / "features" / "housing", "housing"),
        (MIGRATIONS / "features" / "jewellery", "jewellery"),
    ],
)
def test_the_migration_tool_accepts_the_files(folder, prefix):
    # the tool's own reading and safety check (a text that holds a word it refuses would stop here)
    assert migrate.load_group(folder, prefix)


@pytest.mark.parametrize(
    "path",
    [
        MIGRATIONS / "core" / "core-0011_standard_texts.sql",
        MIGRATIONS / "core" / "core-0013_busy_text.sql",
        MIGRATIONS / "core" / "core-0015_closed_signup_text.sql",
        MIGRATIONS / "core" / "core-0016_hold_texts.sql",
        MIGRATIONS / "core" / "core-0017_whatsapp_link_texts.sql",
        MIGRATIONS / "core" / "core-0018_photo_texts.sql",
        MIGRATIONS / "core" / "core-0019_email_setup_texts.sql",
        MIGRATIONS / "features" / "housing" / "housing-0003_industry_text.sql",
        MIGRATIONS / "features" / "jewellery" / "jewellery-0001_industry_text.sql",
    ],
)
def test_a_standard_text_file_only_adds_rows_and_is_safe_to_run_twice(path):
    sql, _ = migrate.read_sql(path)
    # the code of each statement, with the comments and the quoted texts blanked out
    statements = [code.strip() for _, code in migrate.split_statements(sql)]
    assert statements and all(s.startswith("INSERT INTO public.") for s in statements)
    assert all("ON CONFLICT" in s and "DO NOTHING" in s for s in statements)


# ------------------------------------------------------------ the generator


def test_the_generator_quotes_a_text_without_changing_it():
    assert seed_texts.dollar("it's {a}") == "$txt$it's {a}$txt$"
    assert (
        seed_texts.dollar("a $txt$ b") == "$txt1$a $txt$ b$txt1$"
    )  # a tag the text lacks
    sql = seed_texts.messages_sql(2, ["otp.cooldown"])
    assert "'otp.cooldown', 'en-IN', 'global', '', 2," in sql
    assert '["wait_seconds"]' in sql and "ON CONFLICT" in sql
    assert MESSAGES["otp.cooldown"].text in sql


def test_the_generator_refuses_a_text_that_is_neither_global_nor_an_industrys():
    with pytest.raises(ValueError):
        seed_texts.prompt_sql("agent.client", "tenant", "", "x")
    with pytest.raises(ValueError):
        seed_texts.prompt_sql(
            "agent.industry", "pack", "", "x"
        )  # an industry's needs its name
    with pytest.raises(ValueError):
        seed_texts.prompt_sql("agent.reply_style", "global", "housing", "x")


# ------------------------------------------------------------ filling in the reply style


def test_filling_in_the_reply_style_gives_exactly_what_the_old_way_gave():
    template = prompt_loader.reply_style_built_in()
    values = {
        "workflow_name": "Stock {low}",
        "glossary_json": '{"sku": "item code"}',
        "raw_data": '[{"sku": "A1", "qty": 4}]\nit\'s "fine" {x}',
        **platform_prompt.defaults(),
    }
    assert config_store.fill(template, values) == template.format(**values)
