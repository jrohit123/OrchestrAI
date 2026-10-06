"""
prompt_loader.py
Loads the system prompt for an org: the shared rules, then its industry's, then its own notes.
Loading order: _base.txt -> {industry}.txt -> clients/{slug}.txt

Each of the three layers is a text the dashboard can change (see config_store.py). A text written
in the database wins; with none, the file is used, exactly as before.
"""

from pathlib import Path

from app.services import config_store

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def industry_of(org_row: dict) -> str:
    """The organisation's industry as the prompt files and the saved texts name it
    ("Housing Society" is "housing_society"); empty when it has none."""
    return (org_row.get("industry") or "").lower().replace(" ", "_").replace("-", "_")


def _layers(org_row: dict) -> list[tuple[str, str | None, str | None]]:
    """(key, industry for that layer, the text from the file) for each layer, in order."""
    industry = industry_of(org_row)
    slug = (org_row.get("slug") or "").lower()
    return [
        ("agent.shared", None, _read(PROMPTS_DIR / "_base.txt")),
        (
            "agent.industry",
            industry or None,
            _read(PROMPTS_DIR / f"{industry}.txt") if industry else None,
        ),
        (
            "agent.client",
            None,
            _read(PROMPTS_DIR / "clients" / f"{slug}.txt") if slug else None,
        ),
    ]


def built_in(org_row: dict) -> dict[str, str]:
    """The text each layer has in the prompt files, by key ('' when the layer has no file)."""
    return {key: text or "" for key, _, text in _layers(org_row)}


def load_prompt(org_row: dict) -> str:
    """The prompt from the files only.
    org_row must contain: industry (str), slug (str)
    """
    return "\n\n".join(text for _, _, text in _layers(org_row) if text)


async def load_domain_prompt(org_row: dict, source_key: str | None) -> str:
    """The same prompt, but each layer is first looked for in the org's database. With nothing
    saved there the result is identical to load_prompt()."""
    parts: list[str] = []
    for key, industry, from_file in _layers(org_row):
        text = await config_store.prompt(
            source_key, key, from_file or "", pack=industry
        )
        if text and text.strip():
            parts.append(text.strip())
    return "\n\n".join(parts)


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
