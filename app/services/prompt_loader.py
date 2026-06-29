"""
prompt_loader.py
Loads system prompt from files based on org industry and slug.
Loading order: _base.txt → {industry}.txt → clients/{slug}.txt
"""
from pathlib import Path

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def load_prompt(org_row: dict) -> str:
    """
    Build domain-specific prompt for this org.
    org_row must contain: industry (str), slug (str)
    """
    parts: list[str] = []

    base = _read(PROMPTS_DIR / "_base.txt")
    if base:
        parts.append(base)

    industry = (org_row.get("industry") or "").lower().replace(" ", "_").replace("-", "_")
    if industry:
        ind = _read(PROMPTS_DIR / f"{industry}.txt")
        if ind:
            parts.append(ind)

    slug = (org_row.get("slug") or "").lower()
    if slug:
        client = _read(PROMPTS_DIR / "clients" / f"{slug}.txt")
        if client:
            parts.append(client)

    return "\n\n".join(parts)


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
